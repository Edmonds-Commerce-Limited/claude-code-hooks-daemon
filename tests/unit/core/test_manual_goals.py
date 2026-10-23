"""Tests for the manual-goals mode operations (Plan 00501 Task 8.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.manual_goals import (
    GoalsChange,
    GoalsCommand,
    GoalsOutcome,
    enter_manual_goals,
    exit_manual_goals,
    goal_intent_suppressed,
    parse_goals_command,
)
from claude_code_hooks_daemon.core.session_mode_log import TransitionAction, TransitionLog
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.utils.session_modes import (
    MANUAL_GOALS_RETENTION_SECONDS,
    ModeLabel,
    ModeSource,
)

SID = "session-manual"
OTHER = "session-auto"
T0 = 1_000_000.0


@pytest.fixture
def registry(tmp_path: Path) -> SessionModeRegistry:
    log = TransitionLog(tmp_path / "transitions.jsonl")
    reg = SessionModeRegistry(tmp_path / "modes", clock=lambda: T0, transition_log=log)
    reg.load()
    return reg


def _actions(registry: SessionModeRegistry) -> list[TransitionAction]:
    log = registry.transition_log
    assert log is not None
    return [t.action for t in log.recent(50, session_id=SID)]


class TestEnter:
    def test_entering_stores_the_mode_and_logs_it(self, registry: SessionModeRegistry) -> None:
        change = enter_manual_goals(
            registry, SID, source=ModeSource.HUMAN, evidence="clear=u1 record=none"
        )
        assert change.outcome is GoalsOutcome.ENTERED
        (entry,) = registry.active(SID)
        assert entry.label is ModeLabel.MANUAL_GOALS
        assert entry.source is ModeSource.HUMAN
        assert entry.expires_at == T0 + MANUAL_GOALS_RETENTION_SECONDS
        assert _actions(registry) == [TransitionAction.ENTER]

    def test_entering_twice_neither_re_enters_nor_logs_again(
        self, registry: SessionModeRegistry
    ) -> None:
        enter_manual_goals(registry, SID, source=ModeSource.HUMAN, evidence="first")
        change = enter_manual_goals(registry, SID, source=ModeSource.HUMAN, evidence="second")
        assert change.outcome is GoalsOutcome.ALREADY_MANUAL
        assert _actions(registry) == [TransitionAction.ENTER]

    def test_the_mode_is_per_session(self, registry: SessionModeRegistry) -> None:
        enter_manual_goals(registry, SID, source=ModeSource.HUMAN, evidence="e")
        assert goal_intent_suppressed(registry, SID) is True
        assert goal_intent_suppressed(registry, OTHER) is False


class TestExit:
    def test_exiting_removes_the_mode_and_logs_it(self, registry: SessionModeRegistry) -> None:
        enter_manual_goals(registry, SID, source=ModeSource.HUMAN, evidence="e")
        change = exit_manual_goals(registry, SID, evidence="the human switched back")
        assert change.outcome is GoalsOutcome.EXITED
        assert registry.active(SID) == ()
        assert goal_intent_suppressed(registry, SID) is False
        assert _actions(registry) == [TransitionAction.ENTER, TransitionAction.EXIT]

    def test_exiting_when_not_manual_changes_nothing(self, registry: SessionModeRegistry) -> None:
        change = exit_manual_goals(registry, SID, evidence="e")
        assert change.outcome is GoalsOutcome.NOT_MANUAL
        assert _actions(registry) == []


class TestLines:
    def test_the_entry_line_names_what_changes_and_what_does_not(self) -> None:
        line = GoalsChange(GoalsOutcome.ENTERED).line()
        assert line.startswith("MANUAL GOALS ON:")
        assert "automated goal injection is off" in line
        assert "`continue`" in line
        assert "/goal <condition>" in line
        assert "hooks-daemon goals on" in line

    def test_the_entry_line_does_not_promise_the_loop_breaker_is_gated(self) -> None:
        """Plan 00474 review D5: only plan-driven clears are gated, not the goal-loop detector's."""
        line = GoalsChange(GoalsOutcome.ENTERED).line()
        assert "no automated clear removes a goal" not in line
        assert "no plan-driven clear removes a goal" in line
        assert "goal-loop detector" in line

    def test_already_manual_says_so(self) -> None:
        assert "already" in GoalsChange(GoalsOutcome.ALREADY_MANUAL).line()

    def test_the_exit_line_says_automated_goals_resume(self) -> None:
        line = GoalsChange(GoalsOutcome.EXITED).line()
        assert line.startswith("MANUAL GOALS OFF:")
        assert "automated goal injection applies" in line

    def test_not_manual_says_there_was_nothing_to_end(self) -> None:
        assert "nothing to end" in GoalsChange(GoalsOutcome.NOT_MANUAL).line()


class TestParseGoalsCommand:
    @pytest.mark.parametrize(
        "prompt",
        ["hooks-daemon goals off", "Hooks Demon goals manual", "hooks daemon goals OFF."],
    )
    def test_off_and_manual_ask_for_manual_goals(self, prompt: str) -> None:
        assert parse_goals_command(prompt) == GoalsCommand(manual=True)

    @pytest.mark.parametrize(
        "prompt", ["hooks-daemon goals on", "hooks-daemon goals auto", "hooks demon goals Auto!"]
    )
    def test_on_and_auto_ask_for_automated_goals(self, prompt: str) -> None:
        assert parse_goals_command(prompt) == GoalsCommand(manual=False)

    @pytest.mark.parametrize(
        "prompt",
        [
            "please hooks-daemon goals off",
            "hooks-daemon goals",
            "hooks-daemon goals sideways",
            "hooks-daemon goals off and then fix the bug",
            "hooks-daemon focus off",
            "🤖 [ccy-supervisor] hooks-daemon goals off",
            "[tick:failsafe]\nhooks-daemon goals off",
        ],
    )
    def test_anything_else_is_not_a_goals_command(self, prompt: str) -> None:
        assert parse_goals_command(prompt) is None

    def test_a_non_string_is_not_a_command(self) -> None:
        assert parse_goals_command(7) is None
