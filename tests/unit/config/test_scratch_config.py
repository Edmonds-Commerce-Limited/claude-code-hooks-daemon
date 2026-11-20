"""The ``scratch:`` config block (Plan 00627 Task 1.2, DESIGN.md section 10).

Every default is asserted on its own: a default that drifts silently changes
how long an agent's notes survive.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, ScratchConfig


class TestDefaults:
    def test_ttl_defaults(self) -> None:
        config = ScratchConfig()
        assert config.ttl_hours == 24
        assert config.max_ttl_hours == 72
        assert config.max_lifetime_hours == 168
        assert config.min_age_minutes == 30

    def test_sweep_defaults(self) -> None:
        sweep = ScratchConfig().sweep
        assert sweep.extra_roots == []
        assert sweep.max_listed == 50
        assert sweep.unowned_entry == "advise"

    def test_archive_keep_and_filing_defaults(self) -> None:
        config = ScratchConfig()
        assert config.archive.disposable_hours == 12
        assert config.archive.uncertain_hours == 168
        assert config.keep.max_hours == 168
        assert config.filing.max_bytes == 262144

    def test_cap_defaults(self) -> None:
        caps = ScratchConfig().caps
        assert (caps.directories.warn, caps.directories.block) == (10000, 25000)
        assert (caps.bytes.warn, caps.bytes.block) == (1073741824, 4294967296)
        assert (caps.entries.warn, caps.entries.block) == (500, 2000)
        assert caps.project_directories.warn_percent == 50
        assert caps.project_directories.block_percent == 75
        assert caps.pressure_idle_minutes == 30
        assert caps.mode == "block"

    def test_root_config_carries_the_block(self) -> None:
        assert Config().scratch == ScratchConfig()

    def test_root_config_reads_the_block(self) -> None:
        config = Config.model_validate({"scratch": {"ttl_hours": 48, "max_ttl_hours": 96}})
        assert config.scratch.ttl_hours == 48


class TestUnknownKeysFail:
    @pytest.mark.parametrize(
        "document",
        [
            {"ttl_hour": 24},
            {"sweep": {"max_list": 5}},
            {"archive": {"disposable": 1}},
            {"keep": {"hours": 1}},
            {"filing": {"bytes": 1}},
            {"caps": {"dirs": {"warn": 1, "block": 2}}},
            {"caps": {"directories": {"warn": 1, "block": 2, "hard": 3}}},
            {"caps": {"project_directories": {"warn": 50}}},
        ],
    )
    def test_a_misspelt_key_is_rejected(self, document: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            ScratchConfig.model_validate(document)


class TestBounds:
    @pytest.mark.parametrize(
        "document",
        [
            {"ttl_hours": 0},
            {"min_age_minutes": -1},
            {"sweep": {"max_listed": 0}},
            {"archive": {"disposable_hours": 0}},
            {"archive": {"uncertain_hours": 0}},
            {"keep": {"max_hours": 0}},
            {"filing": {"max_bytes": 0}},
            {"caps": {"pressure_idle_minutes": 0}},
            {"caps": {"project_directories": {"warn_percent": 0, "block_percent": 75}}},
            {"caps": {"project_directories": {"warn_percent": 50, "block_percent": 101}}},
        ],
    )
    def test_an_out_of_range_value_is_rejected(self, document: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            ScratchConfig.model_validate(document)

    @pytest.mark.parametrize("mode", ["block", "advise", "off"])
    def test_every_cap_mode_is_accepted(self, mode: str) -> None:
        assert ScratchConfig.model_validate({"caps": {"mode": mode}}).caps.mode == mode

    @pytest.mark.parametrize("mode", ["advise", "block", "off"])
    def test_every_unowned_entry_mode_is_accepted(self, mode: str) -> None:
        config = ScratchConfig.model_validate({"sweep": {"unowned_entry": mode}})
        assert config.sweep.unowned_entry == mode

    def test_an_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScratchConfig.model_validate({"caps": {"mode": "warn"}})


class TestOrdering:
    def test_max_ttl_below_ttl_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="max_ttl_hours"):
            ScratchConfig.model_validate({"ttl_hours": 48, "max_ttl_hours": 24})

    def test_max_ttl_equal_to_ttl_is_accepted(self) -> None:
        config = ScratchConfig.model_validate({"ttl_hours": 72, "max_ttl_hours": 72})
        assert config.max_ttl_hours == 72

    def test_lifetime_below_max_ttl_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="max_lifetime_hours"):
            ScratchConfig.model_validate({"max_lifetime_hours": 48})

    @pytest.mark.parametrize("cap", ["directories", "bytes", "entries"])
    def test_a_warn_cap_at_or_above_block_is_rejected(self, cap: str) -> None:
        with pytest.raises(ValidationError, match="warn"):
            ScratchConfig.model_validate({"caps": {cap: {"warn": 10, "block": 10}}})

    def test_a_warn_percent_at_or_above_block_percent_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="warn_percent"):
            ScratchConfig.model_validate(
                {"caps": {"project_directories": {"warn_percent": 75, "block_percent": 75}}}
            )


class TestExtraRoots:
    def test_a_relative_root_is_kept(self) -> None:
        config = ScratchConfig.model_validate({"sweep": {"extra_roots": ["untracked/briefs"]}})
        assert config.sweep.extra_roots == ["untracked/briefs"]

    @pytest.mark.parametrize("root", ["", "/abs/path", "../outside", "untracked/../..", "."])
    def test_a_root_outside_the_project_or_the_project_itself_is_rejected(self, root: str) -> None:
        with pytest.raises(ValidationError, match="extra_roots"):
            ScratchConfig.model_validate({"sweep": {"extra_roots": [root]}})
