"""Building one session's state document from the daemon's own records (Plan 00601 Phase 3).

The records are written by the real writers (stop-failure records, the usage
tracker, the usage pause) and the result is validated against the shipped schema.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from claude_code_hooks_daemon.core import session_state_document as ssd
from claude_code_hooks_daemon.core import state_schemas
from claude_code_hooks_daemon.core.usage_snapshot import UsageTracker, usage_state_file
from claude_code_hooks_daemon.utils.stop_failure_records import (
    STOP_FAILURE_RECORDS_FILENAME,
    StopFailureRecord,
    record_failure,
    resolve_session,
)
from claude_code_hooks_daemon.utils.usage_pause import UsagePause, write_usage_pause

SESSION = "sess-1"
NOW = 1_800_000_000.0


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        state_schemas.load_schema(name), registry=state_schemas.schema_registry()
    )


def _status(
    tmp_path: Path, five: tuple[float, int] | None, seven: tuple[float, int] | None
) -> None:
    windows: dict[str, Any] = {}
    if five:
        windows["five_hour"] = {"used_percentage": five[0], "resets_at": five[1]}
    if seven:
        windows["seven_day"] = {"used_percentage": seven[0], "resets_at": seven[1]}
    UsageTracker().update_from_status_event(
        {"rate_limits": windows}, now=NOW - 5, state_file=usage_state_file(tmp_path)
    )


def _stop_event(tmp_path: Path, session: str, at: float) -> None:
    line = {
        "timestamp": datetime.fromtimestamp(at, tz=UTC).isoformat(),
        "decision": "allow",
        "reason_prefix": "",
        "stop_hook_active": False,
        "session_id": session,
    }
    with (tmp_path / "stop-events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


def _failure(tmp_path: Path, at: float, error: str = "rate_limit") -> None:
    record_failure(
        tmp_path / STOP_FAILURE_RECORDS_FILENAME,
        StopFailureRecord(session_id=SESSION, error=error, recorded_at=at),
    )


def _build(tmp_path: Path, modes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    document = ssd.build_session_state(SESSION, modes=modes or [], untracked_dir=tmp_path, now=NOW)
    _validator(state_schemas.SCHEMA_SESSION_STATE).validate(document)
    return document


class TestBuildSessionState:
    def test_unknown_session_is_all_null_and_valid(self, tmp_path: Path) -> None:
        document = _build(tmp_path)
        assert document["schema_version"] == state_schemas.SCHEMA_VERSION
        assert document["session_id"] == SESSION
        assert document["observed_at"] == NOW
        assert document["modes"] == []
        assert document["last_turn_edge"] is None
        assert document["usage"] == {"five_hour": None, "seven_day": None, "observed_at": None}
        assert document["limit_reset"] is None
        assert document["usage_pause"] is None

    def test_modes_are_passed_through(self, tmp_path: Path) -> None:
        mode = {
            "label": "focus",
            "mode": "focus",
            "reason": None,
            "source": "human",
            "detail": "x",
            "entered_at": 1.0,
            "expires_at": 2.0,
        }
        assert _build(tmp_path, [mode])["modes"] == [mode]

    def test_usage_reports_both_windows(self, tmp_path: Path) -> None:
        _status(tmp_path, (40.0, int(NOW) + 3600), (10.0, int(NOW) + 86400))
        usage = _build(tmp_path)["usage"]
        assert usage["five_hour"]["used_percentage"] == 40.0
        assert usage["seven_day"]["resets_at"] == int(NOW) + 86400
        assert usage["observed_at"] == NOW - 5

    def test_last_stop_of_this_session_is_the_turn_edge(self, tmp_path: Path) -> None:
        _stop_event(tmp_path, "someone-else", NOW - 10)
        _stop_event(tmp_path, SESSION, NOW - 300)
        _stop_event(tmp_path, SESSION, NOW - 100)
        edge = _build(tmp_path)["last_turn_edge"]
        assert edge["kind"] == "stop"
        assert edge["at"] == pytest.approx(NOW - 100)

    def test_unreadable_stop_event_lines_are_skipped(self, tmp_path: Path) -> None:
        _stop_event(tmp_path, SESSION, NOW - 100)
        with (tmp_path / "stop-events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
            handle.write(json.dumps({"session_id": SESSION, "timestamp": "garbage"}) + "\n")
        assert _build(tmp_path)["last_turn_edge"]["at"] == pytest.approx(NOW - 100)

    def test_a_stop_failure_newer_than_the_stop_is_the_turn_edge(self, tmp_path: Path) -> None:
        _stop_event(tmp_path, SESSION, NOW - 100)
        _failure(tmp_path, NOW - 50)
        assert _build(tmp_path)["last_turn_edge"] == {
            "kind": "stop_failure",
            "at": NOW - 50,
            "error": "rate_limit",
            "resolved_at": None,
        }

    def test_a_resolved_failure_makes_the_next_prompt_the_turn_start(self, tmp_path: Path) -> None:
        _failure(tmp_path, NOW - 50)
        resolve_session(tmp_path / STOP_FAILURE_RECORDS_FILENAME, SESSION, now=NOW - 20)
        assert _build(tmp_path)["last_turn_edge"] == {"kind": "start", "at": NOW - 20}

    def test_usage_pause_is_reported(self, tmp_path: Path) -> None:
        write_usage_pause(
            tmp_path,
            UsagePause(
                session_id=SESSION,
                paused_at=NOW - 10,
                resume_at=NOW + 600,
                window="five_hour",
                used_percentage=91.0,
                ceiling=90.0,
                reason="ceiling",
            ),
        )
        pause = _build(tmp_path)["usage_pause"]
        assert pause["resume_at"] == NOW + 600
        assert pause["window"] == "five_hour"


class TestLimitReset:
    """Task 1.1: a rate_limit stop carries no reset time; it is joined to the usage snapshot."""

    def test_unresolved_rate_limit_joins_the_window_that_is_full(self, tmp_path: Path) -> None:
        _failure(tmp_path, NOW - 30)
        _status(tmp_path, (100.0, int(NOW) + 1800), (30.0, int(NOW) + 400_000))
        assert _build(tmp_path)["limit_reset"] == {
            "window": "five_hour",
            "resets_at": int(NOW) + 1800,
        }

    def test_both_windows_full_waits_for_the_later_reset(self, tmp_path: Path) -> None:
        _failure(tmp_path, NOW - 30)
        _status(tmp_path, (99.0, int(NOW) + 1800), (100.0, int(NOW) + 400_000))
        assert _build(tmp_path)["limit_reset"]["window"] == "seven_day"

    def test_no_snapshot_means_no_reset_time(self, tmp_path: Path) -> None:
        _failure(tmp_path, NOW - 30)
        assert _build(tmp_path)["limit_reset"] is None

    def test_no_window_near_its_limit_is_not_guessed(self, tmp_path: Path) -> None:
        _failure(tmp_path, NOW - 30)
        _status(tmp_path, (40.0, int(NOW) + 1800), (30.0, int(NOW) + 400_000))
        assert _build(tmp_path)["limit_reset"] is None

    def test_an_expired_window_is_not_joined(self, tmp_path: Path) -> None:
        _failure(tmp_path, NOW - 30)
        _status(tmp_path, (100.0, int(NOW) - 1), None)
        assert _build(tmp_path)["limit_reset"] is None

    def test_a_resolved_failure_has_no_reset(self, tmp_path: Path) -> None:
        _failure(tmp_path, NOW - 30)
        resolve_session(tmp_path / STOP_FAILURE_RECORDS_FILENAME, SESSION, now=NOW - 5)
        _status(tmp_path, (100.0, int(NOW) + 1800), None)
        assert _build(tmp_path)["limit_reset"] is None

    def test_a_credential_failure_has_no_reset(self, tmp_path: Path) -> None:
        _failure(tmp_path, NOW - 30, error="authentication_failed")
        _status(tmp_path, (100.0, int(NOW) + 1800), None)
        assert _build(tmp_path)["limit_reset"] is None


class TestDiff:
    def test_observed_at_alone_is_not_a_change(self, tmp_path: Path) -> None:
        before = _build(tmp_path)
        assert ssd.changed_fields(before, {**before, "observed_at": NOW + 5}) == []

    def test_each_differing_field_is_named(self, tmp_path: Path) -> None:
        before = _build(tmp_path)
        _stop_event(tmp_path, SESSION, NOW - 1)
        assert ssd.changed_fields(before, _build(tmp_path)) == ["last_turn_edge"]

    def test_usage_heartbeat_alone_is_not_a_change(self, tmp_path: Path) -> None:
        _status(tmp_path, (40.0, int(NOW) + 3600), None)
        before = _build(tmp_path)
        after = json.loads(json.dumps(before))
        after["usage"]["observed_at"] += 60
        after["usage"]["five_hour"]["observed_at"] += 60
        assert ssd.changed_fields(before, after) == []


class TestWatch:
    def test_first_line_names_every_field_then_only_changes(self, tmp_path: Path) -> None:
        first = _build(tmp_path)
        _stop_event(tmp_path, SESSION, NOW - 1)
        second = _build(tmp_path)
        feed = iter([first, second, {**second, "observed_at": NOW + 9}])
        lines = list(
            ssd.watch_lines(lambda: next(feed), interval=0, sleep=lambda _s: None, max_polls=3)
        )
        every_field = sorted(k for k in first if k not in ("schema_version", "observed_at"))
        assert [line["changed"] for line in lines] == [every_field, ["last_turn_edge"]]
        validator = _validator(state_schemas.SCHEMA_SESSION_STATE_WATCH)
        for line in lines:
            validator.validate(json.loads(json.dumps(line)))
