"""Unit tests for the SubagentStop-time cron enforcer (Plan 00416 Task 1.1).

The SubagentStop sibling of ``cron_stop_enforcer``: a subagent-only session
can reach SubagentStop without the main-thread Stop event ever firing, and
``session_crons`` is conditional here too (``contracts/claude-code-hooks/
Stop.json`` documents the field for both events). Same three contract
constraints as the Stop twin -- see that module's test file for the full
rationale; this file pins the same behaviour on the SubagentStop event.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.subagent_stop.cron_subagent_stop_enforcer import (
    CronSubagentStopEnforcerHandler,
)
from claude_code_hooks_daemon.utils.cron_enforcement import PROMPT_DELIVERY_CAP


class _RootedCronSubagentStopEnforcerHandler(CronSubagentStopEnforcerHandler):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self._workspace_root = root


def _handler(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> CronSubagentStopEnforcerHandler:
    handler = CronSubagentStopEnforcerHandler()
    monkeypatch.setattr(handler, "_load_config", lambda: config)
    return handler


def _config(*jobs: PersistentCronConfig, enabled: bool = True) -> Config:
    return Config(persistent_crons=PersistentCronsConfig(enabled=enabled, jobs=list(jobs)))


def _session_cron(schedule: str, prompt: str, cron_id: str = "c1") -> dict[str, Any]:
    return {"id": cron_id, "schedule": schedule, "recurring": True, "prompt": prompt}


_JOB = PersistentCronConfig(
    id="gh-issue-sdlc",
    schedule="23 * * * *",
    prompt="Invoke the issue-sdlc skill and follow it exactly.",
    description="One GitHub issue through the full SDLC",
)


def _long_prompt(length: int) -> str:
    body = "the issue-sdlc skill handles exactly one issue per tick. "
    return (body * (length // len(body) + 1))[:length]


class TestItStaysSilentWithNothingDeclared:
    def test_a_project_with_no_config_does_not_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, Config())
        assert handler.matches({}) is False

    def test_declared_jobs_with_the_section_off_do_not_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _handler(monkeypatch, _config(_JOB, enabled=False))
        assert handler.matches({}) is False

    def test_an_unreadable_config_degrades_to_silence(self, tmp_path: Path) -> None:
        handler = _RootedCronSubagentStopEnforcerHandler(tmp_path)
        assert handler.matches({}) is False


class TestAbsentSessionCronsNeverBlocks:
    def test_a_missing_session_crons_field_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({})
        assert result.decision is Decision.ALLOW

    def test_an_explicit_null_session_crons_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({"session_crons": None})
        assert result.decision is Decision.ALLOW


class TestADeclaredCronPresentInSessionCronsAllows:
    def test_matching_schedule_and_prompt_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        payload = {"session_crons": [_session_cron(_JOB.schedule, _JOB.prompt)]}

        result = handler.handle(payload)

        assert result.decision is Decision.ALLOW


class TestADeclaredCronAbsentFromSessionCronsBlocks:
    def test_no_matching_entry_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        payload = {"session_crons": [_session_cron("0 9 * * 1-5", "unrelated job")]}

        result = handler.handle(payload)

        assert result.decision is Decision.DENY

    def test_the_deny_reason_names_the_schedule_and_the_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({"session_crons": []})

        assert result.reason is not None
        assert _JOB.schedule in result.reason
        assert _JOB.prompt in result.reason
        assert _JOB.id in result.reason
        assert "CronCreate" in result.reason


class TestAPresentButEmptySessionCronsIsRealInformation:
    def test_an_empty_list_with_a_declared_job_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({"session_crons": []})
        assert result.decision is Decision.DENY

    def test_an_empty_list_with_nothing_declared_allows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _handler(monkeypatch, Config())
        result = handler.handle({"session_crons": []})
        assert result.decision is Decision.ALLOW


class TestALongDeclaredPromptStillMatchesItsTruncatedForm:
    def test_a_prompt_over_the_cap_matches_its_capped_delivered_form(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        long_prompt = _long_prompt(2200)
        job = PersistentCronConfig(id="issue-sdlc", schedule="23 * * * *", prompt=long_prompt)
        handler = _handler(monkeypatch, _config(job))
        delivered = long_prompt[:PROMPT_DELIVERY_CAP] + "... [+1200 chars]"
        payload = {"session_crons": [_session_cron(job.schedule, delivered)]}

        result = handler.handle(payload)

        assert result.decision is Decision.ALLOW


class TestHandlerWiring:
    def test_it_is_enabled_by_default(self) -> None:
        assert CronSubagentStopEnforcerHandler().get_default_enabled() is True

    def test_it_is_terminal(self) -> None:
        assert CronSubagentStopEnforcerHandler().terminal is True
