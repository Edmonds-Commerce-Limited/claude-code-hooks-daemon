"""Linear path containment (Plan 00466 N106).

From Python 3.12, ``PurePath.is_relative_to`` and ``PurePath.relative_to`` test
containment as ``other in self.parents``: every parent they visit is a new path
object whose string is built from all of its segments, so a check on a path
``d`` segments deep costs O(d^2). CI on 3.12 and 3.13 measured three PreToolUse
handlers growing 24x-29x for an 8x deeper ``Write`` path, while 3.11 grows 8x.

``utils.path_containment`` answers the same questions from ``parts`` once. The
growth tests below count the segments it touches instead of timing it, so they
are deterministic on any host and on every Python version.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest

from claude_code_hooks_daemon.utils.path_containment import (
    path_is_relative_to,
    path_relative_to,
)
from tests.scaling import SUPERLINEAR_RATIO, counted_ratio

_DEPTH = 500


class _CountingPath(PurePosixPath):
    """A posix path that tallies every segment read through ``parts`` or ``str``.

    Both are how containment can look at a path: ``parts`` directly, and
    ``str`` through equality, which is how the stdlib compares each parent.
    """

    touched = 0

    @property
    def parts(self) -> tuple[str, ...]:
        found = super().parts
        _CountingPath.touched += len(found)
        return found

    def __str__(self) -> str:
        text = super().__str__()
        _CountingPath.touched += text.count("/") + 1
        return text


def _deep(depth: int) -> _CountingPath:
    return _CountingPath("/repo/src/" + "pkg/" * depth + "module.py")


def _segments_touched(check: Callable[[PurePath, PurePath], object], depth: int) -> int:
    path = _deep(depth)
    root = _CountingPath("/repo")
    _CountingPath.touched = 0
    check(path, root)
    return _CountingPath.touched


def _walk_every_parent(path: PurePath, root: PurePath) -> bool:
    """A containment test that visits every parent, as the stdlib's does."""
    return any(str(parent) == str(root) for parent in path.parents)


class TestContainmentGrowsLinearly:
    """Segments touched at depth N vs 8N: linear is about 8x, quadratic about 64x."""

    def test_is_relative_to_is_linear(self) -> None:
        ratio = counted_ratio(lambda d: _segments_touched(path_is_relative_to, d), _DEPTH)
        assert ratio <= SUPERLINEAR_RATIO

    def test_relative_to_is_linear(self) -> None:
        ratio = counted_ratio(lambda d: _segments_touched(path_relative_to, d), _DEPTH)
        assert ratio <= SUPERLINEAR_RATIO

    def test_the_count_sees_a_parent_walk_as_quadratic(self) -> None:
        """Without this, a count that never moves would pass the two tests above."""
        ratio = counted_ratio(lambda d: _segments_touched(_walk_every_parent, d), _DEPTH)
        assert ratio > SUPERLINEAR_RATIO

    def test_the_count_is_not_vacuous_for_the_helper(self) -> None:
        assert _segments_touched(path_is_relative_to, _DEPTH) >= _DEPTH


# (path, other) pairs whose answers must match the stdlib exactly.
_CASES: list[tuple[PurePath, PurePath]] = [
    (PurePosixPath("/a/b/c"), PurePosixPath("/a")),
    (PurePosixPath("/a/b/c"), PurePosixPath("/a/b/c")),
    (PurePosixPath("/a/b"), PurePosixPath("/a/b/c")),
    (PurePosixPath("/a/bc"), PurePosixPath("/a/b")),
    (PurePosixPath("/a/b"), PurePosixPath("/")),
    (PurePosixPath("/"), PurePosixPath("/")),
    (PurePosixPath("/a/b"), PurePosixPath("a")),
    (PurePosixPath("a/b"), PurePosixPath("/a")),
    (PurePosixPath("a/b"), PurePosixPath("a")),
    (PurePosixPath("a/b"), PurePosixPath(".")),
    (PurePosixPath("."), PurePosixPath(".")),
    (PurePosixPath("/a"), PurePosixPath(".")),
    (PurePosixPath("/x/y"), PurePosixPath("/a")),
    (PureWindowsPath("C:/Users/Me/x"), PureWindowsPath("c:/users")),
    (PureWindowsPath("C:/Users/x"), PureWindowsPath("D:/Users")),
    (PureWindowsPath("C:/Users/x"), PureWindowsPath("C:Users")),
]


class TestMatchesTheStdlib:
    """A drop-in replacement: same answers, same result type, same error."""

    @pytest.mark.parametrize(("path", "other"), _CASES, ids=str)
    def test_is_relative_to(self, path: PurePath, other: PurePath) -> None:
        assert path_is_relative_to(path, other) is path.is_relative_to(other)

    @pytest.mark.parametrize(("path", "other"), _CASES, ids=str)
    def test_relative_to(self, path: PurePath, other: PurePath) -> None:
        if path.is_relative_to(other):
            result = path_relative_to(path, other)
            assert result == path.relative_to(other)
            assert type(result) is type(path)
        else:
            with pytest.raises(ValueError, match="is not in the subpath of"):
                path_relative_to(path, other)

    def test_accepts_a_string_other(self) -> None:
        assert path_is_relative_to(Path("/a/b"), "/a")
        assert path_relative_to(Path("/a/b"), "/a") == Path("b")

    def test_keeps_the_concrete_path_type(self) -> None:
        assert type(path_relative_to(Path("/a/b"), Path("/a"))) is type(Path("/a"))
