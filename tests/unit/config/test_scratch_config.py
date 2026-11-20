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
        assert config.untracked_ttl == {"repos": "*", "scratch": "24h"}
        assert config.untracked_default_ttl == "*"
        assert config.max_ttl_hours == 72
        assert config.max_lifetime_hours == 168
        assert config.min_age_minutes == 30

    def test_sweep_defaults(self) -> None:
        sweep = ScratchConfig().sweep
        assert sweep.max_listed == 50
        assert sweep.unowned_entry == "advise"

    def test_archive_keep_and_filing_defaults(self) -> None:
        config = ScratchConfig()
        assert config.archive.disposable_hours == 12
        assert config.archive.uncertain_hours == 168
        assert config.keep.max_hours == 168
        assert config.keep.max_keeps == 4
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
        config = Config.model_validate({"scratch": {"untracked_ttl": {"scratch": "48h"}}})
        assert config.scratch.ttl_hours_for("scratch") == 48


class TestUnknownKeysFail:
    @pytest.mark.parametrize(
        "document",
        [
            {"ttl_hour": 24},
            {"ttl_hours": 24},
            {"sweep": {"max_list": 5}},
            {"sweep": {"extra_roots": ["untracked/briefs"]}},
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
            {"min_age_minutes": -1},
            {"sweep": {"max_listed": 0}},
            {"archive": {"disposable_hours": 0}},
            {"archive": {"uncertain_hours": 0}},
            {"keep": {"max_hours": 0}},
            {"keep": {"max_keeps": 0}},
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
    def test_a_root_ttl_above_the_manifest_bound_still_loads(self) -> None:
        """The owner's own example, ``scratch: 7d``, is longer than ``max_ttl_hours``."""
        config = ScratchConfig.model_validate({"untracked_ttl": {"scratch": "7d"}})
        assert config.ttl_hours_for("scratch") == 168

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


class TestUntrackedTtl:
    """DESIGN.md section 4.1: the owner's per-directory TTL map."""

    def test_the_owners_example_loads(self) -> None:
        config = ScratchConfig.model_validate(
            {"untracked_ttl": {"repos": "*", "scratch": "7d", "other-dir": "36h"}}
        )
        assert config.ttl_hours_for("repos") is None
        assert config.ttl_hours_for("scratch") == 168
        assert config.ttl_hours_for("other-dir") == 36

    def test_a_partial_map_keeps_the_built_in_entries(self) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {"briefs": "36h"}})
        assert config.untracked_ttl == {"repos": "*", "scratch": "24h", "briefs": "36h"}

    def test_an_unlisted_directory_falls_through_to_never(self) -> None:
        assert ScratchConfig().ttl_hours_for("logs") is None

    def test_the_fallthrough_is_configurable(self) -> None:
        config = ScratchConfig.model_validate({"untracked_default_ttl": "2d"})
        assert config.ttl_hours_for("anything") == 48

    @pytest.mark.parametrize("value", ["7 days", "36", "0h", "-1d", "", "1w", "1.5h", 36, None])
    def test_a_malformed_scratch_value_loads_but_its_ttl_is_an_error(
        self, value: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {"scratch": value}})
        with pytest.raises(ValueError, match=r"scratch\.untracked_ttl\.scratch"):
            config.ttl_hours_for("scratch")
        assert config.ttl_hours_for("repos") is None
        assert "untracked_ttl" in caplog.text

    def test_a_malformed_value_for_another_key_is_an_error_for_that_key_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = ScratchConfig.model_validate(
            {"untracked_default_ttl": "36h", "untracked_ttl": {"briefs": "soon"}}
        )
        with pytest.raises(ValueError, match="'soon'"):
            config.ttl_hours_for("briefs")
        assert config.ttl_hours_for("scratch") == 24
        assert config.ttl_hours_for("other") == 36
        assert "briefs" in caplog.text

    def test_a_malformed_fallthrough_is_an_error_for_unlisted_directories(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = ScratchConfig.model_validate({"untracked_default_ttl": "36 hours"})
        with pytest.raises(ValueError, match=r"scratch\.untracked_default_ttl.*36 hours"):
            config.ttl_hours_for("logs")
        assert config.ttl_hours_for("scratch") == 24
        assert "untracked_default_ttl" in caplog.text

    def test_a_non_string_value_that_would_print_as_a_ttl_stays_malformed(self) -> None:
        class Sneaky:
            def __str__(self) -> str:
                return "24h"

        config = ScratchConfig.model_validate({"untracked_ttl": {"scratch": Sneaky()}})
        with pytest.raises(ValueError, match="untracked_ttl"):
            config.ttl_hours_for("scratch")

    @pytest.mark.parametrize("key", ["a/b", ".", "..", "", "/abs"])
    def test_a_key_that_is_not_one_directory_name_is_dropped(
        self, key: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {key: "36h"}})
        assert key not in config.untracked_ttl
        assert "untracked_ttl" in caplog.text

    def test_a_map_that_is_not_a_mapping_makes_every_ttl_an_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": ["scratch"]})
        for directory in ("scratch", "briefs"):
            with pytest.raises(ValueError, match="not a mapping"):
                config.ttl_hours_for(directory)
        assert "untracked_ttl" in caplog.text

    def test_hours_and_days_are_parsed(self) -> None:
        config = ScratchConfig.model_validate({"untracked_ttl": {"a": "1h", "b": "1d"}})
        assert (config.ttl_hours_for("a"), config.ttl_hours_for("b")) == (1, 24)
