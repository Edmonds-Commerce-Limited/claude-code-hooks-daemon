"""Tests for UsagePauseStopGateHandler (Plan 00479 Task 4.3).

A paused session may stop only once its ``session_crons`` holds exactly ONE cron,
the usage-resume cron. Otherwise the directive is repeated, as
``cron_stop_enforcer`` does for declared crons.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.stop.usage_pause_stop_gate import (
    UsagePauseStopGateHandler,
)
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    UsagePause,
    write_usage_pause,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import USAGE_RESUME_PROMPT

_SESSION = "sess-1"


def _record(tmp_path: Path, *, session: str = _SESSION) -> None:
    now = time.time()
    write_usage_pause(
        tmp_path,
        UsagePause(
            session_id=session,
            paused_at=now - 60,
            resume_at=now + 3600,
            window=WINDOW_FIVE_HOUR,
            used_percentage=91.0,
            ceiling=80.0,
            reason="five_hour window at 91% (ceiling 80%)",
        ),
    )


def _cron(prompt: str, cron_id: str = "c1", schedule: str = "30 14 2 10 *") -> dict[str, Any]:
    return {"id": cron_id, "schedule": schedule, "recurring": False, "prompt": prompt}


def _stop(
    crons: list[dict[str, Any]] | None, *, active: bool = False, session: str = _SESSION
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "Stop",
        "session_id": session,
        "stop_hook_active": active,
    }
    if crons is not None:
        payload["session_crons"] = crons
    return payload


def _decide(tmp_path: Path, hook_input: dict[str, Any]) -> Any:
    handler = UsagePauseStopGateHandler()
    with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
        if not handler.matches(hook_input):
            return None
        return handler.handle(hook_input)


class TestInit:
    def test_identity_and_priority(self) -> None:
        handler = UsagePauseStopGateHandler()
        assert handler.name == HandlerID.USAGE_PAUSE_STOP_GATE.display_name
        assert handler.priority == Priority.USAGE_PAUSE_STOP_GATE

    def test_runs_before_the_terminal_catch_all_and_does_not_shadow_it(self) -> None:
        handler = UsagePauseStopGateHandler()
        assert handler.terminal is False
        assert handler.priority < Priority.CRON_STOP_ENFORCER


class TestPaused:
    def test_exactly_the_resume_cron_allows_the_stop(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop([_cron(USAGE_RESUME_PROMPT)]))
        assert result is not None
        assert result.decision == Decision.ALLOW

    def test_a_truncated_resume_prompt_still_counts(self, tmp_path: Path) -> None:
        _record(tmp_path)
        prompt = USAGE_RESUME_PROMPT + " ... [+1200 chars]"
        result = _decide(tmp_path, _stop([_cron(prompt)]))
        assert result is not None
        assert result.decision == Decision.ALLOW

    def test_no_crons_at_all_is_refused(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop([]))
        assert result.decision == Decision.DENY
        assert "0 crons" in result.reason
        assert "CronCreate" in result.reason

    def test_extra_crons_alongside_the_resume_cron_are_refused(self, tmp_path: Path) -> None:
        _record(tmp_path)
        crons = [_cron(USAGE_RESUME_PROMPT), _cron("[tick:failsafe]\nx", "c2", "47 * * * *")]
        result = _decide(tmp_path, _stop(crons))
        assert result.decision == Decision.DENY
        assert "2 crons" in result.reason
        assert "CronDelete" in result.reason

    def test_one_cron_that_is_not_the_resume_cron_is_refused(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop([_cron("[tick:failsafe]\nx", "c2", "47 * * * *")]))
        assert result.decision == Decision.DENY
        assert "1 cron," in result.reason

    def test_two_resume_crons_are_refused(self, tmp_path: Path) -> None:
        _record(tmp_path)
        crons = [_cron(USAGE_RESUME_PROMPT), _cron(USAGE_RESUME_PROMPT, "c2")]
        assert _decide(tmp_path, _stop(crons)).decision == Decision.DENY

    def test_absent_session_crons_is_no_information_and_allows(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop(None))
        assert result.decision == Decision.ALLOW

    def test_re_entry_allows_so_the_session_is_never_trapped(
        self, tmp_path: Path, caplog: Any
    ) -> None:
        _record(tmp_path)
        with caplog.at_level("WARNING"):
            result = _decide(tmp_path, _stop([], active=True))
        assert result.decision == Decision.ALLOW
        assert "usage pause" in caplog.text.lower()

    def test_the_deny_names_the_resume_cron_expression(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _stop([]))
        assert "recurring: false" in result.reason
        assert "[tick:usage-resume]" in result.reason


class TestNotPaused:
    def test_does_not_match(self, tmp_path: Path) -> None:
        assert _decide(tmp_path, _stop([])) is None

    def test_other_session_does_not_match(self, tmp_path: Path) -> None:
        _record(tmp_path, session="someone-else")
        assert _decide(tmp_path, _stop([])) is None

    def test_no_project_context_fails_open(self) -> None:
        handler = UsagePauseStopGateHandler()
        with patch.object(ProjectContext, "daemon_untracked_dir", side_effect=RuntimeError("x")):
            assert handler.matches(_stop([])) is False


class TestMetadata:
    def test_rule(self) -> None:
        assert [r.rule_id for r in UsagePauseStopGateHandler().get_rules()] == [
            "R-USAGE-PAUSE-STOP"
        ]

    def test_acceptance_tests_declare_what_the_harness_cannot_drive(self) -> None:
        tests = UsagePauseStopGateHandler().get_acceptance_tests()
        denies = [t for t in tests if t.expected_decision == Decision.DENY]
        allows = [t for t in tests if t.expected_decision == Decision.ALLOW]
        assert denies and allows
        assert all(t.harness_cannot_produce for t in denies)
        assert not any(t.harness_cannot_produce for t in allows)

    def test_guidance_is_resident(self) -> None:
        text = UsagePauseStopGateHandler().get_claude_md()
        assert text is not None
        assert "usage_pause_stop_gate" in text
