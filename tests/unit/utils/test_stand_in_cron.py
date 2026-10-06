"""The timed stand-in cron (Plan 00470 Task 5.2): schedule, prompt and Stop verdict."""

from __future__ import annotations

import time
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.utils.cron_enforcement import SessionCron
from claude_code_hooks_daemon.utils.cron_tick import (
    TickKind,
    classify_tick,
    tick_sentinel,
)
from claude_code_hooks_daemon.utils.stand_in_cron import (
    DEFAULT_STAND_IN_DELAY_HOURS,
    STAND_IN_SENTINEL,
    has_stand_in_cron,
    one_off_schedule,
    stand_in_prompt,
    stand_in_verdict,
    validate_delay_hours,
)

_NOW = time.mktime((2026, 10, 6, 9, 15, 0, 0, 0, -1))


def _stop(crons: list[dict[str, Any]] | None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"hook_event_name": "Stop", "session_id": "s1", **extra}
    if crons is not None:
        payload["session_crons"] = crons
    return payload


def _cron(prompt: str, cron_id: str = "c1") -> dict[str, Any]:
    return {"id": cron_id, "schedule": "0 12 6 10 *", "prompt": prompt, "recurring": False}


class TestSentinel:
    def test_the_sentinel_is_a_tick_kind(self) -> None:
        assert tick_sentinel(TickKind.STAND_IN) == "[tick:stand-in]" == STAND_IN_SENTINEL

    def test_it_classifies_as_stand_in(self) -> None:
        tick = classify_tick(stand_in_prompt())
        assert tick is not None and tick.kind is TickKind.STAND_IN


class TestPrompt:
    def test_first_line_is_the_sentinel(self) -> None:
        assert stand_in_prompt().splitlines()[0] == STAND_IN_SENTINEL

    def test_states_the_constraints(self) -> None:
        text = stand_in_prompt()
        for needle in (
            "model: fable",
            "claude-fable-5-1",
            "mkplan.bash --journal",
            "the stand-in's ruling",
            "never as the owner's",
            "overturn",
            "ONLY among engineering options",
            "releases",
            "force deletes",
            "remote branch deletes",
            "QA suppressions",
            "history rewrites",
            "upgrade approvals",
            "no-op",
            "declined",
        ):
            assert needle in text

    def test_fits_the_delivered_prompt_cap(self) -> None:
        assert len(stand_in_prompt()) < 1000


class TestSchedule:
    def test_three_hours_out_as_a_one_off_five_field_cron(self) -> None:
        assert one_off_schedule(_NOW, 3.0) == "15 12 6 10 *"

    def test_rolls_over_midnight(self) -> None:
        assert one_off_schedule(_NOW, 15.0) == "15 0 7 10 *"


class TestDelayValidation:
    def test_default_is_three_hours(self) -> None:
        assert DEFAULT_STAND_IN_DELAY_HOURS == 3.0

    @pytest.mark.parametrize("value", [1, 3.0, 0.5, 23.5])
    def test_accepts_a_positive_number_below_a_day(self, value: float) -> None:
        assert validate_delay_hours(value) == float(value)

    @pytest.mark.parametrize("value", [0, -1, 24, 100, "3", None, True, float("nan")])
    def test_rejects_everything_else(self, value: object) -> None:
        with pytest.raises(ValueError, match="stand_in_delay_hours"):
            validate_delay_hours(value)


class TestHasStandIn:
    def test_true_with_a_sentinel_cron(self) -> None:
        assert has_stand_in_cron([SessionCron("c", "x", stand_in_prompt())])

    def test_false_otherwise(self) -> None:
        assert not has_stand_in_cron([SessionCron("c", "x", "[tick:failsafe]\nbody")])
        assert not has_stand_in_cron([])


class TestVerdict:
    def test_denies_with_the_exact_cron_create(self) -> None:
        result = stand_in_verdict(_stop([]), delay_hours=3.0, now=_NOW)
        assert result is not None and result.decision is Decision.DENY
        reason = result.reason or ""
        assert "CronCreate" in reason
        assert "recurring: false" in reason
        assert "15 12 6 10 *" in reason
        assert all(line.strip() in reason for line in stand_in_prompt().splitlines() if line)

    def test_allows_when_a_stand_in_exists(self) -> None:
        assert (
            stand_in_verdict(_stop([_cron(stand_in_prompt())]), delay_hours=3.0, now=_NOW) is None
        )

    def test_other_crons_do_not_count(self) -> None:
        crons = [_cron("[tick:job:issue-sdlc]\nbody")]
        assert stand_in_verdict(_stop(crons), delay_hours=3.0, now=_NOW) is not None

    def test_absent_session_crons_is_no_information(self) -> None:
        assert stand_in_verdict(_stop(None), delay_hours=3.0, now=_NOW) is None

    def test_reentry_is_allowed(self) -> None:
        payload = _stop([], stop_hook_active=True)
        assert stand_in_verdict(payload, delay_hours=3.0, now=_NOW) is None
