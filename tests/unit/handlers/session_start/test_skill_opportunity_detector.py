"""Tests for the skill_opportunity_detector SessionStart handler (Plan 00274).

The handler does file-stat work only: it checks the TTL state file and, when
a scan is due, injects an advisory pointing at the ``skill-scan`` CLI. It is
advisory, non-terminal, and can never fail session start.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.session_start.skill_opportunity_detector import (
    SkillOpportunityDetectorHandler,
)
from claude_code_hooks_daemon.skill_scan.constants import STATE_FILE_NAME
from claude_code_hooks_daemon.skill_scan.state import record_attempt, record_success

_STATE_DIR_TARGET = (
    "claude_code_hooks_daemon.handlers.session_start.skill_opportunity_detector."
    "SkillOpportunityDetectorHandler._state_dir"
)


def _hook_input(source: str = "startup") -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "source": source}


def _handler(enabled: bool = True) -> SkillOpportunityDetectorHandler:
    handler = SkillOpportunityDetectorHandler()
    handler.configure({"enabled": enabled})
    return handler


class TestInit:
    def test_identity(self) -> None:
        handler = SkillOpportunityDetectorHandler()
        assert handler.name == "skill-opportunity-detector"
        assert handler.priority == Priority.SKILL_OPPORTUNITY_DETECTOR
        assert handler.terminal is False

    def test_no_resident_guidance_and_acceptance_tests_present(self) -> None:
        # T4 verdict: the fire-time advisory carries the whole remedy, so no
        # resident CLAUDE.md section is emitted (see the guidance coverage
        # integration suite's exemption table).
        handler = SkillOpportunityDetectorHandler()
        assert handler.get_claude_md() is None
        assert handler.get_acceptance_tests()


class TestMatches:
    def test_matches_new_session(self) -> None:
        assert _handler().matches(_hook_input()) is True

    def test_skips_resume_session(self) -> None:
        target = (
            "claude_code_hooks_daemon.handlers.session_start."
            "skill_opportunity_detector.is_resume_session"
        )
        with patch(target, return_value=True):
            assert _handler().matches(_hook_input()) is False

    def test_skips_when_disabled(self) -> None:
        assert _handler(enabled=False).matches(_hook_input()) is False

    def test_skips_wrong_event(self) -> None:
        assert _handler().matches({"hook_event_name": "Stop"}) is False

    def test_skips_none_and_non_dict(self) -> None:
        handler = _handler()
        assert handler.matches(None) is False


class TestHandle:
    def test_due_scan_advises_cli(self, tmp_path: Path) -> None:
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        assert result.decision == Decision.ALLOW
        assert any("skill-scan" in line for line in result.context)

    def test_recent_scan_is_silent(self, tmp_path: Path) -> None:
        record_success(tmp_path / STATE_FILE_NAME, report_path="/r.md")
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        assert result.context == []

    def test_recent_failed_attempt_is_silent(self, tmp_path: Path) -> None:
        record_attempt(tmp_path / STATE_FILE_NAME)
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        assert result.context == []

    def test_corrupt_state_counts_as_due(self, tmp_path: Path) -> None:
        (tmp_path / STATE_FILE_NAME).write_text("{corrupt")
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = _handler().handle(_hook_input())
        assert any("skill-scan" in line for line in result.context)

    def test_interval_option_respected(self, tmp_path: Path) -> None:
        import time

        two_days_ago = time.time() - 2 * 86_400
        record_success(tmp_path / STATE_FILE_NAME, report_path="/r.md", now=two_days_ago)
        handler = _handler()
        handler.configure({"options": {"check_interval_days": 1}})
        with patch(_STATE_DIR_TARGET, return_value=tmp_path):
            result = handler.handle(_hook_input())
        assert any("skill-scan" in line for line in result.context)

    def test_state_dir_failure_never_raises(self) -> None:
        with patch(_STATE_DIR_TARGET, side_effect=OSError("boom")):
            result = _handler().handle(_hook_input())
        assert result.decision == Decision.ALLOW
        assert result.context == []
