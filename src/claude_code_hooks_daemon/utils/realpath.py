"""``os.path.realpath`` without one ``lstat`` per component of a missing tail.

``os.path.realpath`` walks a path one component at a time, calling ``lstat``
on each even after one is missing, and re-copies the unwalked rest of the
string at every step. Guards resolve every Write/Edit ``file_path``, and a
hostile 90 KB-deep path made each resolution cost a tenth of a second --
seconds across the chain (Plan 00466 N40 review 2 nit 4).

This is the same walk (``posixpath._joinrealpath``), step for step, with two
changes that cannot alter its answer:

- The path is split once, not re-partitioned per component.
- Once ``lstat`` of the walked path fails with ENOENT or ENOTDIR, every
  longer path below it fails the same way, so each further name is appended
  without calling ``lstat``. A ``..`` that climbs back out of the missing
  part resumes the ordinary walk.

An earlier version binary-searched for the longest ``lstat``-able prefix of
the path AS SPELLED. That is not what ``os.path.realpath`` walks: it drops
``.`` and empty components and resolves ``..`` lexically. So a spelling past
PATH_MAX, or a link whose target holds ``missing/..``, resolved differently,
and a Write through an in-project link to /tmp got past project_containment
(Plan 00466 N24 review 3 B1). ``tests/unit/utils/test_realpath.py`` holds the
two functions equal over generated adversarial paths.
"""

from __future__ import annotations

import errno
import os
import posixpath
import stat
from pathlib import Path
from typing import Final

# POSIX separator, spelled out rather than taken from pathlib: the walk must
# split and join the path EXACTLY as posixpath does, which Path.parts would
# normalise. The daemon runs on Linux and macOS only.
_SEP: Final = "/"
_NUL: Final = "\0"

#: lstat failures after which no longer path below can exist.
_NOTHING_BELOW: Final = frozenset({errno.ENOENT, errno.ENOTDIR})


def _join_missing(path: str, pending: list[str]) -> str:
    """``posixpath.join(path, *pending)``, in one pass rather than one per name."""
    if not pending:
        return path
    if not path or path.endswith(_SEP):
        return path + _SEP.join(pending)
    return path + _SEP + _SEP.join(pending)


def _join_realpath(path: str, rest: str, seen: dict[str, str | None]) -> tuple[str, bool]:
    """``posixpath._joinrealpath(path, rest, False, seen)``, see the module docstring."""
    if rest.startswith(_SEP):
        rest = rest[1:]
        path = _SEP
    names = rest.split(_SEP) if rest else []
    # While True, `path` is known not to exist and `pending` holds the names
    # walked below it; os.path.realpath would lstat each and fail.
    missing = False
    pending: list[str] = []
    for index, name in enumerate(names):
        if not name or name == os.curdir:
            continue
        if name == os.pardir:
            if pending:
                pending.pop()
                continue
            missing = False
            if path:
                path, name = posixpath.split(path)
                if name == os.pardir:
                    path = posixpath.join(path, os.pardir, os.pardir)
            else:
                path = os.pardir
            continue
        if missing:
            if _NUL in name:
                # The lstat skipped here is what raises for os.path.realpath.
                raise ValueError("embedded null byte")
            pending.append(name)
            continue
        newpath = posixpath.join(path, name)
        try:
            is_link = stat.S_ISLNK(os.lstat(newpath).st_mode)
        except OSError as exc:
            is_link = False
            missing = exc.errno in _NOTHING_BELOW
        if not is_link:
            path = newpath
            continue
        remainder = _SEP.join(names[index + 1 :])
        if newpath in seen:
            cached = seen[newpath]
            if cached is not None:
                path = cached
                continue
            # A symlink loop: os.path.realpath returns the rest unresolved.
            return posixpath.join(newpath, remainder), False
        seen[newpath] = None
        # Path drops only `.` and empty components from the target, which
        # the walk skips anyway.
        target = str(Path(newpath).readlink())
        path, resolved = _join_realpath(path, target, seen)
        if not resolved:
            return posixpath.join(path, remainder), False
        seen[newpath] = path
    return _join_missing(path, pending), True


def realpath(path: str | os.PathLike[str]) -> str:
    """Return exactly ``os.path.realpath(path)``, with no ``lstat`` below a missing component.

    Raises:
        ValueError: For a path ``os.path.realpath`` itself rejects (a NUL byte).
    """
    text = os.fspath(path)
    resolved, _complete = _join_realpath("", text, {})
    return posixpath.abspath(resolved)
