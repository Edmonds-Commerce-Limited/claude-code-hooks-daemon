"""Focus mode: the prompt command, entering and leaving it, and its wording (Plan 00501 Phase 3).

The prompt command is anchored to the start of the prompt, case-insensitive,
tolerant of speech-to-text spellings, and only a genuine human prompt counts.
Entering focus clears an existing goal once; changing the task does not clear
it again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.focus_mode import (
    FOCUS_OFF_ALIASES,
    FocusOutcome,
    enter_focus,
    exit_focus,
    failsafe_focus_line,
    focus_reminder,
    parse_focus_command,
)
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.utils.session_modes import (
    FOCUS_TTL_SECONDS,
    Lifetime,
    ModeLabel,
    ModeSource,
)

_SESSION = "sess-focus"
_NOW = 1_000_000.0


@pytest.fixture
def registry(tmp_path: Path) -> SessionModeRegistry:
    reg = SessionModeRegistry(tmp_path / "modes", clock=lambda: _NOW)
    reg.load()
    return reg


class _GoalClearer:
    """Records each goal clear and answers with ``succeeds``."""

    def __init__(self, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.calls: list[str] = []

    def __call__(self, session_id: str) -> bool:
        self.calls.append(session_id)
        return self.succeeds


class TestParseFocusCommand:
    @pytest.mark.parametrize(
        "prompt",
        [
            "hooks-daemon focus fix the parser",
            "Hooks-Daemon FOCUS fix the parser",
            "hooks daemon focus fix the parser",
            "hooks demon focus fix the parser",
            "Hooks Demon focus fix the parser",
            "  hooks-daemon focus fix the parser  ",
            "hooks-daemon  focus\tfix the parser",
        ],
    )
    def test_spellings_turn_focus_on_with_the_task(self, prompt: str) -> None:
        command = parse_focus_command(prompt)
        assert command is not None
        assert command.task == "fix the parser"
        assert command.is_off is False

    @pytest.mark.parametrize("alias", sorted(FOCUS_OFF_ALIASES))
    def test_off_and_its_aliases_turn_focus_off(self, alias: str) -> None:
        for prompt in (f"hooks-daemon focus {alias}", f"Hooks Demon Focus {alias.upper()}."):
            command = parse_focus_command(prompt)
            assert command is not None
            assert command.is_off is True

    def test_the_aliases_are_exactly_the_four_named(self) -> None:
        assert FOCUS_OFF_ALIASES == frozenset({"off", "done", "end", "disable"})

    def test_an_alias_starting_a_longer_task_is_a_task(self) -> None:
        command = parse_focus_command("hooks-daemon focus end-to-end tests for the parser")
        assert command is not None
        assert command.is_off is False
        assert command.task == "end-to-end tests for the parser"

    def test_a_bare_command_has_no_task(self) -> None:
        command = parse_focus_command("hooks-daemon focus")
        assert command is not None
        assert command.is_off is False
        assert command.task == ""

    @pytest.mark.parametrize(
        "prompt",
        [
            "please run hooks-daemon focus fix the parser",
            "hooks-daemon focused work",
            "hooks-daemon status",
            "hooksdaemon focus x",
            "",
        ],
    )
    def test_not_a_command(self, prompt: str) -> None:
        assert parse_focus_command(prompt) is None

    def test_a_non_string_is_not_a_command(self) -> None:
        assert parse_focus_command(None) is None
        assert parse_focus_command(42) is None

    def test_machine_traffic_is_not_a_command(self) -> None:
        """Reuses the Task 1.2 classifier: a tick or supervisor line never toggles focus."""
        assert parse_focus_command("[tick:failsafe]\nhooks-daemon focus x") is None

    def test_a_multi_line_prompt_keeps_the_whole_task(self) -> None:
        command = parse_focus_command("hooks-daemon focus fix the parser\nand its tests")
        assert command is not None
        assert command.task == "fix the parser\nand its tests"


class TestEnterFocus:
    def test_entering_stores_a_human_session_lifetime_focus(
        self, registry: SessionModeRegistry
    ) -> None:
        clearer = _GoalClearer()
        change = enter_focus(registry, _SESSION, "fix the parser", clear_goal=clearer)
        assert change.outcome is FocusOutcome.ENTERED
        (entry,) = registry.active(_SESSION)
        assert entry.label is ModeLabel.FOCUS
        assert entry.detail == "fix the parser"
        assert entry.source is ModeSource.HUMAN
        assert entry.lifetime is Lifetime.SESSION
        assert entry.expires_at == _NOW + FOCUS_TTL_SECONDS

    def test_entering_clears_the_goal_once(self, registry: SessionModeRegistry) -> None:
        clearer = _GoalClearer()
        enter_focus(registry, _SESSION, "first", clear_goal=clearer)
        change = enter_focus(registry, _SESSION, "second", clear_goal=clearer)
        assert clearer.calls == [_SESSION]
        assert change.outcome is FocusOutcome.CHANGED
        assert registry.policy(_SESSION).focus_task == "second"

    def test_re_entering_after_off_clears_again(self, registry: SessionModeRegistry) -> None:
        clearer = _GoalClearer()
        enter_focus(registry, _SESSION, "first", clear_goal=clearer)
        exit_focus(registry, _SESSION)
        enter_focus(registry, _SESSION, "second", clear_goal=clearer)
        assert clearer.calls == [_SESSION, _SESSION]

    def test_the_entry_line_states_the_task_and_the_goal_clear(
        self, registry: SessionModeRegistry
    ) -> None:
        line = enter_focus(registry, _SESSION, "fix the parser", clear_goal=_GoalClearer()).line()
        assert "\n" not in line
        assert "the active task is 'fix the parser'; other plans are out of scope" in line
        assert "supervisor types `/goal clear` at its next idle" in line
        assert "a human must type `/goal clear`" in line
        assert "hooks-daemon focus off" in line

    def test_a_failed_goal_clear_is_stated_and_logged(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        change = enter_focus(registry, _SESSION, "x", clear_goal=_GoalClearer(succeeds=False))
        assert change.goal_cleared is False
        assert "could not signal the goal clear" in change.line()
        assert "type `/goal clear`" in change.line()
        assert any(r.levelname == "WARNING" and "goal" in r.getMessage() for r in caplog.records)

    def test_the_changed_line_names_the_new_task_without_a_clear(
        self, registry: SessionModeRegistry
    ) -> None:
        clearer = _GoalClearer()
        enter_focus(registry, _SESSION, "first", clear_goal=clearer)
        line = enter_focus(registry, _SESSION, "second", clear_goal=clearer).line()
        assert "'second'" in line
        assert "/goal clear" not in line

    def test_a_blank_task_is_refused_without_a_mode(self, registry: SessionModeRegistry) -> None:
        clearer = _GoalClearer()
        change = enter_focus(registry, _SESSION, "   ", clear_goal=clearer)
        assert change.outcome is FocusOutcome.NEEDS_TASK
        assert "hooks-daemon focus <task>" in change.line()
        assert registry.active(_SESSION) == ()
        assert clearer.calls == []

    def test_other_sessions_are_untouched(self, registry: SessionModeRegistry) -> None:
        enter_focus(registry, _SESSION, "x", clear_goal=_GoalClearer())
        assert registry.active("another") == ()


class TestExitFocus:
    def test_exit_removes_focus(self, registry: SessionModeRegistry) -> None:
        enter_focus(registry, _SESSION, "fix the parser", clear_goal=_GoalClearer())
        change = exit_focus(registry, _SESSION)
        assert change.outcome is FocusOutcome.EXITED
        assert registry.active(_SESSION) == ()
        assert "FOCUS MODE OFF" in change.line()
        assert "'fix the parser'" in change.line()

    def test_exit_when_not_focused_says_so(self, registry: SessionModeRegistry) -> None:
        change = exit_focus(registry, _SESSION)
        assert change.outcome is FocusOutcome.NOT_FOCUSED
        assert "was not on" in change.line()


class TestWording:
    def test_failsafe_line_is_the_ruled_wording(self) -> None:
        assert (
            failsafe_focus_line("fix the parser")
            == "focus mode: the active task is fix the parser; other plans are out of scope"
        )

    def test_focus_reminder_is_one_line_naming_the_task(self) -> None:
        reminder = focus_reminder("fix the parser")
        assert "\n" not in reminder
        assert "fix the parser" in reminder
        assert "other plans are out of scope" in reminder
