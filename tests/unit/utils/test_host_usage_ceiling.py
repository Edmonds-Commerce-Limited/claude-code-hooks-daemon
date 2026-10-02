"""Tests for the host usage-ceiling resolver (Plan 00479 Task 3.2).

Several matching entries combine as: the lowest ceiling wins, per window.
No match, or no ceiling on the matches, means no ceiling.
"""

from __future__ import annotations

import dataclasses

from claude_code_hooks_daemon.config.models import HostConfig
from claude_code_hooks_daemon.utils.host_usage_ceiling import (
    HostUsageCeiling,
    resolve_host_usage_ceiling,
)


def _host(
    pattern: str | None = None,
    *,
    max_used: float | None = None,
    five_hour: float | None = None,
    seven_day: float | None = None,
) -> HostConfig:
    ceiling: dict[str, float] = {}
    if max_used is not None:
        ceiling["max_used_percent"] = max_used
    if five_hour is not None:
        ceiling["five_hour"] = five_hour
    if seven_day is not None:
        ceiling["seven_day"] = seven_day
    return HostConfig.model_validate(
        {"pattern": pattern, **({"usage_ceiling": ceiling} if ceiling else {})}
    )


class TestResolve:
    def test_no_hosts_means_no_ceiling(self) -> None:
        assert resolve_host_usage_ceiling({}, "box") == HostUsageCeiling(None, None, ())

    def test_no_match_means_no_ceiling(self) -> None:
        result = resolve_host_usage_ceiling({"other": _host(max_used=50)}, "box")
        assert result == HostUsageCeiling(None, None, ())

    def test_label_match_applies_to_both_windows(self) -> None:
        result = resolve_host_usage_ceiling({"box": _host(max_used=80)}, "box")
        assert result == HostUsageCeiling(80, 80, ("box",))

    def test_pattern_match(self) -> None:
        hosts = {"runner": _host("cchd-sdlc-*", max_used=80)}
        result = resolve_host_usage_ceiling(hosts, "cchd-sdlc-1")
        assert result.matched_labels == ("runner",)
        assert result.five_hour == 80

    def test_per_window_overrides(self) -> None:
        hosts = {"box": _host(max_used=80, five_hour=85, seven_day=70)}
        result = resolve_host_usage_ceiling(hosts, "box")
        assert (result.five_hour, result.seven_day) == (85, 70)

    def test_lowest_ceiling_wins_per_window(self) -> None:
        hosts = {
            "a": _host("b*", five_hour=90, seven_day=50),
            "b": _host("box", five_hour=60, seven_day=95),
        }
        result = resolve_host_usage_ceiling(hosts, "box")
        assert result == HostUsageCeiling(60, 50, ("a", "b"))

    def test_a_matching_entry_without_a_ceiling_is_listed_but_sets_none(self) -> None:
        hosts = {"a": _host("box"), "b": _host("b*", max_used=70)}
        result = resolve_host_usage_ceiling(hosts, "box")
        assert result == HostUsageCeiling(70, 70, ("a", "b"))

    def test_window_only_set_by_one_match_stays_unset_for_the_other(self) -> None:
        result = resolve_host_usage_ceiling({"box": _host(five_hour=60)}, "box")
        assert result == HostUsageCeiling(60, None, ("box",))

    def test_result_is_frozen_and_hashable(self) -> None:
        result = HostUsageCeiling(None, None, ())
        assert dataclasses.is_dataclass(result)
        assert hash(result) == hash(HostUsageCeiling(None, None, ()))
