"""The `branches:` config block (Plan 00558 Task 2.0, DESIGN.md section 1).

One top-level block feeds the inventory, the guards and the CLI so they cannot
disagree. Every default is asserted on its own: a default that drifts silently
turns an owner ruling (cap 10, dormancy 7/14/30, strict 3/3/7) into a guess.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    BRANCH_DORMANCY_PRESETS,
    BranchDormancyConfig,
    BranchesConfig,
    Config,
)
from claude_code_hooks_daemon.daemon import branch_safety


class TestTopLevelDefaults:
    def test_default_branch_is_auto(self) -> None:
        assert BranchesConfig().default == "auto"

    def test_remote_is_origin(self) -> None:
        assert BranchesConfig().remote == "origin"

    def test_no_integration_lines_or_exemptions(self) -> None:
        config = BranchesConfig()
        assert config.integration_lines == []
        assert config.exempt == []

    def test_protected_names_default(self) -> None:
        assert BranchesConfig().protected_names == ["main", "master", "develop", "trunk"]

    def test_branch_safety_reads_the_model_default(self) -> None:
        """The model is the single source of the protected names."""
        assert branch_safety.DEFAULT_PROTECTED_NAMES == tuple(BranchesConfig().protected_names)


class TestNestedDefaults:
    def test_wip(self) -> None:
        wip = BranchesConfig().wip
        assert (wip.cap, wip.mode, wip.count_remote) == (10, "block", True)

    def test_duplicates(self) -> None:
        assert BranchesConfig().duplicates.mode == "warn"

    def test_dormancy(self) -> None:
        dormancy = BranchesConfig().dormancy
        assert dormancy.preset == "standard"
        assert (dormancy.advisory_days, dormancy.noisy_days, dormancy.block_days) == (
            None,
            None,
            None,
        )
        assert dormancy.mode == "block"

    def test_stop_guard(self) -> None:
        guard = BranchesConfig().stop_guard
        assert (guard.mode, guard.unpushed_subagent, guard.include_default) == (
            "block",
            "block",
            False,
        )

    def test_force_removal_evacuation_cleanup(self) -> None:
        config = BranchesConfig()
        assert config.force_removal.mode == "block"
        assert config.evacuation.mode == "block"
        assert config.cleanup_after_merge.mode == "advise"

    def test_sweep(self) -> None:
        sweep = BranchesConfig().sweep
        assert (sweep.budget_ms, sweep.behind_threshold) == (3000, 50)

    def test_zero_budget_is_allowed(self) -> None:
        """A zero budget is a real setting: classify only what the bulk steps prove."""
        assert BranchesConfig.model_validate({"sweep": {"budget_ms": 0}}).sweep.budget_ms == 0


class TestExtraForbid:
    @pytest.mark.parametrize(
        "data",
        [
            {"unknown": 1},
            {"wip": {"limit": 3}},
            {"duplicates": {"x": 1}},
            {"dormancy": {"days": 3}},
            {"stop_guard": {"x": 1}},
            {"force_removal": {"x": 1}},
            {"evacuation": {"x": 1}},
            {"cleanup_after_merge": {"x": 1}},
            {"sweep": {"x": 1}},
        ],
    )
    def test_unknown_keys_are_rejected(self, data: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            BranchesConfig.model_validate(data)

    @pytest.mark.parametrize(
        "data",
        [
            {"wip": {"mode": "loud"}},
            {"duplicates": {"mode": "block"}},
            {"stop_guard": {"unpushed_subagent": "warn"}},
            {"force_removal": {"mode": "warn"}},
            {"cleanup_after_merge": {"mode": "block"}},
            {"dormancy": {"preset": "lenient"}},
            {"wip": {"cap": 0}},
            {"sweep": {"budget_ms": -1}},
            {"sweep": {"behind_threshold": 0}},
            {"default": ""},
            {"remote": " "},
        ],
    )
    def test_invalid_values_are_rejected(self, data: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            BranchesConfig.model_validate(data)


class TestDormancyEffectiveValues:
    def test_presets(self) -> None:
        assert BRANCH_DORMANCY_PRESETS["standard"] == (7, 14, 30)
        assert BRANCH_DORMANCY_PRESETS["strict"] == (3, 3, 7)

    def test_standard_effective(self) -> None:
        assert BranchDormancyConfig().effective_days == (7, 14, 30)

    def test_strict_effective(self) -> None:
        assert BranchDormancyConfig(preset="strict").effective_days == (3, 3, 7)

    def test_override_one_stage(self) -> None:
        config = BranchDormancyConfig(preset="strict", block_days=10)
        assert config.effective_days == (3, 3, 10)

    def test_inverted_override_is_a_load_error(self) -> None:
        """noisy 20 > block 7 under strict: the effective values invert."""
        with pytest.raises(ValidationError, match="advisory_days <= noisy_days < block_days"):
            BranchDormancyConfig(preset="strict", noisy_days=20)

    def test_override_valid_under_one_preset_only(self) -> None:
        """advisory 10 fits strict? No: 10 > noisy 3. Fits standard: 10 <= 14 < 30."""
        assert BranchDormancyConfig(advisory_days=10).effective_days == (10, 14, 30)
        with pytest.raises(ValidationError):
            BranchDormancyConfig(preset="strict", advisory_days=10)

    def test_noisy_equal_block_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BranchDormancyConfig(noisy_days=30)

    def test_stage_below_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BranchDormancyConfig(advisory_days=0)


class TestExplicitFallbackKeys:
    """`branch_count_advisor` falls back to its own options only when these are unset."""

    def test_unset_returns_none(self) -> None:
        config = BranchesConfig()
        assert config.explicit_wip_cap() is None
        assert config.explicit_behind_threshold() is None

    def test_set_returns_value(self) -> None:
        config = BranchesConfig.model_validate(
            {"wip": {"cap": 4}, "sweep": {"behind_threshold": 9}}
        )
        assert config.explicit_wip_cap() == 4
        assert config.explicit_behind_threshold() == 9

    def test_set_to_the_default_still_counts_as_set(self) -> None:
        config = BranchesConfig.model_validate({"wip": {"cap": 10}})
        assert config.explicit_wip_cap() == 10


class TestRootConfig:
    def test_config_has_a_default_branches_block(self) -> None:
        assert Config().branches == BranchesConfig()

    def test_config_loads_the_block(self, tmp_path: Path) -> None:
        path = tmp_path / "hooks-daemon.yaml"
        path.write_text(
            'version: "2.0"\n'
            "branches:\n"
            "  default: trunk\n"
            "  integration_lines: ['release/*']\n"
            "  dormancy: {preset: strict}\n"
        )
        config = Config.load(path)
        assert config.branches.default == "trunk"
        assert config.branches.integration_lines == ["release/*"]
        assert config.branches.dormancy.effective_days == (3, 3, 7)

    def test_inverted_dormancy_fails_the_whole_load(self, tmp_path: Path) -> None:
        path = tmp_path / "hooks-daemon.yaml"
        path.write_text('version: "2.0"\nbranches:\n  dormancy: {advisory_days: 40}\n')
        with pytest.raises((ValidationError, ValueError)):
            Config.load(path)
