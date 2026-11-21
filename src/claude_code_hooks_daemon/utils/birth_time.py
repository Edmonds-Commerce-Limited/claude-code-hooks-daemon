"""A file's birth time, read with ``statx(2)`` through libc.

Python's ``os.stat`` carries no birth time on Linux, so ``statx`` is called
through ctypes. A stamp is returned only when the kernel says the birth time is
valid (``STATX_BTIME`` set in the returned mask); otherwise the answer is None
and the caller must treat identity as unproven. Links are never followed.

The device and inode statx reports are returned beside the birth, so a caller
can check the stamp describes the inode it ``lstat``-ed.
"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from dataclasses import dataclass

_AT_SYMLINK_NOFOLLOW = 0x100
_STATX_INO = 0x100
_STATX_BTIME = 0x800


class _Timestamp(ctypes.Structure):
    _fields_ = (
        ("tv_sec", ctypes.c_int64),
        ("tv_nsec", ctypes.c_uint32),
        ("reserved", ctypes.c_int32),
    )


class _Statx(ctypes.Structure):
    """``struct statx`` from ``<linux/stat.h>``; 256 bytes, padded at the end."""

    _fields_ = (
        ("stx_mask", ctypes.c_uint32),
        ("stx_blksize", ctypes.c_uint32),
        ("stx_attributes", ctypes.c_uint64),
        ("stx_nlink", ctypes.c_uint32),
        ("stx_uid", ctypes.c_uint32),
        ("stx_gid", ctypes.c_uint32),
        ("stx_mode", ctypes.c_uint16),
        ("spare0", ctypes.c_uint16),
        ("stx_ino", ctypes.c_uint64),
        ("stx_size", ctypes.c_uint64),
        ("stx_blocks", ctypes.c_uint64),
        ("stx_attributes_mask", ctypes.c_uint64),
        ("stx_atime", _Timestamp),
        ("stx_btime", _Timestamp),
        ("stx_ctime", _Timestamp),
        ("stx_mtime", _Timestamp),
        ("stx_rdev_major", ctypes.c_uint32),
        ("stx_rdev_minor", ctypes.c_uint32),
        ("stx_dev_major", ctypes.c_uint32),
        ("stx_dev_minor", ctypes.c_uint32),
        ("spare2", ctypes.c_uint64 * 14),
    )


def _load_statx() -> Callable[..., int] | None:
    libc = ctypes.CDLL(None, use_errno=True)
    func = getattr(libc, "statx", None)
    if func is None:
        return None
    func.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_Statx),
    ]
    func.restype = ctypes.c_int
    result: Callable[..., int] = func
    return result


_STATX: Callable[..., int] | None = _load_statx()


@dataclass(frozen=True)
class BirthStamp:
    """The birth time (ns since the epoch) of one inode, with the inode it describes."""

    birth_ns: int
    ino: int
    dev: int


def birth_stamp(dir_fd: int, name: str) -> BirthStamp | None:
    """``name`` under ``dir_fd``'s birth stamp, not following a link; None when unknown.

    Raises ``OSError`` (``FileNotFoundError`` included) when statx itself fails.
    """
    func = _STATX
    if func is None:
        return None
    buf = _Statx()
    rc = func(
        dir_fd,
        os.fsencode(name),
        _AT_SYMLINK_NOFOLLOW,
        _STATX_INO | _STATX_BTIME,
        ctypes.byref(buf),
    )
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), name)
    if not buf.stx_mask & _STATX_BTIME or not buf.stx_mask & _STATX_INO:
        return None
    birth_ns = buf.stx_btime.tv_sec * 1_000_000_000 + buf.stx_btime.tv_nsec
    if birth_ns <= 0:
        return None
    return BirthStamp(
        birth_ns=birth_ns,
        ino=buf.stx_ino,
        dev=os.makedev(buf.stx_dev_major, buf.stx_dev_minor),
    )


__all__ = ["BirthStamp", "birth_stamp"]
