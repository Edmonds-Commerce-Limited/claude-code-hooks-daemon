"""Proof P6: adopt a tarball that sits beside its original (Plan 00627 Task 3.7).

A by-hand ``tar czf e.tgz e`` beside ``e`` is already an archive of ``e``. This
module moves such a tarball into the store as a recorded archive, after proving
it holds exactly the original, so the original can be treated as packed. The
original is never touched here; its removal stays the sweep's (Task 3.8).

Every check runs before anything is written, and each refusal raises
:class:`AdoptRefused` with nothing changed:

* the store lock; plain names for the entry and the tarball (so the tarball is
  in the entry's own directory), the record's basename equal to the entry's;
* the tarball is a regular file (not a link, not special), with one link, on
  the store's device, and opened ``O_NOFOLLOW`` as the inode ``lstat`` saw;
* its compression (plain, gzip or xz) is chosen from its first bytes and passed
  to tar and :mod:`tarfile` explicitly; an unknown format or a missing
  decompressor refuses;
* every header is a directory, regular file or symbolic link named ``<entry>``
  or ``<entry>/...`` with no empty, ``.`` or ``..`` component, none repeated
  and none beneath a link, and ``<entry>`` is a directory member;
* the original is a directory walked without following links, holding no
  special file and no multiply-linked file;
* the member set equals the walk's (``--compare`` cannot see an extra file);
* ``tar --compare --strip-components=1`` inside the entry, naming every member
  but the root (which strips to an empty name tar cannot stat) with
  ``--no-recursion --no-wildcards --no-unquote``, exits 0 silently; an entry
  holding only its root is proved by the member set alone;
* the SHA-256 and size read before the compare are read again after it.

Then, in this order: the ``adopt`` event is appended (so a crash leaves a named
archive, which :meth:`ArchiveStore.discard_unrecorded` refuses), the tarball is
moved into the store by a no-replace rename, the moved file is checked to be
the same inode, singly linked, with the same digest, and the record is
appended. A moved file that fails that check was swapped in by someone else: it
is moved back under its old name (:class:`AdoptRefused`), or, if that fails, it
stays in the store unrecorded and named by the event (:class:`AdoptStuck`).

A crash after the event but before the record is found by
:func:`unfinished_adoptions`; :func:`finish_adoption` proves the archive
already in the store against the original the same way and appends the
record, or refuses (:class:`AdoptRefused`) leaving the archive in place.
"""

from __future__ import annotations

import errno
import logging
import os
import posixpath
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from claude_code_hooks_daemon.core.scratch_archive import (
    AdoptEvent,
    ArchiveRecord,
    ArchiveStore,
    ExpiredEvent,
    StoreRefused,
    archive_file_name,
    fsync_dir,
    new_archive_id,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    CLAIM_PREFIX,
    DEFAULT_MAX_DEPTH,
    ClaimRefused,
    WalkRefused,
    check_entry_name,
    check_name,
    open_child_dir,
    rename_noreplace_between,
    walk_tree,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    DEFAULT_TAR_TIMEOUT_SECONDS,
    Compression,
    PackRefused,
    TarDidNotRun,
    TarTool,
    VerifyFailed,
    batched_compare,
    compression_flags,
    compression_of,
    digest_fd,
    members_of,
    refuse_foreign_owner,
    require_decompressor,
)
from claude_code_hooks_daemon.core.scratch_archive_restore import (
    Header,
    RestoreRefused,
    read_headers,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

_LOG = logging.getLogger(__name__)

#: The proof id an adopted archive's record always carries.
PROOF_ID = "P6"

_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_STRIP_ROOT = "--strip-components=1"


class AdoptRefused(Exception):
    """Nothing was adopted; the tarball is where it was (an ``adopt`` event may name it)."""


class AdoptStuck(Exception):
    """A moved file failed its check and could not be moved back; it is in the store,
    unrecorded, named by its ``adopt`` event, and never discarded."""


@dataclass(frozen=True)
class Adopted:
    """A tarball now recorded in the store as ``archive_id``."""

    archive_id: str
    original_path: str
    tarball: str
    compression: Compression
    size: int
    sha256: str
    counts: Mapping[str, int]


@dataclass(frozen=True)
class _Tarball:
    fd: int
    ino: int
    dev: int


def adopt(
    store: ArchiveStore,
    parent_fd: int,
    entry_name: str,
    tarball_name: str,
    *,
    original_path: str,
    checkout: str,
    verdict: str,
    proof_ids: tuple[str, ...],
    expires_at: str | None,
    restore_command: str,
    now: datetime,
    tar: TarTool,
    max_inodes: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Adopted:
    """Adopt ``tarball_name`` (beside entry ``entry_name`` in ``parent_fd``) into the store.

    Raises :class:`AdoptRefused` (nothing moved), :class:`AdoptStuck`, or
    :class:`StoreRefused` without the lock.
    """
    store.require_lock("adopt")
    _check_names(entry_name, tarball_name, original_path, now)
    tarball = _open_tarball(store, parent_fd, tarball_name)
    try:
        compression, size, sha, counts = _prove(
            parent_fd,
            entry_name,
            tarball.fd,
            tar=tar,
            max_inodes=max_inodes,
            max_depth=max_depth,
            timeout=timeout,
        )
    finally:
        os.close(tarball.fd)
    archive_id = new_archive_id()
    tarball_path = posixpath.join(posixpath.dirname(original_path), tarball_name)
    at = now.isoformat()
    store.append_event(
        AdoptEvent(archive_id=archive_id, original_path=original_path, tarball=tarball_path, at=at)
    )
    _move_in(store, parent_fd, tarball_name, archive_id)
    _check_moved(store, parent_fd, tarball_name, archive_id, tarball, size, sha)
    store.append(
        ArchiveRecord(
            archive_id=archive_id,
            original_path=original_path,
            checkout=checkout,
            verdict=verdict,
            proof_ids=tuple(dict.fromkeys((*proof_ids, PROOF_ID))),
            packed_at=at,
            expires_at=expires_at,
            counts=dict(counts),
            archive_size=size,
            sha256=sha,
            skipped=(),
            restore_command=restore_command,
        )
    )
    return Adopted(
        archive_id=archive_id,
        original_path=original_path,
        tarball=tarball_path,
        compression=compression,
        size=size,
        sha256=sha,
        counts=dict(counts),
    )


def unfinished_adoptions(store: ArchiveStore) -> tuple[AdoptEvent, ...]:
    """``adopt`` events no record and no ``expired`` event name; needs the store lock.

    Each is a crash between the event and the record: the archive is in the store
    unrecorded (:func:`finish_adoption` finishes it), or the tarball never moved.
    """
    store.require_lock("listing unfinished adoptions")
    events = store.read_events().events
    recorded = {r.archive_id for r in store.read_index().records}
    expired = {e.archive_id for e in events if isinstance(e, ExpiredEvent)}
    found: dict[str, AdoptEvent] = {}
    for event in events:
        if isinstance(event, AdoptEvent) and event.archive_id not in recorded | expired:
            found.setdefault(event.archive_id, event)
    return tuple(found.values())


def finish_adoption(
    store: ArchiveStore,
    parent_fd: int,
    entry_name: str,
    archive_id: str,
    *,
    checkout: str,
    verdict: str,
    proof_ids: tuple[str, ...],
    expires_at: str | None,
    restore_command: str,
    tar: TarTool,
    max_inodes: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Adopted:
    """Record an adoption a crash left with an ``adopt`` event but no record.

    The archive already in the store is proved against the original
    ``entry_name`` in ``parent_fd`` exactly as :func:`adopt` proves a tarball,
    then the record is appended with ``packed_at`` the event's time. Nothing is
    moved. Any failure raises :class:`AdoptRefused` naming why, and the archive
    stays where it is, named by its event, which ``discard_unrecorded`` refuses.
    """
    store.require_lock("finishing an adoption")
    event = _unfinished_event(store, archive_id)
    try:
        check_entry_name(entry_name)
    except ValueError as exc:
        raise AdoptRefused(f"not a plain entry name: {exc}") from exc
    if posixpath.basename(event.original_path) != entry_name:
        raise AdoptRefused("the adopt event's path does not name the entry")
    fd = _open_stored(store, archive_id)
    try:
        compression, size, sha, counts = _prove(
            parent_fd,
            entry_name,
            fd,
            tar=tar,
            max_inodes=max_inodes,
            max_depth=max_depth,
            timeout=timeout,
        )
        if os.fstat(fd).st_nlink != 1:
            raise AdoptRefused("the stored archive gained a hard link while it was proved")
    finally:
        os.close(fd)
    store.append(
        ArchiveRecord(
            archive_id=archive_id,
            original_path=event.original_path,
            checkout=checkout,
            verdict=verdict,
            proof_ids=tuple(dict.fromkeys((*proof_ids, PROOF_ID))),
            packed_at=event.at,
            expires_at=expires_at,
            counts=dict(counts),
            archive_size=size,
            sha256=sha,
            skipped=(),
            restore_command=restore_command,
        )
    )
    return Adopted(
        archive_id=archive_id,
        original_path=event.original_path,
        tarball=event.tarball,
        compression=compression,
        size=size,
        sha256=sha,
        counts=dict(counts),
    )


def _unfinished_event(store: ArchiveStore, archive_id: str) -> AdoptEvent:
    """The ``adopt`` event for ``archive_id``, refusing a torn, recorded or expired id."""
    events = store.read_events()
    if events.torn_tail:
        raise AdoptRefused("the events file has a torn final line; a human must look first")
    index = store.read_index()
    if index.torn_tail:
        raise AdoptRefused("the index has a torn final line; a human must look first")
    if any(r.archive_id == archive_id for r in index.records):
        raise AdoptRefused(f"archive {archive_id} is already recorded")
    if any(isinstance(e, ExpiredEvent) and e.archive_id == archive_id for e in events.events):
        raise AdoptRefused(f"archive {archive_id} has an expired event")
    for event in events.events:
        if isinstance(event, AdoptEvent) and event.archive_id == archive_id:
            return event
    raise AdoptRefused(f"no adopt event names archive {archive_id}")


def _open_stored(store: ArchiveStore, archive_id: str) -> int:
    """Open the stored archive: a regular file, not a link, singly linked."""
    try:
        os.lstat(archive_file_name(archive_id), dir_fd=store.dir_fd)
    except FileNotFoundError as exc:
        raise AdoptRefused(f"archive {archive_id} is not in the store; the move never ran") from exc
    try:
        fd = store.open_archive(archive_id)
    except StoreRefused as exc:
        raise AdoptRefused(str(exc)) from exc
    links = os.fstat(fd).st_nlink
    if links != 1:
        os.close(fd)
        raise AdoptRefused(f"the stored archive has {links} hard links")
    return fd


def _check_names(entry_name: str, tarball_name: str, original_path: str, now: datetime) -> None:
    try:
        check_entry_name(entry_name)
        check_name(tarball_name)
    except ValueError as exc:
        raise AdoptRefused(f"not a plain name beside the entry: {exc}") from exc
    if tarball_name.startswith(CLAIM_PREFIX) or tarball_name == entry_name:
        raise AdoptRefused(f"tarball name {tarball_name!r} cannot be adopted")
    if posixpath.basename(original_path) != entry_name:
        raise AdoptRefused("the record's path does not name the entry")
    if now.tzinfo is None or now.utcoffset() is None:
        raise AdoptRefused("the adoption time has no zone")


def _open_tarball(store: ArchiveStore, parent_fd: int, name: str) -> _Tarball:
    """Open the tarball as the plain, singly-linked, same-device file ``lstat`` saw."""
    try:
        info = os.lstat(name, dir_fd=parent_fd)
    except OSError as exc:
        raise AdoptRefused(f"the tarball cannot be read: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise AdoptRefused("the tarball is a link; only the link itself is beside the entry")
    if not stat.S_ISREG(info.st_mode):
        raise AdoptRefused("the tarball is not a regular file")
    if info.st_nlink != 1:
        raise AdoptRefused(f"the tarball has {info.st_nlink} hard links")
    if info.st_dev != os.fstat(store.dir_fd).st_dev:
        raise AdoptRefused("the tarball is on another device than the store")
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise AdoptRefused(f"the tarball cannot be opened: {exc}") from exc
    opened = os.fstat(fd)
    if (opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev) or opened.st_nlink != 1:
        os.close(fd)
        raise AdoptRefused("the tarball changed while it was opened")
    return _Tarball(fd=fd, ino=info.st_ino, dev=info.st_dev)


def _prove(
    parent_fd: int,
    entry_name: str,
    fd: int,
    *,
    tar: TarTool,
    max_inodes: int,
    max_depth: int,
    timeout: float,
) -> tuple[Compression, int, str, Mapping[str, int]]:
    """Prove the tarball holds exactly the entry; return its compression, size, hash, counts."""
    size, sha = digest_fd(fd)
    try:
        compression = compression_of(fd)
        require_decompressor(compression)
    except PackRefused as exc:
        raise AdoptRefused(str(exc)) from exc
    headers = _headers(fd, compression, entry_name)
    try:
        listing = walk_tree(parent_fd, entry_name, max_inodes=max_inodes, max_depth=max_depth)
        if listing.root.kind != "dir":
            raise AdoptRefused("the entry is not a directory")
        refuse_foreign_owner(listing, entry_name)
        members = members_of(listing, entry_name)
    except (WalkRefused, PackRefused) as exc:
        raise AdoptRefused(f"the entry cannot be walked: {exc}") from exc
    if members.skipped:
        raise AdoptRefused(f"the entry holds {len(members.skipped)} special files")
    walked = {entry_name} | {
        f"{entry_name}/{n[2:].rstrip('/')}" for n in members.names if n != "./"
    }
    if walked != {h.name for h in headers}:
        raise AdoptRefused("the tarball's member set and the entry differ")
    operands = sorted(h.name for h in headers if h.name != entry_name)
    if operands:
        _compare(parent_fd, entry_name, listing.root.ino, fd, operands, compression, tar, timeout)
    if digest_fd(fd) != (size, sha):
        raise AdoptRefused("the tarball changed while it was verified")
    return compression, size, sha, members.counts


def _headers(fd: int, compression: Compression, entry_name: str) -> tuple[Header, ...]:
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        with os.fdopen(os.dup(fd), "rb") as handle:
            headers = read_headers(handle, compression)
    except RestoreRefused as exc:
        raise AdoptRefused(str(exc)) from exc
    for header in headers:
        if header.name != entry_name and not header.name.startswith(entry_name + "/"):
            raise AdoptRefused(f"member {header.name!r} is not under {entry_name!r}")
    if not any(h.name == entry_name and h.kind == "dir" for h in headers):
        raise AdoptRefused(f"the tarball has no directory member {entry_name!r}")
    return headers


def _compare(
    parent_fd: int,
    entry_name: str,
    root_ino: int,
    fd: int,
    operands: list[str],
    compression: Compression,
    tar: TarTool,
    timeout: float,
) -> None:
    try:
        expected = os.lstat(entry_name, dir_fd=parent_fd)
        if expected.st_ino != root_ino:
            raise AdoptRefused("the entry changed while it was walked")
        entry_fd = open_child_dir(parent_fd, entry_name, expected)
    except (OSError, WalkRefused) as exc:
        raise AdoptRefused(f"the entry cannot be opened: {exc}") from exc
    try:
        batched_compare(
            entry_fd,
            fd,
            operands,
            tar=tar,
            timeout=timeout,
            flags=(*compression_flags(compression), _STRIP_ROOT),
        )
    except (VerifyFailed, TarDidNotRun) as exc:
        raise AdoptRefused(f"the tarball and the entry differ: {exc}") from exc
    finally:
        os.close(entry_fd)


def _move_in(store: ArchiveStore, parent_fd: int, tarball_name: str, archive_id: str) -> None:
    """The no-replace move of the tarball into the store; the ``adopt`` event is already written."""
    try:
        rename_noreplace_between(
            parent_fd, tarball_name, store.dir_fd, archive_file_name(archive_id)
        )
    except (OSError, ClaimRefused) as exc:
        raise AdoptRefused(f"the move into the store failed: {exc}") from exc
    fsync_dir(store.dir_fd)
    fsync_dir(parent_fd)


def _check_moved(
    store: ArchiveStore,
    parent_fd: int,
    tarball_name: str,
    archive_id: str,
    tarball: _Tarball,
    size: int,
    sha: str,
) -> None:
    """The moved file must be the verified inode, singly linked, with the verified digest."""
    fd: int | None = None
    unopenable = ""
    try:
        fd = store.open_archive(archive_id)
    except StoreRefused as exc:
        log_and_continue(
            _LOG, exc, reason="the moved archive cannot be opened; it is moved back and refused"
        )
        unopenable = str(exc)
    if fd is None:
        _move_back(store, parent_fd, tarball_name, archive_id, unopenable)
    try:
        info = os.fstat(fd)
        same = (info.st_ino, info.st_dev, info.st_nlink) == (tarball.ino, tarball.dev, 1)
        if same and digest_fd(fd) == (size, sha):
            os.fsync(fd)
            return
    finally:
        os.close(fd)
    _move_back(store, parent_fd, tarball_name, archive_id, "it is not the verified tarball")


def _move_back(
    store: ArchiveStore, parent_fd: int, tarball_name: str, archive_id: str, why: str
) -> NoReturn:
    """Return a file that failed its check to its old name; raise in every case."""
    try:
        rename_noreplace_between(
            store.dir_fd, archive_file_name(archive_id), parent_fd, tarball_name
        )
    except (OSError, ClaimRefused) as exc:
        taken = isinstance(exc, OSError) and exc.errno == errno.EEXIST
        reason = "its old name is taken" if taken else str(exc)
        raise AdoptStuck(
            f"the moved file failed its check ({why}) and stays in the store as "
            f"{archive_id}, named by its adopt event: {reason}"
        ) from exc
    fsync_dir(store.dir_fd)
    fsync_dir(parent_fd)
    raise AdoptRefused(f"the moved file failed its check ({why}); it was moved back")
