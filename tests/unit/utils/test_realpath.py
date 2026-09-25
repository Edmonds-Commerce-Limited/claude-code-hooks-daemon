"""Tests for utils.realpath (Plan 00466 N40 review 2 nit 4).

``realpath`` must answer exactly what ``os.path.realpath`` answers, while doing
O(log depth) filesystem calls rather than one per component: every guard that
resolves a Write's ``file_path`` paid a full component walk, and a 90 KB-deep
path cost seconds across the chain.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.utils.realpath import realpath
from tests.scaling import SIZE_FACTOR, SUPERLINEAR_RATIO, scaling_ratio


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small tree with the symlink shapes realpath has to get right."""
    (tmp_path / "real" / "inner").mkdir(parents=True)
    (tmp_path / "real" / "inner" / "file.txt").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "real")
    (tmp_path / "dangling").symlink_to(tmp_path / "nowhere" / "deeper")
    (tmp_path / "loop_a").symlink_to(tmp_path / "loop_b")
    (tmp_path / "loop_b").symlink_to(tmp_path / "loop_a")
    (tmp_path / "real" / "up").symlink_to("..")
    return tmp_path


_RELATIVE_SHAPES = [
    "real/inner/file.txt",
    "link/inner/file.txt",
    "link/inner/missing/more/file.txt",
    "link/missing/../inner/file.txt",
    "link/missing/../../escape",
    "missing/../real/inner",
    "real/inner/../../link/inner",
    "dangling",
    "dangling/child/../sibling",
    "loop_a/child",
    "real/up/real/up/link",
    "real//inner/./file.txt",
    "real/inner/",
    "missing/",
    "missing/child/..",
    "..",
    "../..",
    "",
]


@pytest.mark.parametrize("relative", _RELATIVE_SHAPES)
def test_matches_os_path_realpath_for_absolute_paths(tree: Path, relative: str) -> None:
    path = str(tree / relative) if relative else str(tree)
    assert realpath(path) == os.path.realpath(path)


@pytest.mark.parametrize("relative", _RELATIVE_SHAPES)
def test_matches_os_path_realpath_for_relative_paths(
    tree: Path, relative: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tree)
    assert realpath(relative) == os.path.realpath(relative)


def test_matches_os_path_realpath_for_every_short_component_sequence(tree: Path) -> None:
    """Exhaustive over every sequence of up to four components drawn from the
    shapes above -- existing, missing, symlinked, dangling, looping, `..`,
    `.` and empty -- so no ordering of them can diverge unnoticed."""
    names = ["real", "link", "inner", "missing", "..", ".", "dangling", "loop_a", "up", ""]
    sequences: list[list[str]] = [[]]
    for _ in range(4):
        sequences = [*sequences, *([*seq, name] for seq in sequences for name in names)]
    mismatches = []
    for sequence in {tuple(seq) for seq in sequences}:
        # Joined as spelled: Path would normalise away the `.` and empty parts.
        path = "/".join([str(tree), *sequence])
        if realpath(path) != os.path.realpath(path):
            mismatches.append(path)
    assert not mismatches


@pytest.mark.parametrize("raw", ["//", "//tmp", "///tmp/../tmp", "/", "/..", "/./tmp/"])
def test_matches_os_path_realpath_for_raw_root_spellings(raw: str) -> None:
    assert realpath(raw) == os.path.realpath(raw)


def test_accepts_a_path_object(tree: Path) -> None:
    assert realpath(tree / "link" / "inner") == os.path.realpath(tree / "link" / "inner")


def test_a_nul_byte_raises_like_os_path_realpath() -> None:
    with pytest.raises(ValueError):
        os.path.realpath("/a\0b")
    with pytest.raises(ValueError):
        realpath("/a\0b")


def test_a_deep_missing_path_costs_logarithmically_many_lstat_calls(tree: Path) -> None:
    """The point of the helper: not one lstat per component. A deterministic
    count: a binary search over the depth, plus resolving the few components
    that exist."""
    depth = 4_096
    deep = str(tree / "real" / ("pkg/" * depth) / "module.py")
    expected = os.path.realpath(deep)
    with patch("claude_code_hooks_daemon.utils.realpath.os.lstat", wraps=os.lstat) as lstat:
        assert realpath(deep) == expected
    existing_components = len((tree / "real").parts)
    assert lstat.call_count <= existing_components + depth.bit_length() + 1


def test_cost_grows_linearly_with_depth(tree: Path) -> None:
    def deep(segments: int) -> str:
        return str(tree / "real" / ("pkg/" * segments) / "module.py")

    segments = 2_812
    ratio = scaling_ratio(lambda size: realpath(deep(size)), segments, deep(SIZE_FACTOR * segments))
    assert ratio <= SUPERLINEAR_RATIO
