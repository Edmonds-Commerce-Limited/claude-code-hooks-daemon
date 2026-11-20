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
import importlib
import os
import posixpath
import shutil
import subprocess  # nosec B404 - argv only, never a shell
import tarfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO, Literal

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
#: A member operand is a literal name: no glob, no backslash unquoting.
_LITERAL_OPERANDS = ("--no-wildcards", "--no-unquote")
#: A P6 archive's members are ``<entry>/...``; compared inside the entry, the root is stripped.
_STRIP_ROOT = "--strip-components=1"


#: The most argv bytes of member names one restricted ``tar --compare`` is given.
COMPARE_ARGV_BUDGET = 64 * 1024


class PackRefused(Exception):
    """The entry was not packed; no archive of it remains."""


class VerifyFailed(Exception):
    """The archive does not match the tree; it authorises no removal."""


class TarDidNotRun(VerifyFailed):
    """tar could not be run (missing, timed out): nothing was learned about the tree."""


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


def read_member_names(handle: IO[bytes], compression: Compression = "none") -> list[str]:
    """Read every header of a tar stream; raise :class:`VerifyFailed` on an unsafe member."""
    names: list[str] = []
    try:
        with tarfile.open(fileobj=handle, mode=tarfile_mode(compression)) as archive:
            for member in archive:
                if member.type not in _MEMBER_TYPES:
                    raise VerifyFailed(f"member {member.name!r} has a refused type")
                if not _member_ok(member.name):
                    raise VerifyFailed(f"member {member.name!r} escapes the entry")
                names.append(_canonical(member.name))
    except tarfile.TarError as exc:
        raise VerifyFailed(f"archive cannot be read: {exc}") from exc
    return names


def _adopted_member_ok(name: str, root: str) -> bool:
    if name == root:
        return True
    if not name.startswith(root + "/"):
        return False
    return all(part not in ("", ".", "..") for part in name[len(root) + 1 :].split("/"))


def _read_adopted_names(handle: IO[bytes], compression: Compression, root: str) -> list[str]:
    """Read a P6 archive's headers: ``root`` (a directory) or ``root/<plain parts>`` only."""
    names: list[str] = []
    root_is_dir = False
    try:
        with tarfile.open(fileobj=handle, mode=tarfile_mode(compression)) as archive:
            for member in archive:
                if member.type not in _MEMBER_TYPES:
                    raise VerifyFailed(f"member {member.name!r} has a refused type")
                name = member.name
                if member.isdir() and name.endswith("/"):
                    name = name[:-1]
                if not _adopted_member_ok(name, root):
                    raise VerifyFailed(f"member {member.name!r} is not under {root!r}")
                if name == root:
                    root_is_dir = member.isdir()
                names.append(name)
    except tarfile.TarError as exc:
        raise VerifyFailed(f"archive cannot be read: {exc}") from exc
    if not root_is_dir:
        raise VerifyFailed(f"the archive has no directory member {root!r}")
    return names


def _sniff(archive_fd: int) -> Compression:
    """The archive's compression from its first bytes, with its decompressor present."""
    try:
        compression = compression_of(archive_fd)
        require_decompressor(compression)
    except PackRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    return compression


def _archive_names(
    archive_fd: int, compression: Compression, adopted_root: str | None
) -> list[str]:
    os.lseek(archive_fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(archive_fd), "rb") as handle:
        if adopted_root is None:
            return read_member_names(handle, compression)
        return _read_adopted_names(handle, compression, adopted_root)


def _layout_name(walk_name: str, adopted_root: str | None) -> str:
    """A walk name (``./``, ``./x/``, ``./x``) as the archive's layout names it."""
    if adopted_root is None:
        return _canonical(walk_name)
    rel = walk_name[2:].rstrip("/")
    return f"{adopted_root}/{rel}" if rel else adopted_root


def _require_adoptable(listing: TreeListing, adopted_root: str | None) -> None:
    if adopted_root is None:
        return
    try:
        check_name(adopted_root)
    except ValueError as exc:
        raise VerifyFailed(f"the adopted root is not one name: {exc}") from exc
    if listing.root.kind != "dir":
        raise VerifyFailed("an adopted archive is only checked against a directory")


def _compare_adopted(
    parent_fd: int,
    claimed_name: str,
    listing: TreeListing,
    archive_fd: int,
    operands: list[str],
    *,
    compression: Compression,
    tar: TarTool,
    timeout: float,
) -> None:
    """``tar --compare --strip-components=1`` inside the claimed tree, naming ``operands``.

    The root strips to an empty name tar cannot stat, so it is never an
    operand; with no other member the member set alone is the proof.
    """
    if not operands:
        return
    try:
        cwd_fd = _cwd_fd(parent_fd, claimed_name, listing)
    except WalkRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    try:
        batched_compare(
            cwd_fd,
            archive_fd,
            operands,
            tar=tar,
            timeout=timeout,
            flags=(*compression_flags(compression), _STRIP_ROOT),
        )
    finally:
        os.close(cwd_fd)


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
    adopted_root: str | None = None,
) -> Verified:
    """Verify ``archive_id`` against the claimed tree both ways; raise :class:`VerifyFailed`.

    The compression is read from the archive's first bytes. ``adopted_root``
    names the layout: ``None`` for a packed ``./`` archive, the entry name for
    an adopted (P6) ``<entry>/...`` archive. The caller takes it from the
    record, never from the archive, so a mismatch refuses rather than adapts.
    """
    check_name(claimed_name)
    try:
        listing = walk_tree(parent_fd, claimed_name, max_inodes=max_inodes, max_depth=max_depth)
        expected = members_of(listing, claimed_name)
    except (WalkRefused, PackRefused) as exc:
        raise VerifyFailed(f"the claimed tree cannot be listed: {exc}") from exc
    _require_adoptable(listing, adopted_root)
    try:
        archive_fd = store.open_archive(archive_id)
    except StoreRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    try:
        size, sha = _digest(archive_fd)
        if expected_sha256 is not None and sha != expected_sha256:
            raise VerifyFailed("archive SHA-256 differs from its record")
        compression = _sniff(archive_fd)
        names = _archive_names(archive_fd, compression, adopted_root)
        wanted = [_layout_name(n, adopted_root) for n in expected.names]
        if len(names) != len(set(names)) or sorted(names) != sorted(wanted):
            raise VerifyFailed(
                f"archive member set differs from the tree ({len(names)} members, "
                f"{len(wanted)} expected)"
            )
        os.lseek(archive_fd, 0, os.SEEK_SET)
        if adopted_root is None:
            _compare(
                parent_fd,
                claimed_name,
                listing,
                archive_fd,
                tar=tar,
                timeout=timeout,
                flags=compression_flags(compression),
            )
        else:
            _compare_adopted(
                parent_fd,
                claimed_name,
                listing,
                archive_fd,
                [n for n in wanted if n != adopted_root],
                compression=compression,
                tar=tar,
                timeout=timeout,
            )
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
    flags: tuple[str, ...] = (),
) -> None:
    """Run ``tar --compare``; with ``only``, compare just those members."""
    try:
        cwd_fd = _cwd_fd(parent_fd, claimed_name, listing)
    except WalkRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    operands = (*_LITERAL_OPERANDS, "--", *only) if only else ()
    try:
        proc = _run_tar(
            tar,
            ["--compare", *flags, "--file=-", *_COMMON, *operands],
            cwd_fd=cwd_fd,
            stdin=archive_fd,
            stdout=None,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TarDidNotRun(f"tar --compare did not run: {exc}") from exc
    finally:
        os.close(cwd_fd)
    if proc.returncode != 0 or proc.stdout or proc.stderr:
        lines = len(proc.stdout.splitlines()) + len(proc.stderr.splitlines())
        raise VerifyFailed(
            f"tar --compare found differences (exit {proc.returncode}, {lines} lines)"
        )


def _batches(names: list[str], budget: int) -> Iterator[tuple[str, ...]]:
    """Split ``names`` into argv batches of at most ``budget`` bytes (at least one name each)."""
    batch: list[str] = []
    used = 0
    for name in names:
        size = len(os.fsencode(name)) + 1
        if batch and used + size > budget:
            yield tuple(batch)
            batch, used = [], 0
        batch.append(name)
        used += size
    if batch:
        yield tuple(batch)


Compression = Literal["gzip", "xz", "none"]

_GZIP_MAGIC = b"\x1f\x8b"
_XZ_MAGIC = b"\xfd7zXZ\x00"
_USTAR_OFFSET = 257
_USTAR_MAGIC = b"ustar"
_FLAGS: dict[Compression, tuple[str, ...]] = {"gzip": ("--gzip",), "xz": ("--xz",), "none": ()}
StreamMode = Literal["r|gz", "r|xz", "r|"]
_STREAM_MODES: dict[Compression, StreamMode] = {"gzip": "r|gz", "xz": "r|xz", "none": "r|"}
_DECOMPRESSORS: dict[Compression, tuple[str, str]] = {
    "gzip": ("gzip", "zlib"),
    "xz": ("xz", "lzma"),
}


def compression_of(fd: int) -> Compression:
    """Choose an archive's compression from its first bytes (read with ``pread``, offset 0).

    Gzip and xz by their magic numbers, a plain tar by ``ustar`` at offset 257
    (the GNU, ustar and pax formats all carry it). Anything else, a short file
    included, raises :class:`PackRefused`: nothing is ever guessed.
    """
    head = os.pread(fd, _USTAR_OFFSET + len(_USTAR_MAGIC), 0)
    if head.startswith(_GZIP_MAGIC):
        return "gzip"
    if head.startswith(_XZ_MAGIC):
        return "xz"
    if head[_USTAR_OFFSET:] == _USTAR_MAGIC:
        return "none"
    raise PackRefused("the archive format is not a plain, gzip or xz tar")


def compression_flags(kind: Compression) -> tuple[str, ...]:
    """tar's explicit decompression flag for ``kind`` (none for a plain tar)."""
    return _FLAGS[kind]


def tarfile_mode(kind: Compression) -> StreamMode:
    """The explicit :func:`tarfile.open` stream mode for ``kind``; never ``r|*``."""
    return _STREAM_MODES[kind]


def require_decompressor(kind: Compression) -> None:
    """Raise :class:`PackRefused` unless tar's decompressor program and Python's module exist."""
    if kind == "none":
        return
    program, module = _DECOMPRESSORS[kind]
    if shutil.which(program, path=_TAR_ENV["PATH"]) is None:
        raise PackRefused(f"the {program} decompressor is not installed")
    try:
        importlib.import_module(module)
    except ImportError as exc:
        raise PackRefused(f"the {module} decompressor module is unavailable: {exc}") from exc


def digest_fd(fd: int) -> tuple[int, str]:
    """Return the size and SHA-256 of an open archive, read from its start."""
    return _digest(fd)


def run_tar(
    tar: TarTool,
    args: list[str],
    *,
    cwd_fd: int,
    stdin: bytes | int,
    stdout: int | None,
    timeout: float,
) -> subprocess.CompletedProcess[bytes]:
    """Run GNU tar by argv in the directory ``cwd_fd`` names, with the scrubbed environment."""
    return _run_tar(tar, args, cwd_fd=cwd_fd, stdin=stdin, stdout=stdout, timeout=timeout)


def tar_create_args() -> list[str]:
    """tar's argv for packing a NUL-separated, ``./``-prefixed member list read on stdin."""
    return ["--create", "--file=-", *_COMMON, "--null", "--verbatim-files-from", "--files-from=-"]


def batched_compare(
    dir_fd: int,
    archive_fd: int,
    names: list[str],
    *,
    tar: TarTool,
    timeout: float,
    flags: tuple[str, ...] = (),
) -> None:
    """Run ``tar --compare`` in ``dir_fd`` restricted to ``names``, in argv-bounded batches.

    ``flags`` go before the operands: a decompression flag (:func:`compression_flags`),
    and ``--strip-components=1`` for a P6 archive compared inside its entry.
    Raises :class:`VerifyFailed` on any difference, :class:`TarDidNotRun` when tar cannot run.
    """
    for batch in _batches(names, COMPARE_ARGV_BUDGET):
        os.lseek(archive_fd, 0, os.SEEK_SET)
        cwd_fd = os.dup(dir_fd)
        try:
            proc = _run_tar(
                tar,
                ["--compare", *flags, "--file=-", *_COMMON, *_LITERAL_OPERANDS, "--", *batch],
                cwd_fd=cwd_fd,
                stdin=archive_fd,
                stdout=None,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TarDidNotRun(f"tar --compare did not run: {exc}") from exc
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
    adopted_root: str | None = None,
) -> Verified:
    """Verify a partly removed claimed tree: all that is left is in the archive, unchanged.

    The archive must match its recorded SHA-256, every remaining name must be a
    member, and ``tar --compare`` restricted to the remaining non-directories
    must be clean. Directories carry no content, and their times change as they
    are emptied, so they are checked by membership only. ``adopted_root`` names
    the layout as in :func:`verify`. Raises :class:`VerifyFailed`.
    """
    check_name(claimed_name)
    try:
        listing = walk_tree(parent_fd, claimed_name, max_inodes=max_inodes, max_depth=max_depth)
        remaining = members_of(listing, claimed_name)
    except (WalkRefused, PackRefused) as exc:
        raise VerifyFailed(f"the claimed tree cannot be listed: {exc}") from exc
    _require_adoptable(listing, adopted_root)
    try:
        archive_fd = store.open_archive(archive_id)
    except StoreRefused as exc:
        raise VerifyFailed(str(exc)) from exc
    try:
        size, sha = _digest(archive_fd)
        if sha != expected_sha256:
            raise VerifyFailed("archive SHA-256 differs from its record")
        compression = _sniff(archive_fd)
        names = _archive_names(archive_fd, compression, adopted_root)
        if len(names) != len(set(names)):
            raise VerifyFailed("archive holds a member twice")
        absent = {_layout_name(n, adopted_root) for n in remaining.names} - set(names)
        if absent:
            raise VerifyFailed(f"{len(absent)} remaining names are not in the archive")
        files = [n for n in remaining.names if not n.endswith("/")]
        if adopted_root is not None:
            _compare_adopted(
                parent_fd,
                claimed_name,
                listing,
                archive_fd,
                [_layout_name(n, adopted_root) for n in files],
                compression=compression,
                tar=tar,
                timeout=timeout,
            )
        else:
            for batch in _batches(files, COMPARE_ARGV_BUDGET):
                os.lseek(archive_fd, 0, os.SEEK_SET)
                _compare(
                    parent_fd,
                    claimed_name,
                    listing,
                    archive_fd,
                    tar=tar,
                    timeout=timeout,
                    only=batch,
                    flags=compression_flags(compression),
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
