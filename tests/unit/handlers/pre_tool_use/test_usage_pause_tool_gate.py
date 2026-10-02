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
    @pytest.mark.parametrize(
        "tool", ["CronList", "CronDelete", "CronCreate", "SendMessage", "TaskStop"]
    )
    def test_cron_and_wind_up_tools_are_left_alone(self, tmp_path: Path, tool: str) -> None:
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


class TestToolSearchIsAllowed:
    """Plan 00479 C1: the cron tools are deferred, so ToolSearch must pass while paused."""

    def test_tool_search_is_left_alone(self, tmp_path: Path) -> None:
        _record(tmp_path)
        assert _decide(tmp_path, _input("ToolSearch")) is None


class TestFailsOpenOnAReadError:
    """Plan 00479 M1: a broken record must never deny a tool."""

    @pytest.mark.parametrize("error", [PermissionError("EACCES"), OSError("x"), ValueError("y")])
    def test_matches_does_not_raise_and_does_not_match(self, error: Exception) -> None:
        handler = UsagePauseToolGateHandler()
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=Path("/nonexistent")),
            patch(
                "claude_code_hooks_daemon.utils.usage_pause_gate.read_usage_pause",
                side_effect=error,
            ),
        ):
            assert handler.matches(_input("Bash")) is False


_NOW = 1_790_000_000.0


def _over_the_ceiling(handler: UsagePauseToolGateHandler, *, five: float = 95.0) -> None:
    from claude_code_hooks_daemon.config.models import Config, HostConfig, UsageCeilingConfig
    from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
    from claude_code_hooks_daemon.utils.usage_pause_gate import PauseEnvironment

    config = Config(
        hosts={"runner": HostConfig(usage_ceiling=UsageCeilingConfig(max_used_percent=80))}
    )
    snapshot = UsageSnapshot(
        five_hour=UsageWindow(five, int(_NOW + 3 * 3600), _NOW), seven_day=None
    )
    handler._env = PauseEnvironment(
        clock=lambda: _NOW, config_loader=lambda: config, usage_loader=lambda _n: snapshot
    )


class TestEntryFromTheToolGate:
    """Plan 00479 M3: a session kept going by Stop continuations never sees a new prompt."""

    def _hook(self, tool: str = "Bash") -> dict[str, Any]:
        return {
            "tool_name": tool,
            "tool_input": {},
            "session_id": _SESSION,
            "hooks_daemon_hostname": "runner",
        }

    def test_the_call_that_starts_a_pause_is_denied_without_halting_and_carries_the_directive(
        self, tmp_path: Path
    ) -> None:
        """Round 2 N2: a halt would end the turn with the directive unread."""
        from claude_code_hooks_daemon.utils.usage_pause import read_usage_pause

        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._hook()) is True
            result = handler.handle(self._hook())
            assert read_usage_pause(tmp_path, _SESSION, now=_NOW) is not None
        assert result.decision == Decision.DENY
        assert result.halt_turn is False
        assert "continue" not in result.to_json("PreToolUse")
        reason = result.reason or ""
        assert "USAGE CEILING REACHED" in reason
        assert "CronCreate" in reason

    def test_the_next_non_cron_call_after_the_entry_halts(self, tmp_path: Path) -> None:
        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._hook()) is True
            assert handler.handle(self._hook()).halt_turn is False
            assert handler.matches(self._hook("Read")) is True
            second = handler.handle(self._hook("Read"))
        assert second.halt_turn is True

    def _subagent_hook(self, tool: str = "Bash") -> dict[str, Any]:
        return {**self._hook(tool), "agent_id": "a1", "agent_type": "general-purpose"}

    def test_a_subagent_over_the_ceiling_starts_the_pause_but_its_call_is_not_denied(
        self, tmp_path: Path
    ) -> None:
        """Round 4 R3-1: subagent activity must not keep the session from pausing, and
        in-flight subagents are never rug-pulled."""
        from claude_code_hooks_daemon.utils.usage_pause import read_usage_pause

        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._subagent_hook()) is False
            record = read_usage_pause(tmp_path, _SESSION, now=_NOW)
        assert record is not None
        assert record.session_id == _SESSION

    def test_every_call_of_a_subagent_over_the_ceiling_is_allowed(self, tmp_path: Path) -> None:
        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            decisions = [handler.matches(self._subagent_hook(t)) for t in ("Bash", "Read", "Edit")]
        assert decisions == [False, False, False]

    def test_a_subagent_below_the_ceiling_writes_no_record(self, tmp_path: Path) -> None:
        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler, five=10.0)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._subagent_hook()) is False
            assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_an_owner_override_stops_a_subagent_starting_the_pause(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.utils.usage_pause import write_usage_override

        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        write_usage_override(tmp_path, _SESSION, until=_NOW + 3600, now=_NOW)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._subagent_hook()) is False
            assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_the_main_threads_next_call_after_a_subagent_started_the_pause_gets_the_directive(
        self, tmp_path: Path
    ) -> None:
        """The main thread never saw the directive: a plain deny carrying it, no halt."""
        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._subagent_hook()) is False
            assert handler.matches(self._hook("Read")) is True
            first = handler.handle(self._hook("Read"))
            assert handler.matches(self._hook("Read")) is True
            second = handler.handle(self._hook("Read"))
        assert first.decision == Decision.DENY
        assert first.halt_turn is False
        assert "USAGE CEILING REACHED" in (first.reason or "")
        assert second.halt_turn is True

    def test_a_subagent_in_a_paused_session_is_not_denied_either(self, tmp_path: Path) -> None:
        """Round 4 R3-1 (owner ruling): in-flight subagents finish; the main thread winds them up."""
        _record(tmp_path)
        handler = UsagePauseToolGateHandler()
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._subagent_hook()) is False

    def test_a_subagent_may_still_use_the_allowed_tools(self, tmp_path: Path) -> None:
        _record(tmp_path)
        handler = UsagePauseToolGateHandler()
        hook = {**self._hook("ToolSearch"), "agent_id": "a1"}
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(hook) is False

    def test_a_record_that_cannot_be_read_back_never_denies_anything(self, tmp_path: Path) -> None:
        """Round 2 N3 (reviewer probe P2b): writable but unreadable must not loop."""
        real_read = Path.read_text

        def unreadable_record(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name.endswith(".usage-paused"):
                raise PermissionError("denied")
            return real_read(self, *args, **kwargs)

        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        with (
            patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path),
            patch.object(Path, "read_text", unreadable_record),
        ):
            assert handler.matches(self._hook()) is False
            assert handler.matches(self._hook("Read")) is False

    def test_an_owner_override_stops_the_entry(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.utils.usage_pause import write_usage_override

        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        write_usage_override(tmp_path, _SESSION, until=_NOW + 3600, now=_NOW)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._hook()) is False

    def test_a_cron_tool_does_not_trigger_the_entry(self, tmp_path: Path) -> None:
        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._hook("CronList")) is False
            assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_below_the_ceiling_nothing_happens(self, tmp_path: Path) -> None:
        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler, five=10.0)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._hook()) is False

    def test_no_session_id_never_pauses(self, tmp_path: Path) -> None:
        handler = UsagePauseToolGateHandler()
        _over_the_ceiling(handler)
        hook = self._hook()
        del hook["session_id"]
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(hook) is False
            assert list(tmp_path.rglob("*.usage-paused")) == []

    def test_a_config_that_cannot_be_evaluated_fails_open(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.utils.usage_pause_gate import PauseEnvironment

        def boom() -> Any:
            raise OSError("config unreadable")

        handler = UsagePauseToolGateHandler()
        handler._env = PauseEnvironment(config_loader=boom)
        with patch.object(ProjectContext, "daemon_untracked_dir", return_value=tmp_path):
            assert handler.matches(self._hook()) is False
