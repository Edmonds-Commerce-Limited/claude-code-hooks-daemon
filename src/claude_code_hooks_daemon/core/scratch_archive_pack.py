"""Pack a claimed scratch entry and verify it both ways (Plan 00627 Task 3.3).

DESIGN.md section 5.2 steps 4-5 and section 5.3. GNU tar runs by argv, never a
shell, with a scrubbed environment (no ``TAR_OPTIONS``, ``LC_ALL=C``). Its
working directory is the procfs magic link of a descriptor of the claimed
inode, so a path swapped after the claim cannot redirect it. The member list is
our own walk, NUL-separated and ``./``-prefixed, read ``--verbatim-files-from``
on stdin with ``--no-recursion``: a name is never an option and tar never
decides on its own what to include. Links are stored as links (never ``-h``);
sockets, FIFOs and device nodes are skipped and listed; any non-directory with
more than one hard link refuses the entry, because its other name may be
outside it (stricter than DESIGN 5.3: an internal pair is refused too).

Verification, both ways:

- the archive's headers are read first and every member must be ``.`` or under
  ``./``, with no ``..`` component, of type directory, regular file or symlink;
  nothing else runs against an archive that fails this,
- archive to tree: ``tar --compare`` exits 0 and prints nothing,
- tree to archive: the member set equals a fresh walk's (``--compare`` cannot
  see a file added to the tree),
- the SHA-256 of the archive, against the record's when one exists.

Every refusal discards the unrecorded archive; the caller renames the entry back.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import shutil
import subprocess  # nosec B404 - argv only, never a shell
import tarfile
from collections import Counter
from dataclasses import dataclass
from typing import IO

from claude_code_hooks_daemon.core.scratch_archive import ArchiveStore, StoreRefused
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    DEFAULT_MAX_DEPTH,
    Claimed,
    TreeListing,
    WalkRefused,
    check_name,
    fingerprint_of,
    walk_tree,
)

#: Kinds tar is never asked to read: listed in the record instead.
SKIPPED_KINDS = frozenset({"fifo", "socket", "chardev", "blockdev", "unknown"})

#: How long one tar run may take before the entry is refused.
DEFAULT_TAR_TIMEOUT_SECONDS = 600.0

_TAR_ENV = {"LC_ALL": "C", "PATH": "/usr/bin:/bin"}
_COMMON = ("--no-recursion", "--one-file-system", "--numeric-owner", "--format=gnu")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_MEMBER_TYPES = (tarfile.DIRTYPE, tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.SYMTYPE)
_CHUNK = 1 << 20
_PROC_FD_PARTS = ("", "proc", "self", "fd")


class PackRefused(Exception):
    """The entry was not packed; no archive of it remains."""


class VerifyFailed(Exception):
    """The archive does not match the tree; it authorises no removal."""


@dataclass(frozen=True)
class TarTool:
    """An absolute path to a GNU tar."""

    path: str


def find_gnu_tar(path: str | None = None) -> TarTool:
    """Resolve GNU tar (``path`` or ``tar`` on ``PATH``); raise :class:`PackRefused` otherwise."""
    resolved = path if path is not None else shutil.which("tar")
    if resolved is None or not resolved.startswith("/"):
        raise PackRefused("GNU tar is not on PATH as an absolute path")
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv
            [resolved, "--version"],
            capture_output=True,
            env=_TAR_ENV,
            timeout=30,
            check=False,
        )
    except OSError as exc:
        raise PackRefused(f"tar at {resolved} cannot run: {exc}") from exc
    first = proc.stdout.decode(errors="replace").splitlines()[:1]
    if proc.returncode != 0 or not first or "GNU tar" not in first[0]:
        raise PackRefused(f"{resolved} is not GNU tar")
    return TarTool(resolved)


@dataclass(frozen=True)
class Members:
    """What tar is asked to store, what is skipped, and the counts by kind."""

    names: tuple[str, ...]
    skipped: tuple[str, ...]
    counts: dict[str, int]


@dataclass(frozen=True)
class PackResult:
    """A packed, verified, fsynced archive that no record names yet."""

    archive_id: str
    members: tuple[str, ...]
    skipped: tuple[str, ...]
    counts: dict[str, int]
    size: int
    sha256: str


@dataclass(frozen=True)
class Verified:
    """The archive matched the tree both ways."""

    size: int
    sha256: str
    members: tuple[str, ...]


def members_of(listing: TreeListing, claimed_name: str) -> Members:
    """Turn a walk into tar's member list; refuse a special root or a multiply-linked file."""
    counts = dict(Counter(n.kind for n in listing.nodes))
    root = listing.root
    if root.kind in SKIPPED_KINDS:
        raise PackRefused(f"the entry itself is a {root.kind}; it is never packed")
    for node in listing.nodes:
        if node.kind != "dir" and node.nlink > 1:
            raise PackRefused(f"{node.rel or claimed_name!r} has {node.nlink} hard links")
    if root.kind != "dir":
        return Members(names=(f"./{claimed_name}",), skipped=(), counts=counts)
    names: list[str] = []
    skipped: list[str] = []
    for node in listing.nodes:
        if node.kind in SKIPPED_KINDS:
            skipped.append(node.rel)
        elif node.kind == "dir":
            names.append(f"./{node.rel}/" if node.rel else "./")
        else:
            names.append(f"./{node.rel}")
    return Members(names=tuple(names), skipped=tuple(skipped), counts=counts)


def _canonical(name: str) -> str:
    stripped = name.rstrip("/")
    return stripped or "."


def _cwd_fd(parent_fd: int, claimed_name: str, listing: TreeListing) -> int:
    """A descriptor of the directory tar runs in: the claimed tree, or its parent for a file."""
    root = listing.root
    if root.kind != "dir":
        return os.dup(parent_fd)
    try:
        fd = os.open(claimed_name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise WalkRefused(f"cannot open the claimed tree: {exc}") from exc
    info = os.fstat(fd)
    if (info.st_ino, info.st_dev) != (root.ino, root.dev):
        os.close(fd)
        raise WalkRefused("the claimed tree changed since it was walked")
    return fd


def _run_tar(
    tar: TarTool,
    args: list[str],
    *,
    cwd_fd: int,
    stdin: bytes | int,
    stdout: int | None,
    timeout: float,
) -> subprocess.CompletedProcess[bytes]:
    cwd = "/".join((*_PROC_FD_PARTS, str(cwd_fd)))
    out = stdout if stdout is not None else subprocess.PIPE
    if isinstance(stdin, bytes):
        return subprocess.run(  # nosec B603 - argv only, scrubbed env
            [tar.path, *args],
            cwd=cwd,
            pass_fds=(cwd_fd,),
            env=_TAR_ENV,
            input=stdin,
            stdout=out,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    return subprocess.run(  # nosec B603 - argv only, scrubbed env
        [tar.path, *args],
        cwd=cwd,
        pass_fds=(cwd_fd,),
        env=_TAR_ENV,
        stdin=stdin,
        stdout=out,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _digest(fd: int) -> tuple[int, str]:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(fd, _CHUNK):
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def _member_ok(name: str) -> bool:
    if name in (".", "./"):
        return True
    if not name.startswith("./") or name.startswith(".//"):
        return False
    return ".." not in name.split("/") and not posixpath.isabs(name)


def read_member_names(handle: IO[bytes]) -> list[str]:
    """Read every header of a tar stream; raise :class:`VerifyFailed` on an unsafe member."""
    names: list[str] = []
    try:
        with tarfile.open(fileobj=handle, mode="r|") as archive:
            for member in archive:
                if member.type not in _MEMBER_TYPES:
                    raise VerifyFailed(f"member {member.name!r} has a refused type")
                if not _member_ok(member.name):
                    raise VerifyFailed(f"member {member.name!r} escapes the entry")
                names.append(_canonical(member.name))
    except tarfile.TarError as exc:
        raise VerifyFailed(f"archive cannot be read: {exc}") from exc
    return names


def verify(
    parent_fd: int,
    claimed_name: str,
    store: ArchiveStore,
    archive_id: str,
    *,
    tar: TarTool,
    max_inodes: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    expected_sha256: str | None = None,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Verified:
    """Verify ``archive_id`` against the claimed tree both ways; raise :class:`VerifyFailed`."""
    check_name(claimed_name)
    try:
        listing = walk_tree(parent_fd, claimed_name, max_inodes=max_inodes, max_depth=max_depth)
        expected = members_of(listing, claimed_name)
    except (WalkRefused, PackRefused) as exc:
        raise VerifyFailed(f"the claimed tree cannot be listed: {exc}") from exc
    try:
        archive_fd = store.open_archive(archive_id)
    except StoreRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    try:
        size, sha = _digest(archive_fd)
        if expected_sha256 is not None and sha != expected_sha256:
            raise VerifyFailed("archive SHA-256 differs from its record")
        os.lseek(archive_fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(archive_fd), "rb") as handle:
            names = read_member_names(handle)
        wanted = [_canonical(n) for n in expected.names]
        if len(names) != len(set(names)) or sorted(names) != sorted(wanted):
            raise VerifyFailed(
                f"archive member set differs from the tree ({len(names)} members, "
                f"{len(wanted)} expected)"
            )
        os.lseek(archive_fd, 0, os.SEEK_SET)
        _compare(parent_fd, claimed_name, listing, archive_fd, tar=tar, timeout=timeout)
    finally:
        os.close(archive_fd)
    return Verified(size=size, sha256=sha, members=expected.names)


def _compare(
    parent_fd: int,
    claimed_name: str,
    listing: TreeListing,
    archive_fd: int,
    *,
    tar: TarTool,
    timeout: float,
    only: tuple[str, ...] = (),
) -> None:
    """Run ``tar --compare``; with ``only``, compare just those members."""
    try:
        cwd_fd = _cwd_fd(parent_fd, claimed_name, listing)
    except WalkRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    operands = ("--", *only) if only else ()
    try:
        proc = _run_tar(
            tar,
            ["--compare", "--file=-", *_COMMON, *operands],
            cwd_fd=cwd_fd,
            stdin=archive_fd,
            stdout=None,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerifyFailed(f"tar --compare did not run: {exc}") from exc
    finally:
        os.close(cwd_fd)
    if proc.returncode != 0 or proc.stdout or proc.stderr:
        lines = len(proc.stdout.splitlines()) + len(proc.stderr.splitlines())
        raise VerifyFailed(
            f"tar --compare found differences (exit {proc.returncode}, {lines} lines)"
        )


def verify_remaining(
    parent_fd: int,
    claimed_name: str,
    store: ArchiveStore,
    archive_id: str,
    *,
    tar: TarTool,
    max_inodes: int,
    expected_sha256: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> Verified:
    """Verify a partly removed claimed tree: all that is left is in the archive, unchanged.

    The archive must match its recorded SHA-256, every remaining name must be a
    member, and ``tar --compare`` restricted to the remaining non-directories
    must be clean. Directories carry no content, and their times change as they
    are emptied, so they are checked by membership only. Raises
    :class:`VerifyFailed`.
    """
    check_name(claimed_name)
    try:
        listing = walk_tree(parent_fd, claimed_name, max_inodes=max_inodes, max_depth=max_depth)
        remaining = members_of(listing, claimed_name)
    except (WalkRefused, PackRefused) as exc:
        raise VerifyFailed(f"the claimed tree cannot be listed: {exc}") from exc
    try:
        archive_fd = store.open_archive(archive_id)
    except StoreRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    try:
        size, sha = _digest(archive_fd)
        if sha != expected_sha256:
            raise VerifyFailed("archive SHA-256 differs from its record")
        os.lseek(archive_fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(archive_fd), "rb") as handle:
            names = read_member_names(handle)
        if len(names) != len(set(names)):
            raise VerifyFailed("archive holds a member twice")
        absent = {_canonical(n) for n in remaining.names} - set(names)
        if absent:
            raise VerifyFailed(f"{len(absent)} remaining names are not in the archive")
        files = tuple(n for n in remaining.names if not n.endswith("/"))
        if files:
            os.lseek(archive_fd, 0, os.SEEK_SET)
            _compare(
                parent_fd, claimed_name, listing, archive_fd, tar=tar, timeout=timeout, only=files
            )
    finally:
        os.close(archive_fd)
    return Verified(size=size, sha256=sha, members=remaining.names)


def pack(
    handle: Claimed,
    store: ArchiveStore,
    archive_id: str,
    *,
    tar: TarTool,
    max_inodes: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timeout: float = DEFAULT_TAR_TIMEOUT_SECONDS,
) -> PackResult:
    """Pack a claimed entry into ``<id>.tar``, verify it both ways and fsync it.

    Raises :class:`PackRefused` with no archive left behind; the claim is the
    caller's to release.
    """
    try:
        listing = walk_tree(
            handle.parent_fd, handle.claimed_name, max_inodes=max_inodes, max_depth=max_depth
        )
    except WalkRefused as exc:
        raise PackRefused(f"the claimed entry cannot be walked: {exc}") from exc
    if fingerprint_of(listing) != handle.fingerprint:
        raise PackRefused("fingerprint changed since the claim")
    members = members_of(listing, handle.claimed_name)
    try:
        archive_fd = store.create_archive(archive_id)
    except StoreRefused as exc:
        raise PackRefused(str(exc)) from exc
    try:
        try:
            _create(handle, listing, members, archive_fd, tar=tar, timeout=timeout)
            os.fsync(archive_fd)
        finally:
            os.close(archive_fd)
        os.fsync(store.dir_fd)
        verified = verify(
            handle.parent_fd,
            handle.claimed_name,
            store,
            archive_id,
            tar=tar,
            max_inodes=max_inodes,
            max_depth=max_depth,
            timeout=timeout,
        )
        if verified.members != members.names:
            raise VerifyFailed("the tree changed while packing")
    except (PackRefused, VerifyFailed, OSError) as exc:
        store.discard_unrecorded(archive_id)
        raise PackRefused(f"pack of {handle.name!r} refused: {exc}") from exc
    return PackResult(
        archive_id=archive_id,
        members=members.names,
        skipped=members.skipped,
        counts=members.counts,
        size=verified.size,
        sha256=verified.sha256,
    )


def _create(
    handle: Claimed,
    listing: TreeListing,
    members: Members,
    archive_fd: int,
    *,
    tar: TarTool,
    timeout: float,
) -> None:
    try:
        cwd_fd = _cwd_fd(handle.parent_fd, handle.claimed_name, listing)
    except WalkRefused as exc:
        raise PackRefused(str(exc)) from exc
    names = b"".join(os.fsencode(n) + b"\0" for n in members.names)
    args = ["--create", "--file=-", *_COMMON, "--null", "--verbatim-files-from", "--files-from=-"]
    try:
        proc = _run_tar(tar, args, cwd_fd=cwd_fd, stdin=names, stdout=archive_fd, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PackRefused(f"tar --create did not run: {exc}") from exc
    finally:
        os.close(cwd_fd)
    if proc.returncode != 0 or proc.stderr:
        raise PackRefused(
            f"tar --create failed (exit {proc.returncode}, "
            f"{len(proc.stderr.splitlines())} stderr lines)"
        )
