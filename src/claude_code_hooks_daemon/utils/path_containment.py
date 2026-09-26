"""Path containment in time linear in path depth.

From Python 3.12, ``PurePath.is_relative_to`` and ``PurePath.relative_to`` test
containment as ``other in self.parents``. Each parent visited is a new path
whose string is built from every segment above it, so one check on a path
``d`` segments deep costs O(d^2). A hook's ``file_path`` is caller-supplied and
unbounded: a 32 KB path made three PreToolUse handlers grow 24x-29x for 8x
the depth (Plan 00466 N106). ``in path.parents`` has the same cost.

These functions answer the same questions from ``parts``, read once. Use them
instead of the stdlib methods anywhere in the daemon; the
``pathlib-quadratic-containment`` semgrep rule enforces that.
"""

from __future__ import annotations

from pathlib import PurePath, PureWindowsPath
from typing import TypeVar

_P = TypeVar("_P", bound=PurePath)


def _comparable(path: PurePath, texts: tuple[str, ...]) -> tuple[str, ...]:
    """``texts`` case-folded where ``path``'s flavour is case-insensitive."""
    if isinstance(path, PureWindowsPath):
        return tuple(text.lower() for text in texts)
    return texts


def _prefix_length(path: PurePath, other: PurePath | str) -> int | None:
    """How many of ``path``'s parts are ``other``, or None when it is not an ancestor."""
    base = type(path)(other)
    # parts carry the anchor only when there is one, so relative "." (no parts)
    # would otherwise prefix every absolute path.
    if _comparable(path, (path.anchor,)) != _comparable(base, (base.anchor,)):
        return None
    wanted = _comparable(base, base.parts)
    have = _comparable(path, path.parts)
    if have[: len(wanted)] != wanted:
        return None
    return len(wanted)


def path_is_relative_to(path: PurePath, other: PurePath | str) -> bool:
    """Whether ``path`` is ``other`` or lies beneath it, lexically.

    Same answer as ``path.is_relative_to(other)``; no filesystem access.
    """
    return _prefix_length(path, other) is not None


def path_relative_to(path: _P, other: PurePath | str) -> _P:
    """``path`` expressed relative to ``other``, as ``path.relative_to(other)``.

    Raises:
        ValueError: ``path`` is not ``other`` or beneath it, with the stdlib's
            message.
    """
    length = _prefix_length(path, other)
    if length is None:
        raise ValueError(f"{str(path)!r} is not in the subpath of {str(other)!r}")
    return type(path)(*path.parts[length:])
