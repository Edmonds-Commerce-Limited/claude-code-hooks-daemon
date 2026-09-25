"""``os.path.realpath`` without one ``lstat`` per component of a missing tail.

``os.path.realpath`` walks a path one component at a time, calling ``lstat``
on each even after one is missing. Guards resolve every Write/Edit
``file_path``, and a hostile 90 KB-deep path made each resolution cost a
tenth of a second -- seconds across the chain (Plan 00466 N40 review 2 nit 4).

Past the first component that does not exist, nothing further can exist --
unless a ``..`` climbs back out, which this leaves to ``os.path.realpath``
itself. So without a ``..`` in it, the missing tail is appended as it is
spelled. And whether a prefix can be ``lstat``-ed is monotonic in its length
(the kernel has to walk every earlier component to reach it), so the longest
such prefix is found by binary search. The answer is exactly
``os.path.realpath``'s: that function resolves the prefix.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

# POSIX separator, spelled out rather than taken from pathlib: this module
# must split and join the path EXACTLY as spelled (`//`, `.` and a trailing
# `/` included), which is what os.path.realpath sees, while Path.parts
# normalises those away. The daemon runs on Linux and macOS only.
_SEP: Final = "/"


def _can_lstat(path: str) -> bool:
    try:
        os.lstat(path)
    except OSError:
        return False
    return True


def realpath(path: str | os.PathLike[str]) -> str:
    """Return ``os.path.realpath(path)``, in O(log depth) ``lstat`` calls.

    Raises:
        ValueError: For a path ``os.path.realpath`` itself rejects (a NUL byte).
    """
    text = os.fspath(path)
    absolute = text.startswith(_SEP)
    # The empty prefix is the root (absolute) or the working directory
    # (relative); both always exist. A relative prefix stays relative, so
    # os.path.realpath sees exactly the spelling it would have been given.
    start = _SEP if absolute else os.curdir
    parts = text.split(_SEP)
    # Find the largest k such that the first k parts can be lstat-ed. For an
    # absolute path parts[0] is "", the root, so k starts at 1.
    known, unknown = (1 if absolute else 0), len(parts)
    while known < unknown:
        middle = (known + unknown + 1) // 2
        if _can_lstat(_SEP.join(parts[:middle]) or start):
            known = middle
        else:
            unknown = middle - 1
    tail = parts[known:]
    if os.pardir in tail:
        # A `..` can climb from the missing tail back into directories that
        # exist, where a symlink resolves again; os.path.realpath's own walk
        # is the only exact answer then. Never slower than before.
        return os.path.realpath(text)
    resolved = os.path.realpath(_SEP.join(parts[:known]) or start)
    if tail and Path(resolved).is_symlink():
        # Still a link after resolving: a symlink loop, where
        # os.path.realpath abandons the walk in its own particular way.
        return os.path.realpath(text)
    components = [name for name in resolved.split(_SEP) if name]
    components.extend(name for name in tail if name not in ("", os.curdir))
    return _SEP + _SEP.join(components)
