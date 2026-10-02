"""Tests for the top-level ``hosts:`` config block (Plan 00479 Task 3.1).

Entries are keyed by a label; an optional ``pattern`` is a case-sensitive fnmatch
glob matched against the effective session hostname, and without one the label
is the exact hostname. Per-host settings live in ``HostConfig``; the usage
ceiling is its first member.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, HostConfig, UsageCeilingConfig


class TestDefaults:
    def test_a_project_that_says_nothing_declares_no_hosts(self) -> None:
        assert Config().hosts == {}


class TestParsing:
    def test_full_shape_parses(self) -> None:
        config = Config.model_validate(
            {
                "hosts": {
                    "sdlc-runner": {
                        "pattern": "cchd-sdlc-*",
                        "usage_ceiling": {
                            "max_used_percent": 80,
                            "five_hour": 85,
                            "seven_day": 70,
                        },
                    },
                    "dev-laptop": {"usage_ceiling": {"max_used_percent": 95}},
                }
            }
        )
        runner = config.hosts["sdlc-runner"]
        assert runner.pattern == "cchd-sdlc-*"
        assert runner.usage_ceiling is not None
        assert runner.usage_ceiling.five_hour == 85
        assert runner.usage_ceiling.seven_day == 70
        laptop = config.hosts["dev-laptop"]
        assert laptop.pattern is None
        assert laptop.usage_ceiling is not None
        assert laptop.usage_ceiling.max_used_percent == 95

    def test_a_host_with_no_settings_is_valid(self) -> None:
        assert Config.model_validate({"hosts": {"box": {}}}).hosts["box"].usage_ceiling is None

    def test_yaml_round_trip_keeps_the_block(self) -> None:
        config = Config.model_validate(
            {"hosts": {"box": {"usage_ceiling": {"max_used_percent": 50}}}}
        )
        assert Config.model_validate(config.model_dump()) == config


class TestValidation:
    @pytest.mark.parametrize("bad", [0, -1, 100.5, 101])
    def test_percent_out_of_range_is_rejected(self, bad: float) -> None:
        with pytest.raises(ValidationError, match="greater than 0 and at most 100"):
            UsageCeilingConfig(max_used_percent=bad)

    @pytest.mark.parametrize("field", ["five_hour", "seven_day"])
    def test_override_out_of_range_is_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError, match="greater than 0 and at most 100"):
            UsageCeilingConfig.model_validate({"max_used_percent": 80, field: 0})

    def test_100_is_allowed(self) -> None:
        assert UsageCeilingConfig(max_used_percent=100).max_used_percent == 100

    def test_percent_must_be_a_number_not_a_bool(self) -> None:
        with pytest.raises(ValidationError):
            UsageCeilingConfig.model_validate({"max_used_percent": True})

    def test_a_ceiling_naming_no_limit_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one of"):
            UsageCeilingConfig.model_validate({})

    def test_a_per_window_override_alone_is_a_ceiling(self) -> None:
        ceiling = UsageCeilingConfig.model_validate({"five_hour": 60})
        assert ceiling.effective_five_hour == 60
        assert ceiling.effective_seven_day is None

    def test_overrides_beat_max_used_percent(self) -> None:
        ceiling = UsageCeilingConfig(max_used_percent=80, five_hour=85, seven_day=70)
        assert (ceiling.effective_five_hour, ceiling.effective_seven_day) == (85, 70)

    def test_max_used_percent_applies_to_both_windows(self) -> None:
        ceiling = UsageCeilingConfig(max_used_percent=80)
        assert (ceiling.effective_five_hour, ceiling.effective_seven_day) == (80, 80)

    def test_unknown_ceiling_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="max_used_pct"):
            UsageCeilingConfig.model_validate({"max_used_pct": 80})

    def test_unknown_host_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="usage_ceilng"):
            HostConfig.model_validate({"usage_ceilng": {"max_used_percent": 80}})

    @pytest.mark.parametrize("bad", [5, ["a"], "", "   "])
    def test_bad_pattern_is_rejected(self, bad: Any) -> None:
        with pytest.raises(ValidationError):
            HostConfig.model_validate({"pattern": bad})

    def test_blank_label_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="label"):
            Config.model_validate({"hosts": {" ": {}}})

    def test_hosts_must_be_a_mapping(self) -> None:
        with pytest.raises(ValidationError):
            Config.model_validate({"hosts": ["a"]})


class TestMatching:
    def test_without_a_pattern_the_label_is_the_exact_hostname(self) -> None:
        host = HostConfig()
        assert host.matches("box", "box") is True
        assert host.matches("box", "box2") is False

    def test_label_is_not_a_glob(self) -> None:
        assert HostConfig().matches("box-*", "box-1") is False

    def test_pattern_is_a_glob(self) -> None:
        host = HostConfig(pattern="cchd-sdlc-*")
        assert host.matches("anything", "cchd-sdlc-runner") is True
        assert host.matches("anything", "other") is False

    def test_pattern_is_case_sensitive(self) -> None:
        assert HostConfig(pattern="Box").matches("x", "box") is False
