"""The branch pool warning ladder (Plan 00619): level function, base, throttle, wording.

The level is the share of a pool's block point in use: warn at 60, strong at 80
and very strong at 90 percent (thresholds rounded UP), block at the block point.
The open-work block point is ``wip.cap + wip.creation_grace``, because that is
where creation is actually denied; parked and merged pools block at their cap.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    BranchesConfig,
    BranchLadderConfig,
    BranchMergedConfig,
    BranchParkedConfig,
    BranchWipConfig,
)
from claude_code_hooks_daemon.core import branch_ladder
from claude_code_hooks_daemon.core.branch_creation import WorkGroup
from claude_code_hooks_daemon.core.branch_inventory import Pool
from claude_code_hooks_daemon.core.branch_ladder import (
    LadderLevel,
    LadderThrottle,
    PoolPressure,
    PressureCache,
    ladder_level,
    pool_base,
    pool_pressures,
    pressure_lines,
)
from tests.support.ladder_repo import (
    add_open_branches,
    git,
    init_repo,
    init_repo_with_remote,
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


_git = git
_open_branches = add_open_branches


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path)


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

    def test_a_merged_label_with_its_tip_leaves_the_open_pool(self, repo: Path) -> None:
        """A real snapshot label records the tip; a tipped merged label is in the merged pool."""
        _open_branches(repo, 10)
        labels = {
            name: {
                "group": "merged",
                "action": "branch-sweep --clean",
                "local_tip": _tip(repo, name),
            }
            for name in ("work-00", "work-01")
        }
        pools = {p.pool: p for p in pool_pressures(repo, self.CONFIG, labels)}
        assert pools[Pool.OPEN].count == 8
        named = [w.name for w in pools[Pool.OPEN].work]
        assert "work-00" not in named
        assert "work-01" not in named
        text = "\n".join(pressure_lines(pools[Pool.OPEN], now=2_000_000_000.0))
        first = next(line for line in text.splitlines() if "work-" in line)
        assert "work-00" not in first
        assert "work-01" not in first

    def test_very_strong_says_it_shows_on_every_call(self, repo: Path) -> None:
        text = self._lines(repo, 11, {})
        assert "VERY STRONG" in text


def _tip(repo: Path, name: str) -> str:
    return _git(repo, "rev-parse", f"refs/heads/{name}")


def _pressure(
    pool: Pool, level: LadderLevel, *, count: int, base: int, refuses: bool = True
) -> PoolPressure:
    work = tuple(
        WorkGroup(name=f"b-{i}", names=frozenset({f"b-{i}"}), committed=1_000_000.0 + i, pool=pool)
        for i in range(count)
    )
    return PoolPressure(pool, count, base, level, work, refuses=refuses)


class TestWarnModeWording:
    """In ``mode: warn`` creation is never refused, so the ladder must not say it is."""

    @pytest.mark.parametrize("section", ["wip", "parked", "merged"])
    def test_a_warn_mode_pool_at_the_limit_does_not_claim_a_refusal(self, section: str) -> None:
        pool = {"wip": Pool.OPEN, "parked": Pool.PARKED, "merged": Pool.MERGED}[section]
        config = BranchesConfig.model_validate({section: {"cap": 2, "mode": "warn"}})
        base = pool_base(config, pool)
        pressure = _pressure(pool, LadderLevel.BLOCK, count=base, base=base, refuses=False)
        text = "\n".join(pressure_lines(pressure, now=2_000_000_000.0))
        assert "refused" not in text
        assert "warn" in text.lower()

    def test_pool_pressures_marks_a_warn_pool_as_not_refusing(self, repo: Path) -> None:
        _open_branches(repo, 12)
        config = BranchesConfig(
            wip=BranchWipConfig(cap=10, creation_grace=2, mode="warn", count_remote=False)
        )
        (pressure,) = pool_pressures(repo, config, {})
        assert pressure.level is LadderLevel.BLOCK
        assert pressure.refuses is False
        assert "refused" not in "\n".join(pressure_lines(pressure, now=2_000_000_000.0))

    def test_a_block_mode_pool_still_says_it_is_refused(self, repo: Path) -> None:
        _open_branches(repo, 12)
        (pressure,) = pool_pressures(repo, TestPoolPressures.CONFIG, {})
        assert pressure.refuses is True
        assert "refused" in "\n".join(pressure_lines(pressure, now=2_000_000_000.0))


class TestPerPoolExitAdvice:
    """Each pool is left a different way; the strong advice must say the right one."""

    NOW = 2_000_000_000.0

    def _text(self, pool: Pool, level: LadderLevel) -> str:
        pressure = _pressure(pool, level, count=4, base=5)
        return "\n".join(pressure_lines(pressure, now=self.NOW))

    @pytest.mark.parametrize("level", [LadderLevel.STRONG, LadderLevel.VERY_STRONG])
    def test_merged_pool_is_cleared_by_a_sweep_or_a_keep_never_a_park(
        self, level: LadderLevel
    ) -> None:
        text = self._text(Pool.MERGED, level)
        assert "branch-sweep" in text
        assert "branch-keep" in text
        assert "park it" not in text
        assert "no-value verdict" not in text

    @pytest.mark.parametrize("level", [LadderLevel.STRONG, LadderLevel.VERY_STRONG])
    def test_parked_pool_is_left_by_clearing_the_park_and_merging(
        self, level: LadderLevel
    ) -> None:
        text = self._text(Pool.PARKED, level)
        assert "--clear" in text
        assert "merge" in text
        assert "park it only" not in text

    @pytest.mark.parametrize("level", [LadderLevel.STRONG, LadderLevel.VERY_STRONG])
    def test_open_pool_keeps_the_merge_verdict_or_park_advice(self, level: LadderLevel) -> None:
        text = self._text(Pool.OPEN, level)
        assert "no-value verdict" in text
        assert "park it only" in text

    def test_first_branch_to_close_is_the_oldest(self) -> None:
        text = self._text(Pool.OPEN, LadderLevel.STRONG)
        first = next(line for line in text.splitlines() if "Finish or remove first" in line)
        assert "b-0" in first


class TestPressureCacheBehaviour:
    CONFIG = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2, count_remote=False))

    def _counting(self, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        calls: list[int] = []
        real: Callable[..., Any] = branch_ladder.try_pool_pressures

        def counted(*args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            return real(*args, **kwargs)

        monkeypatch.setattr(branch_ladder, "try_pool_pressures", counted)
        return calls

    def test_a_reading_is_reused_within_the_ttl_then_refreshed(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _open_branches(repo, 11)
        calls = self._counting(monkeypatch)
        now = [100.0]
        cache = PressureCache(ttl=10.0)
        first = cache.get(repo, self.CONFIG, {}, clock=lambda: now[0])
        now[0] = 105.0
        assert cache.get(repo, self.CONFIG, {}, clock=lambda: now[0]) is first
        assert len(calls) == 1
        _git(repo, "update-ref", "-d", "refs/heads/work-10")
        now[0] = 111.0
        refreshed = cache.get(repo, self.CONFIG, {}, clock=lambda: now[0])
        assert len(calls) == 2
        assert refreshed[0].count == 10

    def test_the_key_is_the_config_value_not_its_identity(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _open_branches(repo, 11)
        calls = self._counting(monkeypatch)
        cache = PressureCache(ttl=10.0)
        same_value = BranchesConfig.model_validate(self.CONFIG.model_dump())
        cache.get(repo, self.CONFIG, {}, clock=lambda: 1.0)
        cache.get(repo, same_value, {}, clock=lambda: 2.0)
        assert len(calls) == 1
        other = BranchesConfig(wip=BranchWipConfig(cap=20, creation_grace=2, count_remote=False))
        assert cache.get(repo, other, {}, clock=lambda: 3.0) == []
        assert len(calls) == 2


class TestOwnerAndRemoteCounting:
    """The default counting reads remotes: own branches count once, foreign ones never."""

    def test_foreign_remote_only_branches_are_not_counted(self, tmp_path: Path) -> None:
        root = init_repo_with_remote(tmp_path)
        tree = _git(root, "rev-parse", "main^{tree}")
        for name, email, keep_local in (
            ("own-a", "t@example.com", True),
            ("own-b", "t@example.com", False),
            ("theirs-x", "other@example.com", False),
            ("theirs-y", "other@example.com", False),
        ):
            sha = _git(root, "commit-tree", tree, "-p", "main", "-m", name, author_email=email)
            _git(root, "update-ref", f"refs/heads/{name}", sha)
            _git(root, "push", "-q", "origin", name)
            if not keep_local:
                _git(root, "update-ref", "-d", f"refs/heads/{name}")
        config = BranchesConfig(wip=BranchWipConfig(cap=3, creation_grace=0))
        (pressure,) = pool_pressures(root, config, {})
        assert pressure.pool is Pool.OPEN
        assert pressure.count == 2
        assert pressure.base == 3
        assert {w.name for w in pressure.work} == {"own-a", "own-b"}
