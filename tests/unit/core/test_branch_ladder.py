"""The branch pool warning ladder (Plan 00619): level function, base, throttle, wording.

The level is the share of a pool's block point in use: warn at 60, strong at 80
and very strong at 90 percent (thresholds rounded UP), block at the block point.
The open-work block point is ``wip.cap + wip.creation_grace``, because that is
where creation is actually denied; parked and merged pools block at their cap.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    BranchesConfig,
    BranchLadderConfig,
    BranchMergedConfig,
    BranchParkedConfig,
    BranchWipConfig,
)
from claude_code_hooks_daemon.core.branch_inventory import Pool
from claude_code_hooks_daemon.core.branch_ladder import (
    LadderLevel,
    LadderThrottle,
    ladder_level,
    pool_base,
    pool_pressures,
    pressure_lines,
)

DEFAULTS = BranchLadderConfig()
N, W, S, V, B = (
    LadderLevel.NONE,
    LadderLevel.WARN,
    LadderLevel.STRONG,
    LadderLevel.VERY_STRONG,
    LadderLevel.BLOCK,
)


class TestLevelFunction:
    @pytest.mark.parametrize(
        ("base", "expected"),
        [
            # base 1: every threshold collapses onto the block point.
            (1, [N, B, B]),
            # base 2: 60 percent rounds up to 2, so one branch is still quiet.
            (2, [N, N, B, B]),
            # base 3: 60 -> 2, 80 and 90 -> 3 (the block point): the top level wins.
            (3, [N, N, W, B, B]),
            # base 5: 60 -> 3, 80 -> 4, 90 -> 5 (block).
            (5, [N, N, N, W, S, B, B]),
            # base 10: 6, 8, 9; block at 10.
            (10, [N] * 6 + [W, W, S, V, B, B]),
            # base 12 (the default open pool: cap 10 plus grace 2): 8, 10, 11.
            (12, [N] * 8 + [W, W, S, V, B, B]),
            # base 20: 12, 16, 18.
            (20, [N] * 12 + [W] * 4 + [S] * 2 + [V, V, B, B]),
            # base 100: exactly 60, 80, 90.
            (100, [N] * 60 + [W] * 20 + [S] * 10 + [V] * 10 + [B, B]),
        ],
    )
    def test_table(self, base: int, expected: list[LadderLevel]) -> None:
        got = [ladder_level(count, base, DEFAULTS) for count in range(len(expected))]
        assert got == expected

    def test_zero_count_is_never_a_level(self) -> None:
        assert ladder_level(0, 1, DEFAULTS) is N

    def test_custom_thresholds(self) -> None:
        custom = BranchLadderConfig(warn=50, strong=70, very_strong=95)
        # base 20: 10, 14, 19
        got = [ladder_level(count, 20, custom) for count in (9, 10, 14, 18, 19, 20)]
        assert got == [N, W, S, S, V, B]

    def test_levels_are_ordered(self) -> None:
        assert N < W < S < V < B


class TestThresholdConfig:
    def test_defaults(self) -> None:
        assert (DEFAULTS.warn, DEFAULTS.strong, DEFAULTS.very_strong) == (60, 80, 90)

    @pytest.mark.parametrize(
        ("warn", "strong", "very_strong"),
        [(80, 80, 90), (90, 80, 70), (60, 80, 100), (0, 80, 90)],
    )
    def test_rejects_unordered_or_out_of_range(
        self, warn: int, strong: int, very_strong: int
    ) -> None:
        with pytest.raises(ValidationError):
            BranchLadderConfig(warn=warn, strong=strong, very_strong=very_strong)

    def test_every_pool_has_its_own_thresholds(self) -> None:
        config = BranchesConfig(
            wip=BranchWipConfig(ladder=BranchLadderConfig(warn=10, strong=20, very_strong=30)),
            parked=BranchParkedConfig(
                ladder=BranchLadderConfig(warn=40, strong=50, very_strong=60)
            ),
        )
        assert config.wip.ladder.warn == 10
        assert config.parked.ladder.warn == 40
        assert config.merged.ladder == DEFAULTS


class TestPoolBase:
    def test_open_base_is_the_block_point_not_the_nominal_cap(self) -> None:
        config = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2))
        assert pool_base(config, Pool.OPEN) == 12

    def test_open_base_with_no_grace_is_the_cap(self) -> None:
        config = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=0))
        assert pool_base(config, Pool.OPEN) == 10

    def test_other_pools_use_their_cap(self) -> None:
        config = BranchesConfig(
            wip=BranchWipConfig(cap=10, creation_grace=2),
            parked=BranchParkedConfig(cap=4),
            merged=BranchMergedConfig(),
        )
        assert pool_base(config, Pool.PARKED) == 4
        assert pool_base(config, Pool.MERGED) == 10


class TestThrottle:
    def test_warn_and_strong_show_once_per_session_pool_and_level(self) -> None:
        throttle = LadderThrottle()
        assert throttle.should_show("s1", Pool.OPEN, W) is True
        assert throttle.should_show("s1", Pool.OPEN, W) is False
        assert throttle.should_show("s1", Pool.OPEN, S) is True
        assert throttle.should_show("s1", Pool.OPEN, S) is False
        assert throttle.should_show("s1", Pool.PARKED, W) is True
        assert throttle.should_show("s2", Pool.OPEN, W) is True

    @pytest.mark.parametrize("level", [V, B])
    def test_very_strong_and_block_are_never_rate_limited(self, level: LadderLevel) -> None:
        throttle = LadderThrottle()
        assert all(throttle.should_show("s1", Pool.OPEN, level) for _ in range(50))

    def test_none_is_never_shown(self) -> None:
        assert LadderThrottle().should_show("s1", Pool.OPEN, N) is False


# --- against a real repository ----------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    return root


def _open_branches(repo: Path, count: int) -> None:
    tree = _git(repo, "rev-parse", "main^{tree}")
    for index in range(count):
        sha = _git(repo, "commit-tree", tree, "-p", "main", "-m", f"work {index}")
        _git(repo, "update-ref", f"refs/heads/work-{index:02d}", sha)


class TestPoolPressures:
    CONFIG = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2, count_remote=False))

    @pytest.mark.parametrize(
        ("count", "level"),
        [(7, N), (8, W), (9, W), (10, S), (11, V), (12, B)],
    )
    def test_open_pool_level_uses_cap_plus_grace(
        self, repo: Path, count: int, level: LadderLevel
    ) -> None:
        _open_branches(repo, count)
        found = {p.pool: p for p in pool_pressures(repo, self.CONFIG, {})}
        if level is N:
            assert Pool.OPEN not in found
            return
        assert found[Pool.OPEN].level is level
        assert (found[Pool.OPEN].count, found[Pool.OPEN].base) == (count, 12)

    def test_a_pool_in_off_mode_gives_no_level(self, repo: Path) -> None:
        _open_branches(repo, 11)
        config = BranchesConfig(
            wip=BranchWipConfig(cap=10, creation_grace=2, mode="off", count_remote=False)
        )
        assert pool_pressures(repo, config, {}) == []

    def test_a_git_failure_is_silent(self, tmp_path: Path) -> None:
        assert pool_pressures(tmp_path / "missing", self.CONFIG, {}) == []


class TestWording:
    CONFIG = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2, count_remote=False))

    def _lines(self, repo: Path, count: int, labels: Mapping[str, Mapping[str, str | None]]) -> str:
        _open_branches(repo, count)
        (pressure,) = pool_pressures(repo, self.CONFIG, labels)
        return "\n".join(pressure_lines(pressure, now=2_000_000_000.0))

    def test_names_pool_count_base_branch_and_command(self, repo: Path) -> None:
        text = self._lines(repo, 8, {})
        assert "open" in text.lower()
        assert "8 of 12" in text
        assert "work-" in text
        assert "branch-park" in text
        assert "branch-preflight" in text

    def test_strong_names_how_a_branch_leaves_the_pool(self, repo: Path) -> None:
        text = self._lines(repo, 10, {})
        assert "merge" in text
        assert "no-value verdict" in text
        assert "--allow-unproven" not in text
        assert "archive" not in text.lower()

    def test_warn_level_is_milder_than_strong(self, repo: Path) -> None:
        assert "no-value verdict" not in self._lines(repo, 8, {})

    def test_strong_names_an_unfinished_branch_before_a_merged_one(self, repo: Path) -> None:
        labels = {
            "work-00": {"group": "merged", "action": "branch-sweep --clean"},
            "work-01": {"group": "merged", "action": "branch-sweep --clean"},
        }
        text = self._lines(repo, 10, labels)
        named = [line for line in text.splitlines() if "work-" in line]
        assert named
        assert "work-00" not in named[0]
        assert "work-01" not in named[0]

    def test_very_strong_says_it_shows_on_every_call(self, repo: Path) -> None:
        text = self._lines(repo, 11, {})
        assert "VERY STRONG" in text
