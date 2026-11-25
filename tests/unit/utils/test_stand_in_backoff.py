"""A stand-in that declines again with no human in between backs off (Plan 00639 Task 1.3)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.utils import stand_in_cron
from claude_code_hooks_daemon.utils.session_modes import SessionPolicy, declared_blocked_entry
from claude_code_hooks_daemon.utils.stand_in_cron import (
    DEFAULT_STAND_IN_DELAY_HOURS,
    MAX_STAND_IN_DELAY_HOURS,
    backed_off_delay_hours,
    stand_in_requirement,
)

_NOW = time.mktime((2026, 11, 25, 9, 0, 0, 0, 0, -1))
_HOUR = 3600.0


class TestBackedOffDelayHours:
    def test_a_first_stop_keeps_the_configured_delay(self) -> None:
        assert backed_off_delay_hours(3.0, previous_entered_at=None, now=_NOW) == 3.0

    def test_a_repeat_stop_waits_twice_as_long_as_the_gap_since_the_last_one(self) -> None:
        assert backed_off_delay_hours(3.0, previous_entered_at=_NOW - 3 * _HOUR, now=_NOW) == 6.0
        assert backed_off_delay_hours(3.0, previous_entered_at=_NOW - 6 * _HOUR, now=_NOW) == 12.0

    def test_a_quick_repeat_never_goes_below_the_configured_delay(self) -> None:
        assert backed_off_delay_hours(3.0, previous_entered_at=_NOW - 0.1 * _HOUR, now=_NOW) == 3.0

    def test_the_backoff_stays_inside_the_marker_expiry(self) -> None:
        delay = backed_off_delay_hours(3.0, previous_entered_at=_NOW - 20 * _HOUR, now=_NOW)
        assert 3.0 < delay < MAX_STAND_IN_DELAY_HOURS

    def test_a_configured_delay_above_the_ceiling_is_kept_as_is(self) -> None:
        assert backed_off_delay_hours(23.5, previous_entered_at=_NOW - 20 * _HOUR, now=_NOW) == 23.5

    def test_a_previous_entry_in_the_future_is_ignored(self) -> None:
        assert backed_off_delay_hours(3.0, previous_entered_at=_NOW + _HOUR, now=_NOW) == 3.0


def _requirement_for(monkeypatch: pytest.MonkeyPatch, *, previous_entered_at: float | None) -> Any:
    entries = (
        []
        if previous_entered_at is None
        else [declared_blocked_entry("s1", entered_at=previous_entered_at)]
    )
    verdict = SimpleNamespace(environment_allowed=True, session=SessionPolicy.from_entries(entries))
    monkeypatch.setattr(stand_in_cron, "autonomy_verdict", lambda _hook_input: verdict)
    config = Config.model_validate({"persistent_crons": {"enabled": True}})
    payload = {"hook_event_name": "Stop", "session_id": "s1", "session_crons": []}
    return stand_in_requirement(
        payload, config=config, delay_hours=DEFAULT_STAND_IN_DELAY_HOURS, now=_NOW
    )


class TestRequirementBacksOff:
    def test_a_first_awaiting_human_stop_schedules_the_configured_delay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _requirement_for(monkeypatch, previous_entered_at=None)
        assert result is not None and result.decision is Decision.DENY
        assert "about 3 hours out" in result.reason

    def test_a_repeat_stop_with_no_human_between_schedules_a_longer_delay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _requirement_for(monkeypatch, previous_entered_at=_NOW - 3 * _HOUR)
        assert result is not None and result.decision is Decision.DENY
        assert "about 6 hours out" in result.reason
