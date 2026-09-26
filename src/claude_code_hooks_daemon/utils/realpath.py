"""A thin, version-safe wrapper around ``os.path.realpath``.

Plan 00466 N24 review 4 R4-B1: an earlier version of this module reimplemented
``posixpath._joinrealpath`` by hand to avoid one ``lstat`` per component of a
missing tail (Plan 00466 N40 review 2 nit 4). That hand-written walk matched
CPython 3.11's algorithm, but 3.13 rewrote ``_joinrealpath``'s symlink-loop
handling, and the two diverged: a symlink loop followed by ``..`` resolved to
a different answer than ``os.path.realpath`` gives on 3.13, and a Write
through it got past ``project_containment``. Every guard here exists to
answer "where does this path really land", so it must equal the interpreter's
own answer on every supported Python version -- not just the one this module
happened to be tested against. Delegating removes the divergence outright
rather than chasing each new CPython edge case by hand.
"""

from __future__ import annotations

import errno
import os


def realpath(path: str | os.PathLike[str]) -> str:
    """Return exactly ``os.path.realpath(path)``.

    Raises:
        ValueError: For a path ``os.path.realpath`` itself rejects (a NUL byte).
    """
    return os.path.realpath(path, strict=False)


def has_symlink_loop(path: str | os.PathLike[str]) -> bool:
    """True when resolving ``path`` passes through a symlink loop.

    Plan 00466 N24 review 4 (team-lead follow-up on R4-B1): once a loop is
    hit, ``os.path.realpath``'s OWN answer for the rest of the path is
    version-dependent -- 3.11 gives up and appends the remainder unresolved,
    3.13 backs out of the loop and keeps resolving -- so ``realpath()``
    above, which now equals ``os.path.realpath`` exactly, cannot itself give
    a version-INDEPENDENT containment answer for this shape. A security
    check that must agree on every Python version asks this directly
    instead: ``strict=True`` resolution fails with ``ELOOP`` for the
    existing prefix precisely when a loop is on the path, distinct from a
    plain missing component (``ENOENT``/``ENOTDIR``), which is the ordinary,
    harmless case of a Write to a path that does not exist yet.
    """
    try:
        os.path.realpath(path, strict=True)
    except OSError as exc:
        return exc.errno == errno.ELOOP
    except ValueError:
        # A NUL byte: os.path.realpath itself rejects it, so it cannot BE a
        # symlink loop -- realpath() above raises the same ValueError for
        # any caller that goes on to actually resolve the path.
        return False
    return False
