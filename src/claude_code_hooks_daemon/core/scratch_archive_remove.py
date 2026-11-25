"""Remove a claimed, archived tree; resume a leftover claim (Plan 00627 Task 3.4).

DESIGN.md section 5.2 step 6 and section 5.3. This module holds every
``unlink`` and ``rmdir`` of entry content (a test pins that). It removes only
after its own proof, never on a caller's word:

* the name is one claim (``.sweeping-<name>``), the store lock is held, the
  record handed in is the one the index holds, and it names this entry;
* the tree is walked, the archive verified against it with the recorded
  SHA-256, and the tree walked again; both walks must be identical, and the
  skipped special files must be the ones the record lists.

Removal is driven by that second listing, never by a fresh scan. Each name is
``lstat``-ed through its directory's descriptor and must still be the listed
inode before it goes; directories are opened ``O_NOFOLLOW`` and must stay on
the root's device and mount (a same-filesystem bind mount keeps ``st_dev``, so
the mount id is compared too). A name that is not listed makes ``rmdir`` fail,
which stops the removal. Any refusal leaves the rest under its claimed name.

A leftover claim is resumed by :func:`resume_claimed`: removed when an archive
recorded for it verifies against what is left (whole, or a partly removed
tree), and renamed back otherwise. Only a claim a sweep recorded with
:func:`record_claim` before its rename is resumed; any other ``.sweeping-*``
name is reported foreign and left alone.
"""

from __future__ import annotations

import errno
import logging
import os
import stat
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from claude_code_hooks_daemon.core.scratch_archive import (
    ArchiveRecord,
    ArchiveStore,
    ClaimEvent,
    StoreRefused,
)
from claude_code_hooks_daemon.core.scratch_archive_adopt import PROOF_ID as ADOPT_PROOF
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    CLAIM_PREFIX,
    DEFAULT_MAX_DEPTH,
    ClaimRefused,
    Fingerprint,
    Node,
    TreeListing,
    WalkRefused,
    check_entry_name,
    check_name,
    fingerprint_of,
    kind_of,
    open_child_dir,
    rename_noreplace,
    walk_tree,
)
from claude_code_hooks_daemon.core.scratch_archive_expire import (
    Due,
    Incomplete,
    require_not_due,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    DEFAULT_TAR_TIMEOUT_SECONDS,
    PackRefused,
    TarDidNotRun,
    TarTool,
    VerifyFailed,
    members_of,
    refuse_unrestorable,
    verify,
    verify_remaining,
)
from claude_code_hooks_daemon.utils.birth_time import BirthStamp, birth_stamp
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

_LOG = logging.getLogger(__name__)

_FDINFO_PARTS = ("", "proc", "self", "fdinfo")
_MNT_ID = "mnt_id:"


class RemoveRefused(Exception):
    """Nothing more was removed; what is left stays under its claimed name."""


class ProofUnavailable(RemoveRefused):
    """The archive could not be checked at all (tar did not run); nothing was learned."""


@dataclass(frozen=True)
class Removed:
    """A claimed entry that is gone; ``link_target`` is set when the entry was a link."""

    claimed_name: str
    archive_id: str
    removed: int
    link_target: str | None
    partial: bool


@dataclass(frozen=True)
class Resumed:
    """What became of a leftover claim: removed, renamed-back, stuck, absent or foreign.

    ``foreign``: no claim event covers the name, so a sweep did not make it; untouched.
    """

    name: str
    outcome: str
    reason: str
    removed: Removed | None = None


@dataclass(frozen=True)
class _Proof:
    claimed_name: str
    record: ArchiveRecord
    listing: TreeListing
    partial: bool


def entry_name_of(claimed_name: str) -> str:
    """Return the entry name a claim stands for; raise :class:`RemoveRefused` otherwise."""
    try:
        check_name(claimed_name)
        if not claimed_name.startswith(CLAIM_PREFIX):
            raise ValueError(f"{claimed_name!r} is not a claimed name")
        return check_entry_name(claimed_name[len(CLAIM_PREFIX) :])
    except ValueError as exc:
        raise RemoveRefused(str(exc)) from exc


def _index(store: ArchiveStore) -> tuple[ArchiveRecord, ...]:
    try:
        store.require_lock("remove")
        return store.read_index().records
    except StoreRefused as exc:
        raise RemoveRefused(str(exc)) from exc


def _removable(
    store: ArchiveStore,
    archive_id: str,
    clock: Callable[[], datetime],
    retention_hours: Mapping[str, float],
) -> None:
    """Refuse an archive the events file says is expired, due or not complete.

    Read under the store lock the removal holds, so the answer stands for the
    whole removal. Any doubt (a torn tail, a bad clock, an unparsable keep)
    refuses: a tree is never removed against an archive expiry may delete.
    """
    try:
        now = clock()
    except Exception as exc:
        raise RemoveRefused(f"the clock failed: {exc}") from exc
    if not isinstance(now, datetime):
        raise RemoveRefused("the clock did not return an instant")
    try:
        require_not_due(store.read_index(), store.read_events(), archive_id, now, retention_hours)
    except (Incomplete, Due, StoreRefused, ValueError) as exc:
        raise RemoveRefused(f"archive {archive_id} may not authorise a removal: {exc}") from exc


def record_claim(
    store: ArchiveStore,
    expected: Fingerprint,
    *,
    parent_fd: int,
    name: str,
    archive_id: str,
    original_path: str,
    checkout: str,
    at: datetime,
) -> None:
    """Record, durably, that a sweep is about to claim the entry ``expected`` describes.

    Call it under the store lock BEFORE the rename: a crash between the two
    leaves a record and no claim, never a claim with no record. ``name`` under
    ``parent_fd`` is where the entry is now; its birth time is recorded beside
    its device and inode. Raises ``ValueError`` (nothing recorded, so nothing
    may be claimed) when the filesystem reports no birth time or the name is no
    longer the fingerprinted inode: without a birth, a leftover claim could not
    be told from a new folder that reused the inode number.
    """
    stamp = birth_stamp(parent_fd, name)
    if stamp is None:
        raise ValueError(
            f"{name!r}: the filesystem reports no birth time, so a leftover claim could "
            "not be told from a new folder on a reused inode; not claimed"
        )
    if (stamp.ino, stamp.dev) != (expected.root_ino, expected.root_dev):
        raise ValueError(f"{name!r} is no longer the fingerprinted inode; not claimed")
    store.append_event(
        ClaimEvent(
            archive_id=archive_id,
            original_path=original_path,
            checkout=checkout,
            root_dev=str(expected.root_dev),
            root_ino=str(expected.root_ino),
            at=at.isoformat(),
            root_birth_ns=str(stamp.birth_ns),
        )
    )


def claim_event_covers(
    event: ClaimEvent, *, checkout: str, name: str, info: os.stat_result, birth: BirthStamp | None
) -> bool:
    """True only when ``event`` describes this very inode: device, inode AND birth.

    ``info`` is the leftover claim's ``lstat`` and ``birth`` its birth stamp. A
    missing birth on either side covers nothing (fail closed): device and inode
    alone are reused by a new folder on ext4.
    """
    if birth is None or not event.root_birth_ns:
        return False
    if (birth.ino, birth.dev) != (info.st_ino, info.st_dev):
        return False
    return (
        event.checkout == checkout
        and PurePosixPath(event.original_path).name == name
        and (event.root_dev, event.root_ino) == (str(info.st_dev), str(info.st_ino))
        and event.root_birth_ns == str(birth.birth_ns)
    )


def _latest_claim(
    store: ArchiveStore,
    checkout: str,
    name: str,
    info: os.stat_result,
    birth: BirthStamp | None,
) -> ClaimEvent | None:
    """The last-appended claim event covering this very inode; None: no such event.

    "Last" is the events file's append order, never the events' ``at``: the
    wall clock can step back, the order of appends under the store lock cannot.
    """
    try:
        events = store.read_events().events
    except StoreRefused as exc:
        raise RemoveRefused(str(exc)) from exc
    covering = [
        event
        for event in events
        if isinstance(event, ClaimEvent)
        and claim_event_covers(event, checkout=checkout, name=name, info=info, birth=birth)
    ]
    return covering[-1] if covering else None


def _names_entry(record: ArchiveRecord, name: str) -> bool:
    return PurePosixPath(record.original_path).name == name


def _walk(parent_fd: int, claimed_name: str, max_inodes: int, max_depth: int) -> TreeListing:
    try:
        return walk_tree(parent_fd, claimed_name, max_inodes=max_inodes, max_depth=max_depth)
    except WalkRefused as exc:
        raise RemoveRefused(f"the claimed tree cannot be walked: {exc}") from exc


def _prove(
    parent_fd: int,
    claimed_name: str,
    store: ArchiveStore,
    record: ArchiveRecord,
    *,
    tar: TarTool,
    max_inodes: int,
    max_depth: int,
    timeout: float,
    partial: bool,
    expected: Fingerprint | None = None,
) -> _Proof:
    """Walk, verify against the recorded SHA-256, walk again; refuse on any difference."""
    before = _walk(parent_fd, claimed_name, max_inodes, max_depth)
    if expected is not None and fingerprint_of(before) != expected:
        raise RemoveRefused("fingerprint changed since the claim")
    try:
        refuse_unrestorable(before, claimed_name)
        members = members_of(before, claimed_name)
    except PackRefused as exc:
        raise RemoveRefused(str(exc)) from exc
    skipped, recorded = set(members.skipped), set(record.skipped)
    if partial and not skipped <= recorded:
        raise RemoveRefused("special files the record does not list")
    if not partial and (skipped != recorded or members.counts != dict(record.counts)):
        raise RemoveRefused("the tree's special files or counts differ from the record")
    check = verify_remaining if partial else verify
    # The layout comes from the record's proof, never from the archive's content.
    adopted_root = (
        PurePosixPath(record.original_path).name if ADOPT_PROOF in record.proof_ids else None
    )
    try:
        verified = check(
            parent_fd,
            claimed_name,
            store,
            record.archive_id,
            tar=tar,
            max_inodes=max_inodes,
            max_depth=max_depth,
            expected_sha256=record.sha256,
            timeout=timeout,
            adopted_root=adopted_root,
        )
    except TarDidNotRun as exc:
        raise ProofUnavailable(f"archive {record.archive_id} was not checked: {exc}") from exc
    except VerifyFailed as exc:
        raise RemoveRefused(f"archive {record.archive_id} does not verify: {exc}") from exc
    after = _walk(parent_fd, claimed_name, max_inodes, max_depth)
    if after.nodes != before.nodes or verified.members != members.names:
        raise RemoveRefused("the claimed tree changed while it was verified")
    return _Proof(claimed_name=claimed_name, record=record, listing=after, partial=partial)


def _lstat_at(dir_fd: int, name: str) -> os.stat_result:
    try:
        return os.lstat(name, dir_fd=dir_fd)
    except OSError as exc:
        raise RemoveRefused(f"cannot lstat {name!r}: {exc}") from exc


def _mount_id(fd: int) -> int:
    """The mount id of an open descriptor, from procfs; refuse when it cannot be read."""
    path = "/".join((*_FDINFO_PARTS, str(fd)))
    try:
        with open(path, encoding="ascii") as handle:
            for line in handle:
                if line.startswith(_MNT_ID):
                    return int(line[len(_MNT_ID) :].strip())
    except (OSError, ValueError) as exc:
        raise RemoveRefused(f"cannot read the mount id: {exc}") from exc
    raise RemoveRefused("no mount id for a descriptor")


def _require_listed(info: os.stat_result, node: Node) -> None:
    """The name must still be the listed inode; directories are matched by identity only."""
    same = (kind_of(info.st_mode), info.st_ino, info.st_dev) == (node.kind, node.ino, node.dev)
    if same and node.kind != "dir":
        same = (info.st_nlink, info.st_ctime_ns, info.st_mtime_ns, info.st_size) == (
            node.nlink,
            node.ctime_ns,
            node.mtime_ns,
            node.size,
        )
    if not same:
        raise RemoveRefused(f"{node.rel or 'the entry'!r} changed since it was verified")


def _open_listed_dir(dir_fd: int, name: str, info: os.stat_result, mount: int) -> int:
    try:
        fd = open_child_dir(dir_fd, name, info)
    except WalkRefused as exc:
        raise RemoveRefused(str(exc)) from exc
    try:
        if _mount_id(fd) != mount:
            raise RemoveRefused(f"{name!r} is on another mount")
    except RemoveRefused:
        os.close(fd)
        raise
    return fd


def _delete(dir_fd: int, name: str, *, directory: bool, inside: bool) -> None:
    """Remove one listed name. ``EACCES`` inside the tree adds u+wx through ``dir_fd`` once."""
    for attempt in (1, 2):
        try:
            if directory:
                os.rmdir(name, dir_fd=dir_fd)
            else:
                os.unlink(name, dir_fd=dir_fd)
            return
        except PermissionError as exc:
            if attempt == 2 or not inside or exc.errno != errno.EACCES:
                raise RemoveRefused(f"cannot remove {name!r}: {exc}") from exc
            try:
                mode = stat.S_IMODE(os.fstat(dir_fd).st_mode)
                os.fchmod(dir_fd, mode | stat.S_IWUSR | stat.S_IXUSR)
            except OSError as chmod_exc:
                raise RemoveRefused(f"cannot make a directory writable: {chmod_exc}") from exc
        except OSError as exc:
            raise RemoveRefused(f"cannot remove {name!r}: {exc}") from exc


def _children(listing: TreeListing) -> dict[str, list[Node]]:
    found: dict[str, list[Node]] = {}
    for node in listing.nodes[1:]:
        parent = node.rel.rpartition("/")[0]
        found.setdefault(parent, []).append(node)
    return found


def _fsync(dir_fd: int) -> None:
    try:
        os.fsync(dir_fd)
    except OSError as exc:
        raise RemoveRefused(f"cannot fsync the parent directory: {exc}") from exc


def _readlink(dir_fd: int, name: str) -> str:
    try:
        return os.readlink(name, dir_fd=dir_fd)
    except OSError as exc:
        raise RemoveRefused(f"cannot read the link {name!r}: {exc}") from exc


def _remove(parent_fd: int, proof: _Proof, *, max_depth: int) -> Removed:
    name = proof.claimed_name
    root = proof.listing.root
    info = _lstat_at(parent_fd, name)
    if root.kind != "dir":
        _require_listed(info, root)
        target = _readlink(parent_fd, name) if root.kind == "symlink" else None
        _delete(parent_fd, name, directory=False, inside=False)
        _fsync(parent_fd)
        return Removed(name, proof.record.archive_id, 1, target, proof.partial)
    _require_listed(info, root)
    mount = _mount_id(parent_fd)
    children = _children(proof.listing)
    removed = 0
    stack: list[tuple[int, str, Iterator[Node]]] = []
    try:
        root_fd = _open_listed_dir(parent_fd, name, info, mount)
        stack.append((root_fd, "", iter(children.get("", []))))
        while stack:
            fd, rel, pending = stack[-1]
            node = next(pending, None)
            if node is None:
                stack.pop()
                os.close(fd)
                if stack:
                    leaf = rel.rpartition("/")[2]
                    _delete(stack[-1][0], leaf, directory=True, inside=True)
                else:
                    _delete(parent_fd, name, directory=True, inside=False)
                removed += 1
                continue
            leaf = node.rel.rpartition("/")[2]
            info = _lstat_at(fd, leaf)
            _require_listed(info, node)
            if node.kind != "dir":
                _delete(fd, leaf, directory=False, inside=True)
                removed += 1
                continue
            if len(stack) >= max_depth:
                raise RemoveRefused(f"{node.rel!r} is deeper than {max_depth} (depth cap)")
            child_fd = _open_listed_dir(fd, leaf, info, mount)
            stack.append((child_fd, node.rel, iter(children.get(node.rel, []))))
    finally:
        for fd, _rel, _pending in stack:
            os.close(fd)
    _fsync(parent_fd)
    return Removed(name, proof.record.archive_id, removed, None, proof.partial)


def remove_claimed(
    parent_fd: int,
    claimed_name: str,
    store: ArchiveStore,
    record: ArchiveRecord,
    *,
    tar: TarTool,
    max_inodes: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    clock: Callable[[], datetime],
    retention_hours: Mapping[str, float],
    expected: Fingerprint | None = None,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Removed:
    """Remove a claimed entry whose archive is recorded and verifies; raise :class:`RemoveRefused`.

    ``clock`` and ``retention_hours`` are required: an archive that is
    expired, due for expiry or not complete never authorises a removal.
    """
    name = entry_name_of(claimed_name)
    records = _index(store)
    if record not in records:
        raise RemoveRefused(f"archive {record.archive_id} is not in the index as given")
    if not _names_entry(record, name):
        raise RemoveRefused(f"archive {record.archive_id} names another entry")
    _removable(store, record.archive_id, clock, retention_hours)
    # A batch archive (Task 3.5) is shared by one record per loose file: each
    # file is proved by its own member (the restricted compare), never by the
    # whole archive's member set.
    shared = sum(1 for r in records if r.archive_id == record.archive_id) > 1
    proof = _prove(
        parent_fd,
        claimed_name,
        store,
        record,
        tar=tar,
        max_inodes=max_inodes,
        max_depth=max_depth,
        timeout=timeout,
        partial=shared,
        expected=expected,
    )
    if shared:
        root = proof.listing.root
        if root.kind == "dir" or dict(record.counts) != {root.kind: 1}:
            raise RemoveRefused(f"archive {record.archive_id} is a batch; this is not its file")
    return _remove(parent_fd, proof, max_depth=max_depth)


def resume_claimed(
    parent_fd: int,
    claimed_name: str,
    store: ArchiveStore,
    *,
    checkout: str,
    tar: TarTool,
    max_inodes: int,
    clock: Callable[[], datetime],
    retention_hours: Mapping[str, float],
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Resumed:
    """Finish or undo a leftover claim.

    Only the archive the latest covering claim event names is tried (a claim
    records the id its pack will use, so a record of an earlier claim of the
    same tree, or of an earlier tree of that name, never proves it), whole and
    then as a partly removed tree; when it verifies it authorises the removal. An archive that is expired, due or not complete authorises
    nothing: against an intact tree it is skipped, and against a partly removed
    tree it leaves the claim stuck for a human to restore from it (never
    removed, never renamed back). When none verifies, the tree is renamed back; when its name is taken,
    it stays claimed and is reported stuck. A record that could not be checked at
    all (tar did not run) also leaves it stuck: a partly removed tree is never
    renamed back for want of a check. Nothing is removed without a record.

    A claim name no claim event of this checkout covers (same entry name, same
    device, inode and birth time) was not made by a sweep: it is reported ``foreign`` and
    neither removed nor renamed (D-PATH F1).
    """
    name = entry_name_of(claimed_name)
    records = _index(store)
    try:
        info = os.lstat(claimed_name, dir_fd=parent_fd)
    except FileNotFoundError:
        return Resumed(name, "absent", "no leftover claim")
    except OSError as exc:
        raise RemoveRefused(f"cannot lstat {claimed_name!r}: {exc}") from exc
    try:
        birth = birth_stamp(parent_fd, claimed_name)
    except OSError as exc:
        raise RemoveRefused(f"cannot read the birth of {claimed_name!r}: {exc}") from exc
    latest = _latest_claim(store, checkout, name, info, birth)
    if latest is None:
        return Resumed(
            name, "foreign", f"no claim record covers {claimed_name!r}: not a sweep's; left alone"
        )
    # Only the archive the latest claim names may prove the tree (Task 3.9
    # finding 2; PR 251 review F1/F2). Any other record naming the entry is of
    # an earlier claim of it, whose tree and retention are not this one's. The
    # binding is by id, so no clock reading takes part in it.
    candidates = [
        r
        for r in reversed(records)
        if r.checkout == checkout and _names_entry(r, name) and r.archive_id == latest.archive_id
    ]
    unchecked = False
    for record in candidates:
        try:
            _removable(store, record.archive_id, clock, retention_hours)
            blocked: str | None = None
        except RemoveRefused as exc:
            blocked = str(exc)
            log_and_continue(
                _LOG,
                exc,
                reason=f"archive {record.archive_id} cannot authorise removal; reported as stuck",
                level=logging.DEBUG,
            )
        for partial in (False, True):
            try:
                proof = _prove(
                    parent_fd,
                    claimed_name,
                    store,
                    record,
                    tar=tar,
                    max_inodes=max_inodes,
                    max_depth=max_depth,
                    timeout=timeout,
                    partial=partial,
                )
            except ProofUnavailable as exc:
                unchecked = True
                log_and_continue(
                    _LOG, exc, reason="tar did not run; the entry is reported stuck, not removed"
                )
                continue
            except RemoveRefused as exc:
                log_and_continue(
                    _LOG,
                    exc,
                    reason=f"archive {record.archive_id} does not prove the entry; try the next",
                    level=logging.DEBUG,
                )
                continue
            if blocked is not None:
                if not partial:
                    # The tree is intact: this archive cannot authorise its
                    # removal, and renaming it back loses nothing.
                    break
                return Resumed(
                    name, "stuck", f"partly removed; {blocked}; a human restores from it"
                )
            try:
                removed = _remove(parent_fd, proof, max_depth=max_depth)
            except RemoveRefused as exc:
                return Resumed(name, "stuck", f"removal stopped: {exc}")
            return Resumed(name, "removed", f"archive {record.archive_id} verified", removed)
    if unchecked:
        return Resumed(name, "stuck", "a recorded archive could not be checked (tar did not run)")
    # An adopted archive of this entry that the claim does not name means the
    # claim cannot be matched to the archive that holds the tree: the tree is
    # never renamed back (a human reconciles them). Other excluded records of
    # the entry (earlier claims, earlier trees) stay harmless.
    if any(
        r.checkout == checkout
        and _names_entry(r, name)
        and r.archive_id != latest.archive_id
        and ADOPT_PROOF in r.proof_ids
        for r in records
    ):
        return Resumed(
            name,
            "stuck",
            f"the claim names archive {latest.archive_id}, not the adopted archive of this "
            "entry; left claimed for a human",
        )
    reason = (
        "the claim's archive does not verify"
        if candidates
        else f"no record of the claim's archive {latest.archive_id} (not packed)"
    )
    try:
        rename_noreplace(parent_fd, claimed_name, name)
    except (OSError, ClaimRefused) as exc:
        return Resumed(name, "stuck", f"{reason}; cannot rename back: {exc}")
    _fsync(parent_fd)
    return Resumed(name, "renamed-back", reason)
