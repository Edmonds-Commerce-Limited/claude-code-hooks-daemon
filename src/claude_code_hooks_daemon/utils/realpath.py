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

import os


def realpath(path: str | os.PathLike[str]) -> str:
    """Return exactly ``os.path.realpath(path)``.

    Raises:
        ValueError: For a path ``os.path.realpath`` itself rejects (a NUL byte).
    """
    return os.path.realpath(path, strict=False)
