"""Tests for UsagePauseToolGateHandler (Plan 00479 Task 4.2).

While a session is paused on its usage ceiling it may use only CronList,
CronDelete and CronCreate. Any other tool is denied WITH ``continue: false`` and
a ``stopReason``, so a turn already running halts at its next tool call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.pre_tool_use.usage_pause_tool_gate import (
    UsagePauseToolGateHandler,
)
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    UsagePause,
    write_usage_pause,
)

_SESSION = "sess-1"


def _record(tmp_path: Path, *, session: str = _SESSION) -> None:
    import time

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


def _input(tool: str, session: str = _SESSION) -> dict[str, Any]:
    return {"tool_name": tool, "tool_input": {}, "session_id": session}


def _decide(tmp_path: Path, hook_input: dict[str, Any]) -> Any:
    handler = UsagePauseToolGateHandler()
    with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
        if not handler.matches(hook_input):
            return None
        return handler.handle(hook_input)


class TestInit:
    def test_identity_and_priority(self) -> None:
        handler = UsagePauseToolGateHandler()
        assert handler.name == HandlerID.USAGE_PAUSE_TOOL_GATE.display_name
        assert handler.priority == Priority.USAGE_PAUSE_TOOL_GATE

    def test_terminal_because_its_deny_is_the_final_word(self) -> None:
        assert UsagePauseToolGateHandler().terminal is True


class TestWhilePaused:
    @pytest.mark.parametrize("tool", ["CronList", "CronDelete", "CronCreate"])
    def test_cron_tools_are_left_alone(self, tmp_path: Path, tool: str) -> None:
        _record(tmp_path)
        assert _decide(tmp_path, _input(tool)) is None

    @pytest.mark.parametrize("tool", ["Bash", "Read", "Write", "Edit", "Task", "Agent", "Skill"])
    def test_every_other_tool_is_denied_and_halts_the_turn(self, tmp_path: Path, tool: str) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _input(tool))
        assert result is not None
        assert result.decision == Decision.DENY
        assert result.halt_turn is True
        assert result.stop_reason
        assert "paused" in result.stop_reason.lower()

    def test_the_wire_response_carries_continue_false_and_a_stop_reason(
        self, tmp_path: Path
    ) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _input("Bash"))
        assert result is not None
        wire = result.to_json("PreToolUse")
        assert wire["continue"] is False
        assert wire["stopReason"]
        assert wire["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_the_deny_reason_names_the_allowed_tools(self, tmp_path: Path) -> None:
        _record(tmp_path)
        result = _decide(tmp_path, _input("Bash"))
        assert result is not None
        for tool in ("CronList", "CronDelete", "CronCreate"):
            assert tool in result.reason


class TestNotPaused:
    def test_no_record_means_every_tool_passes(self, tmp_path: Path) -> None:
        assert _decide(tmp_path, _input("Bash")) is None

    def test_another_session_is_unaffected(self, tmp_path: Path) -> None:
        _record(tmp_path, session="someone-else")
        assert _decide(tmp_path, _input("Bash")) is None

    def test_no_project_context_fails_open(self) -> None:
        handler = UsagePauseToolGateHandler()
        with patch.object(ProjectContext, "daemon_untracked_dir", side_effect=RuntimeError("x")):
            assert handler.matches(_input("Bash")) is False

    def test_a_missing_tool_name_is_not_judged_without_a_pause(self, tmp_path: Path) -> None:
        assert _decide(tmp_path, {"session_id": _SESSION}) is None


class TestMetadata:
    def test_rule(self) -> None:
        assert [r.rule_id for r in UsagePauseToolGateHandler().get_rules()] == [
            "R-USAGE-PAUSE-TOOL"
        ]

    def test_acceptance_tests_declare_what_the_harness_cannot_drive(self) -> None:
        tests = UsagePauseToolGateHandler().get_acceptance_tests()
        denies = [t for t in tests if t.expected_decision == Decision.DENY]
        allows = [t for t in tests if t.expected_decision == Decision.ALLOW]
        assert denies and allows
        assert all(t.harness_cannot_produce for t in denies)
        assert not any(t.harness_cannot_produce for t in allows)

    def test_guidance_is_resident(self) -> None:
        text = UsagePauseToolGateHandler().get_claude_md()
        assert text is not None
        assert "usage_pause_tool_gate" in text
