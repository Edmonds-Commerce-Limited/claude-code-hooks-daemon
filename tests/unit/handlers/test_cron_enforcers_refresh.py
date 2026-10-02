"""Both cron enforcers refresh a job older than ``refresh_after_days`` (Plan 00470 Task 2.2)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.stop.cron_stop_enforcer import CronStopEnforcerHandler
from claude_code_hooks_daemon.handlers.subagent_stop.cron_subagent_stop_enforcer import (
    CronSubagentStopEnforcerHandler,
)
from claude_code_hooks_daemon.utils.cron_records import (
    DEFAULT_REFRESH_AFTER_DAYS,
    SECONDS_PER_DAY,
    CronRecord,
    prompt_fingerprint,
    read_records,
    record_cron,
)
from claude_code_hooks_daemon.utils.cron_refresh import refresh_days_to_seconds

_JOB = PersistentCronConfig(
    id="issue-sdlc", schedule="23 * * * *", prompt="Invoke the issue-sdlc skill and follow it."
)

EnforcerClass = type[CronStopEnforcerHandler] | type[CronSubagentStopEnforcerHandler]


@pytest.fixture(params=[CronStopEnforcerHandler, CronSubagentStopEnforcerHandler])
def enforcer_class(request: pytest.FixtureRequest) -> EnforcerClass:
    cls: EnforcerClass = request.param
    return cls


@pytest.fixture
def records(tmp_path: Path) -> Path:
    return tmp_path / "cron-records.json"


@pytest.fixture
def handler(
    enforcer_class: EnforcerClass, monkeypatch: pytest.MonkeyPatch, records: Path, tmp_path: Path
) -> CronStopEnforcerHandler | CronSubagentStopEnforcerHandler:
    instance = enforcer_class()
    config = Config(persistent_crons=PersistentCronsConfig(enabled=True, jobs=[_JOB]))
    monkeypatch.setattr(instance, "_load_config", lambda: config)
    monkeypatch.setattr(instance, "_records_path", lambda: records)
    monkeypatch.setattr(instance, "_pauses_path", lambda: tmp_path / "cron-pauses.json")
    return instance


def _stop(cron_id: str = "c1") -> dict[str, Any]:
    return {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "session_crons": [
            {"id": cron_id, "schedule": _JOB.schedule, "recurring": True, "prompt": _JOB.prompt}
        ],
    }


def _born_days_ago(records: Path, days: float, cron_id: str = "c1") -> None:
    created = time.time() - days * SECONDS_PER_DAY
    record_cron(
        records,
        CronRecord("s1", cron_id, _JOB.schedule, prompt_fingerprint(_JOB.prompt), created),
        now=created,
    )


class TestTheDefault:
    def test_the_default_option_is_six_days(self, handler: Any) -> None:
        assert handler._refresh_after_days == DEFAULT_REFRESH_AFTER_DAYS == 6.0


class TestAgeBoundaryThroughTheHandler:
    def test_a_job_inside_the_default_is_allowed(self, handler: Any, records: Path) -> None:
        _born_days_ago(records, 5.9)
        assert handler.handle(_stop()).decision is Decision.ALLOW

    def test_a_job_past_the_default_is_denied_naming_the_refresh(
        self, handler: Any, records: Path
    ) -> None:
        _born_days_ago(records, 6.1)
        result = handler.handle(_stop())
        assert result.decision is Decision.DENY
        assert result.reason is not None
        assert "CronDelete c1" in result.reason
        assert "CronCreate" in result.reason

    def test_the_option_moves_the_boundary(self, handler: Any, records: Path) -> None:
        handler._refresh_after_days = 2.0
        _born_days_ago(records, 2.1)
        assert handler.handle(_stop()).decision is Decision.DENY

    @pytest.mark.parametrize("bad", [0.0, -1.0, 7.0, 30.0])
    def test_an_option_that_cannot_work_falls_back_to_the_default(
        self, handler: Any, records: Path, bad: float
    ) -> None:
        handler._refresh_after_days = bad
        _born_days_ago(records, 5.9)
        assert handler.handle(_stop()).decision is Decision.ALLOW
        _born_days_ago(records, 6.1)
        assert handler.handle(_stop()).decision is Decision.DENY


class TestAnUnknownAgeIsStamped:
    def test_an_unrecorded_job_is_allowed_and_stamped(self, handler: Any, records: Path) -> None:
        before = time.time()
        assert handler.handle(_stop()).decision is Decision.ALLOW
        [record] = read_records(records)
        assert (record.session_id, record.cron_id) == ("s1", "c1")
        assert before <= record.created_at <= time.time()


class TestWhatTheHandlerStillRespects:
    def test_a_usage_paused_session_is_not_matched(
        self, handler: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = type(handler).__module__
        monkeypatch.setattr(f"{module}.hook_is_usage_paused", lambda _hook_input: True)
        assert handler.matches(_stop()) is False

    def test_priority_and_terminality_are_unchanged(self, handler: Any) -> None:
        assert (
            handler.priority == Priority.CRON_STOP_ENFORCER == Priority.CRON_SUBAGENT_STOP_ENFORCER
        )
        assert handler.priority == 7
        assert handler.terminal is False

    def test_a_missing_job_still_denies_naming_create_only(self, handler: Any) -> None:
        payload = _stop()
        payload["session_crons"] = []
        result = handler.handle(payload)
        assert result.decision is Decision.DENY
        assert result.reason is not None and "MISSING" in result.reason

    def test_the_guidance_documents_the_option(self, handler: Any) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None and "refresh_after_days" in guidance


class TestDaysToSeconds:
    def test_a_valid_value_converts(self) -> None:
        assert refresh_days_to_seconds(1.5) == 1.5 * SECONDS_PER_DAY

    def test_an_invalid_value_logs_and_uses_the_default(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert refresh_days_to_seconds(9) == DEFAULT_REFRESH_AFTER_DAYS * SECONDS_PER_DAY
        assert "refresh_after_days" in caplog.text
