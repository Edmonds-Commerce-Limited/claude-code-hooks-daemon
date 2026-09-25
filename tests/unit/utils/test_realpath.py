"""Tests for utils.realpath (Plan 00466 N40 review 2 nit 4).

``realpath`` must answer exactly what ``os.path.realpath`` answers, while doing
O(log depth) filesystem calls rather than one per component: every guard that
resolves a Write's ``file_path`` paid a full component walk, and a 90 KB-deep
path cost seconds across the chain.
"""

from __future__ import annotations

import os
import random
from collections.abc import Callable
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


#: Plan 00466 N24 review 3 B1: each atom is one path component. They cover
#: dirs, a file, relative and absolute links, a dangling link, loops, a chain,
#: link targets holding `..` and `missing/..`, a link to `.` and to `/`, and
#: a component too long for NAME_MAX.
_ATOMS = [
    *("d1", "d2", "d3", "e1", "f1", "f2", "l_d1", "l_abs_d2", "l_f1", "l_dangling"),
    *("l_loop_a", "l_loop_b", "l_self", "l_up_e1", "l_parent", "l_chain"),
    *("l_dotdot_target", "l_missing_dotdot", "l_missing_dotdot_up", "l_dot", "l_root"),
    *("missing", "zz", "..", ".", "", "x" * 300),
]
_DIFFERENTIAL_CASES = 24_000
_DIFFERENTIAL_SEED = 466_24


@pytest.fixture
def adversarial_tree(tmp_path: Path) -> Path:
    """Every symlink shape review 3 found the fast path getting wrong."""
    (tmp_path / "d1" / "d2" / "d3").mkdir(parents=True)
    (tmp_path / "e1").mkdir()
    (tmp_path / "f1").write_text("")
    (tmp_path / "d1" / "f2").write_text("")
    links = {
        "l_d1": "d1",
        "l_abs_d2": str(tmp_path / "d1" / "d2"),
        "l_f1": "f1",
        "l_dangling": "missing/x",
        "l_loop_a": "l_loop_b",
        "l_loop_b": "l_loop_a",
        "l_self": "l_self",
        "d1/l_up_e1": "../e1",
        "d1/d2/l_parent": "..",
        "l_chain": "l_d1/d2",
        "l_dotdot_target": "d1/../e1/../d1/d2/l_parent/f2",
        "l_missing_dotdot": "nope/../d1",
        "l_missing_dotdot_up": "nope/deeper/../../e1",
        "l_dot": ".",
        "l_root": "/",
    }
    for name, target in links.items():
        (tmp_path / name).symlink_to(target)
    return tmp_path


def _generated_path(rng: random.Random, base: Path) -> str:
    parts = [rng.choice(_ATOMS) for _ in range(rng.randint(0, 7))]
    if rng.random() < 0.04:
        # A spelling at or past PATH_MAX made of components realpath skips.
        parts = [rng.choice([".", ""])] * rng.choice([1_500, 2_100, 3_000, 4_200]) + parts
    path = "/".join(parts)
    anchor = rng.random()
    if anchor < 0.45:
        path = f"{base}/{path}"
    elif anchor < 0.5:
        path = f"/{path}"
    elif anchor < 0.55:
        path = f"//{path}"
    if rng.random() < 0.15:
        path += "/"
    return path


def _outcome(function: Callable[[str], str], path: str) -> tuple[str, str]:
    try:
        return ("ok", function(path))
    except (OSError, ValueError, RuntimeError) as exc:
        return ("raised", type(exc).__name__)


def test_matches_os_path_realpath_on_generated_adversarial_paths(
    adversarial_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan 00466 N24 review 3 B1: a differential test, not a list of shapes.

    The earlier exhaustive test could not reach two classes, and each let a
    Write through an in-project link to /tmp past project_containment: a
    spelling past PATH_MAX, and a link whose target holds `missing/..`.
    """
    monkeypatch.chdir(adversarial_tree)
    rng = random.Random(_DIFFERENTIAL_SEED)
    mismatches = []
    for _ in range(_DIFFERENTIAL_CASES):
        path = _generated_path(rng, adversarial_tree)
        expected = _outcome(os.path.realpath, path)
        if _outcome(realpath, path) != expected:
            mismatches.append(path[:200])
    assert not mismatches, f"{len(mismatches)} differ, e.g. {mismatches[:3]}"


@pytest.mark.parametrize(
    "spelled",
    [
        "/".join(["."] * 2_100) + "/l_d1/f2",
        "/".join([""] * 4_200) + "/l_d1/f2",
        "l_missing_dotdot/l_up_e1",
        "l_missing_dotdot_up/x",
    ],
)
def test_the_two_classes_review_3_found(adversarial_tree: Path, spelled: str) -> None:
    path = f"{adversarial_tree}/{spelled}"
    assert realpath(path) == os.path.realpath(path)


def test_a_nul_byte_after_a_missing_component_still_raises(tree: Path) -> None:
    path = f"{tree}/missing/deeper/a\0b"
    with pytest.raises(ValueError):
        os.path.realpath(path)
    with pytest.raises(ValueError):
        realpath(path)


def test_a_deep_missing_path_costs_logarithmically_many_lstat_calls(tree: Path) -> None:
    """The point of the helper: not one lstat per component. A deterministic
    count: one per component that exists, and one for the first that does
    not."""
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
