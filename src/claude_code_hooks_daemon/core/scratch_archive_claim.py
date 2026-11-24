"""Claim a scratch entry by rename (Plan 00627 Task 3.2, DESIGN.md section 5.2 steps 2-3).

The entry is renamed to ``.sweeping-<name>`` in the same directory through a
directory descriptor, with ``renameat2(RENAME_NOREPLACE)`` so the claim can
never replace a file or an empty directory already holding that name. Where the
no-replace rename is unavailable, nothing is claimed. A late writer using the
old path then fails loudly instead of writing into a tree that is about to go.

After the rename the fingerprint is re-taken from the claimed tree and compared
with the one taken at classification; any difference, a failed walk, or a
failed liveness check renames the entry back. The rename changes the entry
root's own ctime (pinned by a test), so the fingerprint leaves the root's ctime
out and the rename-back carries the claim time for the clock to subtract.

The walk here is the one the pack and removal steps reuse: ``lstat`` only,
directories opened ``O_NOFOLLOW`` relative to their parent's descriptor and
checked against the ``lstat`` they were chosen from, one device, and bounded in
inodes and depth (and so in open descriptors).
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

#: The prefix a claimed entry carries until it is packed and removed, or renamed back.
CLAIM_PREFIX = ".sweeping-"

#: The deepest directory nesting a walk enters before refusing the entry.
DEFAULT_MAX_DEPTH = 256

#: The procfs directory of this process's descriptors, as path parts.
PROC_FD_PARTS = ("", "proc", "self", "fd")

#: The xattr namespace tar here does not carry and an unprivileged user can set.
USER_XATTR_PREFIX = "user."

_RENAME_NOREPLACE = 1
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
#: ``st_blocks`` counts 512-byte units whatever the filesystem's block size.
_BLOCK_BYTES = 512


def _load_renameat2() -> Callable[..., int] | None:
    libc = ctypes.CDLL(None, use_errno=True)
    func = getattr(libc, "renameat2", None)
    if func is None:
        return None
    func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    func.restype = ctypes.c_int
    result: Callable[..., int] = func
    return result


_RENAMEAT2: Callable[..., int] | None = _load_renameat2()


class WalkRefused(Exception):
    """The tree could not be walked completely; it authorises nothing."""


class ClaimRefused(Exception):
    """The entry was not claimed; nothing was renamed."""


class ClaimStuck(Exception):
    """A claimed entry could not be renamed back; it stays under its claimed name."""


@dataclass(frozen=True)
class Node:
    """One inode of a walked tree, from ``lstat``; ``rel`` is ``""`` for the root."""

    rel: str
    kind: str
    ino: int
    dev: int
    nlink: int
    ctime_ns: int
    mtime_ns: int
    size: int
    uid: int = -1
    gid: int = -1
    #: ``user.*`` extended attribute names; ``None`` when they could not be read.
    user_xattrs: tuple[str, ...] | None = None
    #: A regular file with a hole; ``None`` when that could not be checked.
    sparse: bool | None = None


@dataclass(frozen=True)
class TreeListing:
    """Every inode of a tree, root first, parents before children."""

    nodes: tuple[Node, ...]

    @property
    def root(self) -> Node:
        """The entry root's node."""
        return self.nodes[0]


@dataclass(frozen=True)
class Fingerprint:
    """What must not change between classification and claim."""

    count: int
    newest_ctime_ns: int
    root_kind: str
    root_ino: int
    root_dev: int
    root_mtime_ns: int
    root_size: int


def kind_of(mode: int) -> str:
    """Name the file type of an ``st_mode``."""
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "chardev"
    if stat.S_ISBLK(mode):
        return "blockdev"
    return "unknown"


def _list_xattrs(path: str) -> list[str]:
    return os.listxattr(path, follow_symlinks=False)


def _user_xattrs(dir_fd: int, name: str) -> tuple[str, ...] | None:
    """The ``user.*`` xattr names of ``name`` in ``dir_fd``, never following a final link.

    Read through the procfs link of the already-verified directory descriptor,
    so a path swapped above it cannot redirect the probe. A filesystem without
    xattrs has none; any other failure is unknown, which refuses a pack.
    """
    try:
        names = _list_xattrs("/".join((*PROC_FD_PARTS, str(dir_fd), name)))
    except OSError as exc:
        if exc.errno == errno.ENOTSUP:
            return ()
        return None
    return tuple(sorted(n for n in names if n.startswith(USER_XATTR_PREFIX)))


def _few_blocks(info: os.stat_result) -> bool:
    return info.st_blocks * _BLOCK_BYTES < info.st_size


def _has_hole(fd: int, size: int) -> bool:
    return os.lseek(fd, 0, os.SEEK_HOLE) < size


def _sparse(dir_fd: int, name: str, info: os.stat_result) -> bool | None:
    """Whether regular file ``name`` has a hole; ``None`` when that cannot be checked.

    Few allocated blocks only suggest a hole (a compressing filesystem reports
    the same), so the file is opened and ``SEEK_HOLE`` decides.
    """
    if not stat.S_ISREG(info.st_mode) or not _few_blocks(info):
        return False
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
        if (opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev):
            return None
        return _has_hole(fd, info.st_size)
    except OSError:
        return None
    finally:
        os.close(fd)


def _node(rel: str, info: os.stat_result, dir_fd: int, name: str) -> Node:
    return Node(
        rel=rel,
        kind=kind_of(info.st_mode),
        ino=info.st_ino,
        dev=info.st_dev,
        nlink=info.st_nlink,
        ctime_ns=info.st_ctime_ns,
        mtime_ns=info.st_mtime_ns,
        size=info.st_size,
        uid=info.st_uid,
        gid=info.st_gid,
        user_xattrs=_user_xattrs(dir_fd, name),
        sparse=_sparse(dir_fd, name, info),
    )


def check_name(name: str) -> str:
    """Return ``name`` if it is one plain directory entry name; raise ``ValueError``."""
    if name in ("", ".", "..") or "/" in name or "\0" in name:
        raise ValueError(f"not a plain entry name: {name!r}")
    return name


def check_entry_name(name: str) -> str:
    """Return ``name`` if it can be claimed: plain, and not already a claim."""
    check_name(name)
    if name.startswith(CLAIM_PREFIX):
        raise ValueError(f"{name!r} is already a claimed name")
    return name


def open_dir(path: Path) -> int:
    """Open a directory ``O_NOFOLLOW``; the caller closes the descriptor."""
    return os.open(path, _DIR_FLAGS)


def open_child_dir(parent_fd: int, name: str, expected: os.stat_result) -> int:
    """Open directory ``name`` under ``parent_fd`` and check it is the inode ``expected`` saw."""
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise WalkRefused(f"cannot open directory {name!r}: {exc}") from exc
    info = os.fstat(fd)
    if (info.st_ino, info.st_dev) != (expected.st_ino, expected.st_dev):
        os.close(fd)
        raise WalkRefused(f"directory {name!r} changed while it was walked")
    return fd


def bounded_names(dir_fd: int, limit: int) -> list[str]:
    """List a directory through a fresh descriptor, refusing more than ``limit`` names."""
    try:
        fresh = os.open(".", _DIR_FLAGS, dir_fd=dir_fd)
    except OSError as exc:
        raise WalkRefused(f"cannot reopen a directory: {exc}") from exc
    names: list[str] = []
    try:
        with os.scandir(fresh) as listing:
            for item in listing:
                names.append(item.name)
                if len(names) > limit:
                    raise WalkRefused(f"more than {limit} names in one directory (inode cap)")
    except OSError as exc:
        raise WalkRefused(f"cannot list a directory: {exc}") from exc
    finally:
        os.close(fresh)
    return sorted(names)


def walk_tree(
    parent_fd: int, name: str, *, max_inodes: int, max_depth: int = DEFAULT_MAX_DEPTH
) -> TreeListing:
    """Walk entry ``name`` under ``parent_fd`` without following any link; refuse on any gap."""
    check_name(name)
    try:
        top = os.lstat(name, dir_fd=parent_fd)
    except OSError as exc:
        raise WalkRefused(f"cannot lstat {name!r}: {exc}") from exc
    if top.st_dev != os.fstat(parent_fd).st_dev:
        # The entry is itself a mount point: DESIGN section 5.3 gives it no action.
        raise WalkRefused(f"{name!r} is on a second device (a mount point)")
    nodes = [_node("", top, parent_fd, name)]
    if not stat.S_ISDIR(top.st_mode):
        return TreeListing(tuple(nodes))
    stack: list[tuple[int, str, Iterator[str]]] = []
    try:
        root_fd = open_child_dir(parent_fd, name, top)
        stack.append((root_fd, "", iter(bounded_names(root_fd, max_inodes))))
        while stack:
            fd, rel, names = stack[-1]
            child = next(names, None)
            if child is None:
                os.close(fd)
                stack.pop()
                continue
            child_rel = f"{rel}/{child}" if rel else child
            try:
                info = os.lstat(child, dir_fd=fd)
            except OSError as exc:
                raise WalkRefused(f"cannot lstat {child_rel!r}: {exc}") from exc
            if len(nodes) >= max_inodes:
                raise WalkRefused(f"more than {max_inodes} inodes (inode cap)")
            nodes.append(_node(child_rel, info, fd, child))
            if not stat.S_ISDIR(info.st_mode):
                continue
            if info.st_dev != top.st_dev:
                raise WalkRefused(f"{child_rel!r} is on a second device")
            if len(stack) >= max_depth:
                raise WalkRefused(f"{child_rel!r} is deeper than {max_depth} (depth cap)")
            child_fd = open_child_dir(fd, child, info)
            # On the stack before listing, so a refused listing still closes it.
            stack.append((child_fd, child_rel, iter(())))
            stack[-1] = (child_fd, child_rel, iter(bounded_names(child_fd, max_inodes)))
    finally:
        for fd, _rel, _names in stack:
            os.close(fd)
    return TreeListing(tuple(nodes))


def fingerprint_of(listing: TreeListing) -> Fingerprint:
    """Reduce a listing to its fingerprint; the root's own ctime is left out."""
    root = listing.root
    return Fingerprint(
        count=len(listing.nodes),
        newest_ctime_ns=max((n.ctime_ns for n in listing.nodes[1:]), default=0),
        root_kind=root.kind,
        root_ino=root.ino,
        root_dev=root.dev,
        root_mtime_ns=root.mtime_ns,
        root_size=root.size,
    )


def fingerprint_at(
    parent_fd: int, name: str, *, max_inodes: int, max_depth: int = DEFAULT_MAX_DEPTH
) -> Fingerprint:
    """Walk ``name`` and return its fingerprint."""
    return fingerprint_of(walk_tree(parent_fd, name, max_inodes=max_inodes, max_depth=max_depth))


def rename_noreplace(dir_fd: int, src: str, dst: str) -> None:
    """Rename ``src`` to ``dst`` in ``dir_fd``, failing (``EEXIST``) if ``dst`` exists."""
    if _RENAMEAT2 is None:
        raise ClaimRefused("no-replace rename (renameat2) is unavailable; nothing is claimed")
    result = _RENAMEAT2(dir_fd, os.fsencode(src), dir_fd, os.fsencode(dst), _RENAME_NOREPLACE)
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), src)


def rename_noreplace_between(src_dir_fd: int, src: str, dst_dir_fd: int, dst: str) -> None:
    """Move plain name ``src`` of ``src_dir_fd`` to ``dst`` of ``dst_dir_fd``, never replacing.

    Fails with ``EEXIST`` if ``dst`` exists (a dangling link included), ``EXDEV``
    across devices; raises ``ValueError`` for a name that is not one plain entry.
    """
    check_name(src)
    check_name(dst)
    if _RENAMEAT2 is None:
        raise ClaimRefused("no-replace rename (renameat2) is unavailable; nothing is moved")
    result = _RENAMEAT2(
        src_dir_fd, os.fsencode(src), dst_dir_fd, os.fsencode(dst), _RENAME_NOREPLACE
    )
    if result != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), src)


class Claimed:
    """A held claim: the entry now lives at ``claimed_name`` under ``parent_fd``."""

    def __init__(
        self, parent_fd: int, name: str, fingerprint: Fingerprint, claimed_at_ns: int
    ) -> None:
        self.parent_fd = parent_fd
        self.name = name
        self.claimed_name = CLAIM_PREFIX + name
        self.fingerprint = fingerprint
        self.claimed_at_ns = claimed_at_ns

    def close(self) -> None:
        """Close the claim's own parent descriptor."""
        if self.parent_fd >= 0:
            os.close(self.parent_fd)
            self.parent_fd = -1


@dataclass(frozen=True)
class RenamedBack:
    """The entry is back under its own name; ``reason`` says why (it is STUCK or LIVE)."""

    name: str
    reason: str
    claimed_at_ns: int


def claim(
    parent_fd: int,
    name: str,
    expected: Fingerprint,
    *,
    max_inodes: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    liveness_ok: Callable[[], bool] | None = None,
    clock: Callable[[], int] = time.time_ns,
) -> Claimed | RenamedBack:
    """Claim ``name`` and re-check it; return the claim, or the reason it was renamed back."""
    check_entry_name(name)
    try:
        rename_noreplace(parent_fd, name, CLAIM_PREFIX + name)
    except OSError as exc:
        raise ClaimRefused(f"cannot claim {name!r}: {exc}") from exc
    handle = Claimed(os.dup(parent_fd), name, expected, clock())
    try:
        actual = fingerprint_at(
            handle.parent_fd, handle.claimed_name, max_inodes=max_inodes, max_depth=max_depth
        )
    except (WalkRefused, OSError) as exc:
        # An I/O error is a refusal too: the claim is never left held by an escaping error.
        return release(handle, f"the claimed entry could not be walked: {exc}")
    if actual != expected:
        return release(handle, "fingerprint changed since classification")
    if liveness_ok is not None:
        try:
            live_ok = liveness_ok()
        except Exception as exc:
            return release(handle, f"liveness check failed: {exc!r}")
        if not live_ok:
            return release(handle, "entry is live")
    return handle


def release(handle: Claimed, reason: str) -> RenamedBack:
    """Rename a claimed entry back under its own name, closing the claim.

    Raises :class:`ClaimStuck` when the name has been taken again meanwhile: the
    entry then stays whole under its claimed name for the next sweep to resolve.
    """
    try:
        rename_noreplace(handle.parent_fd, handle.claimed_name, handle.name)
    except OSError as exc:
        raise ClaimStuck(
            f"cannot rename {handle.claimed_name!r} back to {handle.name!r} ({reason}): {exc}"
        ) from exc
    finally:
        handle.close()
    return RenamedBack(name=handle.name, reason=reason, claimed_at_ns=handle.claimed_at_ns)
