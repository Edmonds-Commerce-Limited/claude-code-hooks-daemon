"""Restore an archived entry under its original name (Plan 00627 Task 3.6).

Restore never overwrites anything. Every check runs BEFORE any staging exists:
the store lock, a complete record (:func:`complete_records`), a plain
destination name from the record, the destination absent (``lstat``, so a
dangling link counts as present), the store and destination on one device, the
archive's size and SHA-256 read through the descriptor later fed to tar, and
every header: only directories, regular files and symbolic links, each named
``./...`` with no empty, ``.`` or ``..`` component, none repeated and none
beneath a symbolic link member. The layout is derived from the headers and
must agree with the record:

* a ``.`` root member: a directory entry, its member counts by kind equal to
  the record's, its other kinds equal to the record's skipped files;
* only ``./.sweeping-<name>`` members: a loose file or a batch, of which the
  member for the record's name is restored, its kind equal to the record's;
* only ``<name>`` (one directory) and ``<name>/...`` members, ``<name>`` the
  record's: a P6 adopted archive (Task 3.7), its counts equal to the record's.

A mixture of prefix styles, or anything else, is refused. The compression
(plain, gzip or xz) is chosen from the archive's first bytes and passed to tar
and to :mod:`tarfile` explicitly; an unknown format or a missing decompressor
is a refusal.

Then tar extracts into a fresh staging directory in the store
(``.restoring-<random>``), the staged tree is verified against the archive
(member set and ``tar --compare``), and one no-replace rename moves it into
place. A failure cleans the staging directory it created, through descriptors
on that inode; a crash leaves it, :func:`leftover_staging` and the store audit
report it, and :func:`reclaim_staging` (under the lock) removes it through the
same cleaner. The archive and its records are never touched.
"""

from __future__ import annotations

import errno
import os
import posixpath
import re
import secrets
import stat
import tarfile
from collections import Counter
from dataclasses import dataclass
from typing import IO, Literal

from claude_code_hooks_daemon.core.scratch_archive import (
    STAGING_PREFIX,
    ArchiveRecord,
    ArchiveStore,
    StoreRefused,
    fsync_dir,
    list_names,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    CLAIM_PREFIX,
    DEFAULT_MAX_DEPTH,
    WalkRefused,
    check_entry_name,
    open_child_dir,
    rename_noreplace_between,
    walk_tree,
)
from claude_code_hooks_daemon.core.scratch_archive_expire import Incomplete, complete_records
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
    require_decompressor,
    run_tar,
    tarfile_mode,
)

__all__ = [
    "STAGING_PREFIX",
    "Header",
    "Reclaimed",
    "RestoreRefused",
    "Restored",
    "RestoredWithLeftovers",
    "leftover_staging",
    "read_headers",
    "reclaim_staging",
    "restore",
]

#: Exactly the names :func:`_stage_and_move` creates (``secrets.token_hex(8)``).
_STAGING_NAME = re.compile(re.escape(STAGING_PREFIX) + r"[0-9a-f]{16}")
_STAGED_ROOT = "root"
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_KINDS = {
    tarfile.DIRTYPE: "dir",
    tarfile.REGTYPE: "file",
    tarfile.AREGTYPE: "file",
    tarfile.SYMTYPE: "symlink",
}
_STORED_KINDS = ("dir", "file", "symlink")
_EXTRACT = (
    "--extract",
    "--file=-",
    "--keep-old-files",
    "--no-same-owner",
    "--preserve-permissions",
)

Layout = Literal["directory", "member", "adopted"]


class RestoreRefused(Exception):
    """Nothing was restored.

    Any staging this restore created is gone, unless the message names it as
    left in the store (then :func:`reclaim_staging` removes it).
    """


#: What :func:`_clean_staging` can raise (``open_child_dir`` raises :class:`WalkRefused`).
_CLEAN_FAILURES = (RestoreRefused, WalkRefused, OSError)


@dataclass(frozen=True)
class Header:
    """One tar header: its name as stored, its kind and permission bits."""

    name: str
    kind: str
    mode: int


@dataclass(frozen=True)
class Restored:
    """An entry restored under ``name`` in the destination directory."""

    archive_id: str
    name: str
    layout: Layout


@dataclass(frozen=True)
class RestoredWithLeftovers(Restored):
    """Restored (the no-replace move succeeded), but a step after the move failed.

    ``problems`` names each failure: the root directory's mode not reset, the
    destination directory not synced, or the staging directory not cleaned.
    ``staging`` names a staging directory left in the store, for
    :func:`reclaim_staging`; ``None`` when it was cleaned.
    """

    problems: tuple[str, ...]
    staging: str | None


@dataclass(frozen=True)
class _Plan:
    layout: Layout
    member: str
    headers: tuple[Header, ...]
    compression: Compression = "none"


@dataclass(frozen=True)
class Reclaimed:
    """What :func:`reclaim_staging` did with one ``.restoring-`` name."""

    name: str
    outcome: Literal["reclaimed", "stuck", "foreign"]
    reason: str


def leftover_staging(store: ArchiveStore) -> tuple[str, ...]:
    """Staging directories a crashed restore left in the store; a restore never deletes them."""
    return tuple(sorted(n for n in list_names(store.dir_fd) if n.startswith(STAGING_PREFIX)))


def reclaim_staging(
    store: ArchiveStore, *, max_depth: int = DEFAULT_MAX_DEPTH
) -> tuple[Reclaimed, ...]:
    """Remove the staging directories crashed restores left; needs the store lock.

    Only a name shaped exactly as a restore creates it qualifies (any other
    ``.restoring-`` name is ``foreign`` and untouched). It must be a directory,
    not a link, owned by this user and on the store's device; it is then
    emptied and removed by :func:`_clean_staging`, through descriptors on that
    inode and never leaving its device. A failure leaves it ``stuck``.
    """
    store.require_lock("reclaiming restore staging")
    store_dev = os.fstat(store.dir_fd).st_dev
    results: list[Reclaimed] = []
    for name in leftover_staging(store):
        if not _STAGING_NAME.fullmatch(name):
            results.append(Reclaimed(name, "foreign", "not a name a restore creates"))
            continue
        try:
            info = os.lstat(name, dir_fd=store.dir_fd)
            if not stat.S_ISDIR(info.st_mode):
                raise RestoreRefused("not a directory (a link or a file); it is left in place")
            if info.st_uid != os.geteuid():
                raise RestoreRefused("owned by another user; it is left in place")
            if info.st_dev != store_dev:
                raise RestoreRefused("on another device than the store; it is left in place")
            _clean_staging(store, name, (info.st_ino, info.st_dev), max_depth=max_depth)
        except _CLEAN_FAILURES as exc:
            results.append(Reclaimed(name, "stuck", str(exc)))
            continue
        results.append(Reclaimed(name, "reclaimed", ""))
    return tuple(results)


def _name_ok(name: str) -> bool:
    """``.``, ``./<plain>...``, or (the P6 layout) ``<plain>[/<plain>...]``."""
    if name == ".":
        return True
    parts = name.split("/")
    if parts[0] == ".":
        return len(parts) > 1 and all(p not in ("", ".", "..") for p in parts[1:])
    return all(p not in ("", ".", "..") for p in parts)


def read_headers(handle: IO[bytes], compression: Compression = "none") -> tuple[Header, ...]:
    """Read every header; raise :class:`RestoreRefused` on any unsafe member."""
    headers: list[Header] = []
    try:
        with tarfile.open(fileobj=handle, mode=tarfile_mode(compression)) as archive:
            for member in archive:
                kind = _KINDS.get(member.type)
                if kind is None:
                    raise RestoreRefused(f"member {member.name!r} has a refused type")
                if not _name_ok(member.name):
                    raise RestoreRefused(f"member {member.name!r} escapes the entry")
                headers.append(Header(member.name, kind, stat.S_IMODE(member.mode)))
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise RestoreRefused(f"archive member headers cannot be read: {exc}") from exc
    names = [h.name for h in headers]
    if len(names) != len(set(names)):
        raise RestoreRefused("a member name is repeated")
    links = {h.name for h in headers if h.kind == "symlink"}
    for name in names:
        parts = name.split("/")
        if any("/".join(parts[:i]) in links for i in range(2, len(parts))):
            raise RestoreRefused(f"member {name!r} lies beneath a symbolic link member")
    return tuple(headers)


def _check_counts(record: ArchiveRecord, headers: tuple[Header, ...]) -> None:
    found = Counter(h.kind for h in headers)
    stored = all(found[k] == record.counts.get(k, 0) for k in _STORED_KINDS)
    other = sum(v for k, v in record.counts.items() if k not in _STORED_KINDS)
    if not stored or other != len(record.skipped):
        raise RestoreRefused("layout: the member counts disagree with the record")


def _plan(
    record: ArchiveRecord,
    headers: tuple[Header, ...],
    dest_name: str,
    compression: Compression = "none",
) -> _Plan:
    """Derive the layout from the headers; refuse when it disagrees with the record.

    Every header must share one prefix style: ``.``/``./...`` for a directory,
    ``./.sweeping-<name>`` for a loose file or batch, ``<name>``/``<name>/...``
    for a P6 adopted archive. A mixture is refused.
    """
    if headers and headers[0].name == ".":
        if headers[0].kind != "dir" or any(h.name == "." for h in headers[1:]):
            raise RestoreRefused("layout: the root member is not one directory")
        for header in headers[1:]:
            if not header.name.startswith("./"):
                raise RestoreRefused(f"layout: member {header.name!r} is not under the root")
        _check_counts(record, headers)
        return _Plan("directory", ".", headers, compression)
    if headers and not headers[0].name.startswith("./"):
        return _plan_adopted(record, headers, dest_name, compression)
    wanted = f"./{CLAIM_PREFIX}{dest_name}"
    for header in headers:
        parts = header.name.split("/")
        if len(parts) != 2 or parts[0] != "." or not parts[1].startswith(CLAIM_PREFIX):
            raise RestoreRefused(f"layout: member {header.name!r} is not a claimed loose file")
    match = [h for h in headers if h.name == wanted]
    if len(match) != 1:
        raise RestoreRefused(f"layout: the archive has no member for {dest_name!r}")
    if dict(record.counts) != {match[0].kind: 1}:
        raise RestoreRefused("layout: the member's kind disagrees with the record")
    return _Plan("member", wanted, headers, compression)


def _plan_adopted(
    record: ArchiveRecord,
    headers: tuple[Header, ...],
    dest_name: str,
    compression: Compression,
) -> _Plan:
    """The P6 layout: one ``<name>`` directory member and only ``<name>/...`` beside it."""
    for header in headers:
        if header.name != dest_name and not header.name.startswith(dest_name + "/"):
            raise RestoreRefused(f"layout: member {header.name!r} is not under {dest_name!r}")
    roots = [h for h in headers if h.name == dest_name]
    if len(roots) != 1 or roots[0].kind != "dir":
        raise RestoreRefused(f"layout: the archive has no directory member {dest_name!r}")
    if record.skipped:
        raise RestoreRefused("layout: an adopted archive cannot have skipped files")
    _check_counts(record, headers)
    return _Plan("adopted", dest_name, headers, compression)


def _select(records: tuple[ArchiveRecord, ...], entry: str | None) -> ArchiveRecord:
    if entry is None:
        if len(records) != 1:
            raise RestoreRefused("this archive holds several entries; name the entry")
        return records[0]
    for record in records:
        if record.original_path == entry:
            return record
    raise RestoreRefused(f"the archive holds no entry {entry!r}")


def _check_destination(store: ArchiveStore, dest_parent_fd: int, dest_name: str) -> None:
    try:
        os.lstat(dest_name, dir_fd=dest_parent_fd)
        present = True
    except FileNotFoundError:
        present = False
    except OSError as exc:
        raise RestoreRefused(f"the destination cannot be checked: {exc}") from exc
    if present:
        raise RestoreRefused(f"{dest_name!r} exists; restore never overwrites")
    if os.fstat(dest_parent_fd).st_dev != os.fstat(store.dir_fd).st_dev:
        raise RestoreRefused("the destination is on another device than the store")


def _checked_archive(
    store: ArchiveStore, record: ArchiveRecord
) -> tuple[int, tuple[Header, ...], Compression]:
    """Open the archive, check its size, hash and format, and read its headers, all via one fd."""
    try:
        fd = store.open_archive(record.archive_id)
    except StoreRefused as exc:
        raise RestoreRefused(str(exc)) from exc
    try:
        size, sha = digest_fd(fd)
        if (size, sha) != (record.archive_size, record.sha256):
            raise RestoreRefused("the archive's size or SHA-256 differs from its record")
        try:
            compression = compression_of(fd)
            require_decompressor(compression)
        except PackRefused as exc:
            raise RestoreRefused(str(exc)) from exc
        os.lseek(fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(fd), "rb") as handle:
            headers = read_headers(handle, compression)
    except BaseException:
        os.close(fd)
        raise
    return fd, headers, compression


def restore(
    store: ArchiveStore,
    archive_id: str,
    dest_parent_fd: int,
    *,
    tar: TarTool,
    max_inodes: int,
    entry: str | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Restored:
    """Restore ``archive_id`` (``entry`` names one of a batch) into ``dest_parent_fd``.

    Raises :class:`RestoreRefused` when nothing was restored. Returns
    :class:`RestoredWithLeftovers` when the entry WAS moved into place but a later
    step failed. The archive and its records are untouched either way.
    """
    store.require_lock("restore")
    try:
        records = complete_records(store.read_index(), store.read_events(), archive_id)
    except Incomplete as exc:
        raise RestoreRefused(str(exc)) from exc
    record = _select(records, entry)
    try:
        dest_name = check_entry_name(posixpath.basename(record.original_path))
    except ValueError as exc:
        raise RestoreRefused(f"the record's name cannot be restored: {exc}") from exc
    _check_destination(store, dest_parent_fd, dest_name)
    archive_fd, headers, compression = _checked_archive(store, record)
    try:
        plan = _plan(record, headers, dest_name, compression)
        problems, left = _stage_and_move(
            store,
            archive_fd,
            plan,
            dest_parent_fd,
            dest_name,
            tar=tar,
            max_inodes=max_inodes,
            max_depth=max_depth,
            timeout=timeout,
        )
    finally:
        os.close(archive_fd)
    if problems:
        return RestoredWithLeftovers(
            archive_id=archive_id,
            name=dest_name,
            layout=plan.layout,
            problems=problems,
            staging=left,
        )
    return Restored(archive_id=archive_id, name=dest_name, layout=plan.layout)


def _stage_and_move(
    store: ArchiveStore,
    archive_fd: int,
    plan: _Plan,
    dest_parent_fd: int,
    dest_name: str,
    *,
    tar: TarTool,
    max_inodes: int,
    max_depth: int,
    timeout: float,
) -> tuple[tuple[str, ...], str | None]:
    """Stage, verify and move; return the after-move problems and any staging left.

    A failure before or at the rename cleans the staging and raises
    :class:`RestoreRefused`; once the rename succeeded nothing raises (except a
    process death), every later failure is collected instead.
    """
    staging = STAGING_PREFIX + secrets.token_hex(8)
    os.mkdir(staging, 0o700, dir_fd=store.dir_fd)
    staging_fd = os.open(staging, _DIR_FLAGS, dir_fd=store.dir_fd)
    info = os.fstat(staging_fd)
    ident = (info.st_ino, info.st_dev)
    try:
        try:
            target = _extract_and_verify(
                staging_fd,
                archive_fd,
                plan,
                tar=tar,
                max_inodes=max_inodes,
                max_depth=max_depth,
                timeout=timeout,
            )
            problems = _move(staging_fd, target, dest_parent_fd, dest_name, _root_mode(plan))
        except Exception as exc:
            reason = str(exc) if isinstance(exc, RestoreRefused) else f"restore failed: {exc}"
            try:
                _clean_staging(store, staging, ident, max_depth=max_depth)
            except _CLEAN_FAILURES as clean_exc:
                reason += f"; staging {staging!r} was left in the store: {clean_exc}"
            raise RestoreRefused(reason) from exc
        try:
            os.fsync(dest_parent_fd)
        except OSError as exc:
            problems.append(f"the destination directory was not synced: {exc}")
        left: str | None = None
        try:
            _clean_staging(store, staging, ident, max_depth=max_depth)
        except _CLEAN_FAILURES as exc:
            problems.append(f"staging {staging!r} was left in the store: {exc}")
            left = staging
    finally:
        os.close(staging_fd)
    return tuple(problems), left


def _extract_and_verify(
    staging_fd: int,
    archive_fd: int,
    plan: _Plan,
    *,
    tar: TarTool,
    max_inodes: int,
    max_depth: int,
    timeout: float,
) -> str:
    """Extract into staging and verify it; return the staged name to move."""
    operands: tuple[str, ...] = ()
    flags = compression_flags(plan.compression)
    if plan.layout == "directory":
        os.mkdir(_STAGED_ROOT, 0o700, dir_fd=staging_fd)
        cwd_fd = os.open(_STAGED_ROOT, _DIR_FLAGS, dir_fd=staging_fd)
        target = _STAGED_ROOT
    elif plan.layout == "adopted":
        cwd_fd = os.dup(staging_fd)
        target = plan.member
    else:
        cwd_fd = os.dup(staging_fd)
        target = plan.member[2:]
        operands = ("--no-wildcards", "--no-unquote", "--", plan.member)
    try:
        os.lseek(archive_fd, 0, os.SEEK_SET)
        proc = run_tar(
            tar,
            [*_EXTRACT, *flags, *operands],
            cwd_fd=cwd_fd,
            stdin=archive_fd,
            stdout=None,
            timeout=timeout,
        )
        if proc.returncode != 0 or proc.stdout or proc.stderr:
            raise RestoreRefused(
                f"tar --extract failed (exit {proc.returncode}, "
                f"{len(proc.stderr.splitlines())} stderr lines)"
            )
        try:
            names = _staged_members(staging_fd, target, plan, max_inodes, max_depth)
            if names:
                batched_compare(cwd_fd, archive_fd, names, tar=tar, timeout=timeout, flags=flags)
        except (VerifyFailed, TarDidNotRun, WalkRefused, PackRefused) as exc:
            raise RestoreRefused(f"the staged tree failed verification: {exc}") from exc
    finally:
        os.close(cwd_fd)
    return target


def _staged_members(
    staging_fd: int, target: str, plan: _Plan, max_inodes: int, max_depth: int
) -> list[str]:
    """Check the staged member set equals the archive's; return the names to compare."""
    if plan.layout == "member":
        if sorted(list_names(staging_fd)) != [target]:
            raise VerifyFailed("staging holds other names than the restored member")
        return [plan.member]
    if plan.layout == "adopted" and sorted(list_names(staging_fd)) != [target]:
        raise VerifyFailed("staging holds other names than the adopted root")
    listing = walk_tree(staging_fd, target, max_inodes=max_inodes, max_depth=max_depth)
    members = members_of(listing, target)
    staged = {(n.rstrip("/") or ".") for n in members.names}
    if plan.layout == "adopted":
        # tar extracted the root itself, so it is compared too: "./x" names "<root>/x".
        staged = {target if n == "." else f"{target}/{n[2:]}" for n in staged}
        if members.skipped or staged != {h.name for h in plan.headers}:
            raise VerifyFailed("the staged member set differs from the archive")
        return sorted(staged)
    if members.skipped or staged != {h.name for h in plan.headers}:
        raise VerifyFailed("the staged member set differs from the archive")
    return [n for n in members.names if n != "./"]


def _root_mode(plan: _Plan) -> int | None:
    """The archived root directory's mode, which the move must restore; ``None`` for a member."""
    if plan.layout == "member":
        return None
    for header in plan.headers:
        if header.name == plan.member:
            return header.mode
    raise RestoreRefused("layout: the root member is missing")


def _move(
    staging_fd: int, target: str, dest_parent_fd: int, dest_name: str, root_mode: int | None
) -> list[str]:
    """The no-replace rename into place; return the problems found after it succeeded.

    A directory (``root_mode`` given: tar leaves its working directory's mode
    alone) is owner-writable for the move, then takes the archived root's mode.
    A failed rename raises :class:`RestoreRefused` (the caller cleans staging);
    a failed mode reset after it is a problem, never a refusal, since the entry
    is already in place.
    """
    target_fd: int | None = None
    if root_mode is not None:
        target_fd = os.open(target, _DIR_FLAGS, dir_fd=staging_fd)
    try:
        if target_fd is not None:
            os.fchmod(target_fd, stat.S_IMODE(os.fstat(target_fd).st_mode) | stat.S_IWUSR)
        try:
            rename_noreplace_between(staging_fd, target, dest_parent_fd, dest_name)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                raise RestoreRefused(f"{dest_name!r} exists; restore never overwrites") from exc
            raise RestoreRefused(f"the move into place failed: {exc}") from exc
        problems: list[str] = []
        if target_fd is not None and root_mode is not None:
            try:
                os.fchmod(target_fd, root_mode)
            except OSError as exc:
                problems.append(
                    f"the restored root's mode was not reset to {oct(root_mode)}: {exc}"
                )
        return problems
    finally:
        if target_fd is not None:
            os.close(target_fd)


def _clean_staging(
    store: ArchiveStore, name: str, ident: tuple[int, int], *, max_depth: int
) -> None:
    """Remove the staging directory this restore created, only if it is still that inode."""
    fd = os.open(name, _DIR_FLAGS, dir_fd=store.dir_fd)
    try:
        info = os.fstat(fd)
        if (info.st_ino, info.st_dev) != ident:
            raise RestoreRefused(f"staging {name!r} changed; it is left in place")
        _empty_dir(fd, ident[1], 0, max_depth)
    finally:
        os.close(fd)
    info = os.lstat(name, dir_fd=store.dir_fd)
    if (info.st_ino, info.st_dev) != ident:
        raise RestoreRefused(f"staging {name!r} changed; it is left in place")
    os.rmdir(name, dir_fd=store.dir_fd)
    fsync_dir(store.dir_fd)


def _empty_dir(dir_fd: int, dev: int, depth: int, max_depth: int) -> None:
    """Empty one staged directory through its descriptor, never leaving its device."""
    if depth > max_depth:
        raise RestoreRefused("staging is nested too deeply to clean; it is left in place")
    os.fchmod(dir_fd, 0o700)
    for child in list_names(dir_fd):
        info = os.lstat(child, dir_fd=dir_fd)
        if not stat.S_ISDIR(info.st_mode):
            os.unlink(child, dir_fd=dir_fd)
            continue
        if info.st_dev != dev:
            raise RestoreRefused("staging holds another device; it is left in place")
        child_fd = open_child_dir(dir_fd, child, info)
        try:
            _empty_dir(child_fd, dev, depth + 1, max_depth)
        finally:
            os.close(child_fd)
        os.rmdir(child, dir_fd=dir_fd)
