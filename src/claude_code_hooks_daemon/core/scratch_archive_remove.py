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
tree), and renamed back otherwise.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

from claude_code_hooks_daemon.core.scratch_archive import (
    ArchiveRecord,
    ArchiveStore,
    StoreRefused,
)
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
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    DEFAULT_TAR_TIMEOUT_SECONDS,
    PackRefused,
    TarDidNotRun,
    TarTool,
    VerifyFailed,
    members_of,
    verify,
    verify_remaining,
)

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
    """What became of a leftover claim: removed, renamed-back, stuck or absent."""

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
        members = members_of(before, claimed_name)
    except PackRefused as exc:
        raise RemoveRefused(str(exc)) from exc
    skipped, recorded = set(members.skipped), set(record.skipped)
    if partial and not skipped <= recorded:
        raise RemoveRefused("special files the record does not list")
    if not partial and (skipped != recorded or members.counts != dict(record.counts)):
        raise RemoveRefused("the tree's special files or counts differ from the record")
    check = verify_remaining if partial else verify
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
    expected: Fingerprint | None = None,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Removed:
    """Remove a claimed entry whose archive is recorded and verifies; raise :class:`RemoveRefused`."""
    name = entry_name_of(claimed_name)
    records = _index(store)
    if record not in records:
        raise RemoveRefused(f"archive {record.archive_id} is not in the index as given")
    if not _names_entry(record, name):
        raise RemoveRefused(f"archive {record.archive_id} names another entry")
    proof = _prove(
        parent_fd,
        claimed_name,
        store,
        record,
        tar=tar,
        max_inodes=max_inodes,
        max_depth=max_depth,
        timeout=timeout,
        partial=False,
        expected=expected,
    )
    return _remove(parent_fd, proof, max_depth=max_depth)


def resume_claimed(
    parent_fd: int,
    claimed_name: str,
    store: ArchiveStore,
    *,
    checkout: str,
    tar: TarTool,
    max_inodes: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Resumed:
    """Finish or undo a leftover claim.

    Each record of this checkout naming the entry is tried, newest first, whole
    and then as a partly removed tree; the first that verifies authorises the
    removal. When none does, the tree is renamed back; when its name is taken,
    it stays claimed and is reported stuck. A record that could not be checked at
    all (tar did not run) also leaves it stuck: a partly removed tree is never
    renamed back for want of a check. Nothing is removed without a record.
    """
    name = entry_name_of(claimed_name)
    records = _index(store)
    try:
        os.lstat(claimed_name, dir_fd=parent_fd)
    except FileNotFoundError:
        return Resumed(name, "absent", "no leftover claim")
    except OSError as exc:
        raise RemoveRefused(f"cannot lstat {claimed_name!r}: {exc}") from exc
    candidates = [r for r in reversed(records) if r.checkout == checkout and _names_entry(r, name)]
    unchecked = False
    for record in candidates:
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
            except ProofUnavailable:
                unchecked = True
                continue
            except RemoveRefused:
                continue
            try:
                removed = _remove(parent_fd, proof, max_depth=max_depth)
            except RemoveRefused as exc:
                return Resumed(name, "stuck", f"removal stopped: {exc}")
            return Resumed(name, "removed", f"archive {record.archive_id} verified", removed)
    if unchecked:
        return Resumed(name, "stuck", "a recorded archive could not be checked (tar did not run)")
    reason = "no recorded archive verifies" if candidates else "no record names the entry"
    try:
        rename_noreplace(parent_fd, claimed_name, name)
    except (OSError, ClaimRefused) as exc:
        return Resumed(name, "stuck", f"{reason}; cannot rename back: {exc}")
    _fsync(parent_fd)
    return Resumed(name, "renamed-back", reason)
