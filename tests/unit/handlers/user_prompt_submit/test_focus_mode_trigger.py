"""Tests for FocusModeTriggerHandler (Plan 00501 Task 3.1).

A genuine human prompt opening with ``hooks-daemon focus <task>`` turns focus
on for that session, ``hooks-daemon focus off`` (or an alias) turns it off, and
each emits exactly one context line. Every genuine prompt renews focus; one-time
notices (an expiry) are stated at the next prompt. Driven through the real
session-modes registry.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from tests.support.autonomy import focus_entry, pin_session_modes

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.focus_mode_trigger import (
    FocusModeTriggerHandler,
)
from claude_code_hooks_daemon.utils import usage_pause
from claude_code_hooks_daemon.utils.session_modes import (
    FOCUS_TTL_SECONDS,
    ModeSource,
    SessionMode,
    SessionModeEntry,
)
from claude_code_hooks_daemon.utils.session_signal_paths import SIGNAL_SUBDIR

_MODULE = "claude_code_hooks_daemon.handlers.user_prompt_submit.focus_mode_trigger"
_SESSION = "sess-1"
_CLEAR_TARGET = (
    "claude_code_hooks_daemon.handlers.user_prompt_submit.focus_mode_trigger.clear_goal_signal"
)


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SessionModeRegistry:
    return pin_session_modes(monkeypatch, tmp_path)


def _prompt(prompt: object, session_id: str | None = _SESSION) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"hook_event_name": "UserPromptSubmit", "prompt": prompt}
    if session_id is not None:
        hook_input["session_id"] = session_id
    return hook_input


def _run(hook_input: dict[str, Any], *, cleared: bool = True) -> tuple[Any, list[str]]:
    calls: list[str] = []

    def _clear(session_id: str) -> bool:
        calls.append(session_id)
        return cleared

    with patch(_CLEAR_TARGET, side_effect=_clear):
        result = FocusModeTriggerHandler().handle(hook_input)
    return result, calls


class TestInit:
    def test_identity(self) -> None:
        handler = FocusModeTriggerHandler()
        assert handler.name == HandlerID.FOCUS_MODE_TRIGGER.display_name
        assert handler.priority == Priority.FOCUS_MODE_TRIGGER
        assert handler.terminal is False

    def test_guidance_names_the_command_and_its_aliases(self) -> None:
        guidance = FocusModeTriggerHandler().get_claude_md()
        assert guidance is not None
        assert "hooks-daemon focus <task>" in guidance
        assert "`done`, `end`, `disable`" in guidance

    def test_one_acceptance_test_expecting_the_on_line(self) -> None:
        (test,) = FocusModeTriggerHandler().get_acceptance_tests()
        assert test.expected_decision is Decision.ALLOW
        assert test.expected_message_patterns == [r"FOCUS MODE ON"]

    def test_never_gated_by_autonomy(self) -> None:
        """Focus off must work while focus has halted every work-driving handler."""
        assert FocusModeTriggerHandler.drives_autonomy is False


class TestMatches:
    def test_matches_a_string_prompt(self) -> None:
        assert FocusModeTriggerHandler().matches(_prompt("anything")) is True

    def test_does_not_match_a_non_string_prompt(self) -> None:
        assert FocusModeTriggerHandler().matches(_prompt(7)) is False


class TestFocusOn:
    def test_turns_focus_on_with_exactly_one_line(self, registry: SessionModeRegistry) -> None:
        result, calls = _run(_prompt("Hooks Demon focus fix the parser"))
        assert result.decision is Decision.ALLOW
        assert len(result.context) == 1
        assert "FOCUS MODE ON" in result.context[0]
        assert "the active task is 'fix the parser'" in result.context[0]
        assert registry.policy(_SESSION).focus_task == "fix the parser"
        assert calls == [_SESSION]

    def test_a_second_command_changes_the_task_without_clearing(
        self, registry: SessionModeRegistry
    ) -> None:
        _run(_prompt("hooks-daemon focus first"))
        result, calls = _run(_prompt("hooks-daemon focus second"))
        assert len(result.context) == 1
        assert "TASK CHANGED" in result.context[0]
        assert calls == []
        assert registry.policy(_SESSION).focus_task == "second"

    def test_a_bare_command_asks_for_a_task(self, registry: SessionModeRegistry) -> None:
        result, calls = _run(_prompt("hooks-daemon focus"))
        assert len(result.context) == 1
        assert "needs a task" in result.context[0]
        assert registry.active(_SESSION) == ()
        assert calls == []

    def test_only_this_session_is_focused(self, registry: SessionModeRegistry) -> None:
        _run(_prompt("hooks-daemon focus x"))
        assert registry.active("sess-2") == ()


class TestFocusOff:
    @pytest.mark.parametrize("alias", ["off", "done", "end", "disable"])
    def test_turns_focus_off_with_exactly_one_line(
        self, registry: SessionModeRegistry, alias: str
    ) -> None:
        registry.enter(focus_entry(_SESSION, "fix the parser"))
        result, _ = _run(_prompt(f"hooks daemon focus {alias}"))
        assert result.decision is Decision.ALLOW
        assert len(result.context) == 1
        assert "FOCUS MODE OFF" in result.context[0]
        assert registry.active(_SESSION) == ()

    def test_off_when_not_focused_says_so(self) -> None:
        result, _ = _run(_prompt("hooks-daemon focus off"))
        assert len(result.context) == 1
        assert "was not on" in result.context[0]


class TestNotACommand:
    def test_a_supervisor_line_does_not_toggle_focus(self, registry: SessionModeRegistry) -> None:
        result, calls = _run(_prompt("🤖 [ccy-supervisor] hooks-daemon focus x"))
        assert result.context == []
        assert registry.active(_SESSION) == ()
        assert calls == []

    def test_a_command_not_at_the_start_is_ignored(self, registry: SessionModeRegistry) -> None:
        result, _ = _run(_prompt("please hooks-daemon focus x"))
        assert result.context == []
        assert registry.active(_SESSION) == ()

    def test_an_ordinary_prompt_adds_nothing(self) -> None:
        result, _ = _run(_prompt("fix the bug"))
        assert result.decision is Decision.ALLOW
        assert result.context == []


class TestRenewalAndNotices:
    def _aged_focus(self, registry: SessionModeRegistry, age: float) -> SessionModeEntry:
        entered = time.time() - age
        entry = SessionModeEntry(
            mode=SessionMode.FOCUS,
            session_id=_SESSION,
            entered_at=entered,
            expires_at=entered + FOCUS_TTL_SECONDS,
            source=ModeSource.HUMAN,
            detail="fix the parser",
        )
        registry.enter(entry)
        return entry

    def test_a_genuine_prompt_renews_focus(self, registry: SessionModeRegistry) -> None:
        entry = self._aged_focus(registry, 3600.0)
        _run(_prompt("carry on"))
        (renewed,) = registry.active(_SESSION)
        assert renewed.expires_at > entry.expires_at

    def test_a_tick_does_not_renew_focus(self, registry: SessionModeRegistry) -> None:
        entry = self._aged_focus(registry, 3600.0)
        _run(_prompt(CANONICAL_CRON_PROMPT))
        (kept,) = registry.active(_SESSION)
        assert kept.expires_at == entry.expires_at

    def test_an_expiry_is_stated_once(self, registry: SessionModeRegistry) -> None:
        self._aged_focus(registry, FOCUS_TTL_SECONDS + 10.0)
        first, _ = _run(_prompt("carry on"))
        assert any("focus expired" in line for line in first.context)
        second, _ = _run(_prompt("carry on"))
        assert second.context == []

    def test_an_expiry_is_stated_beside_a_new_focus(self, registry: SessionModeRegistry) -> None:
        self._aged_focus(registry, FOCUS_TTL_SECONDS + 10.0)
        result, _ = _run(_prompt("hooks-daemon focus again"))
        assert any("focus expired" in line for line in result.context)
        assert sum("FOCUS MODE ON" in line for line in result.context) == 1


class TestRestartRestatement:
    """Plan 00501 Task 4.2: one line on the next prompt after a restart, command or not."""

    @pytest.fixture
    def restarted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Mock]:
        """A daemon that restarted with a live focus on disk for the session."""
        writer = SessionModeRegistry(tmp_path / SIGNAL_SUBDIR)
        writer.load()
        writer.enter(focus_entry(_SESSION, "the survivor"))
        pin_session_modes(monkeypatch, tmp_path)
        controller = Mock()
        controller.get_mode.return_value = {ModeConstant.KEY_MODE: DaemonMode.DEFAULT.value}
        with patch(f"{_MODULE}.get_controller", return_value=controller):
            yield controller

    @staticmethod
    def _mode_lines(context: list[str]) -> list[str]:
        return [line for line in context if line.startswith("SESSION MODE:")]

    def test_a_plain_prompt_gets_one_line_once(self, restarted: Mock) -> None:
        first, _ = _run(_prompt("carry on"))
        [line] = self._mode_lines(first.context)
        assert "focus mode on 'the survivor' survived a daemon restart" in line
        second, _ = _run(_prompt("carry on"))
        assert second.context == []

    def test_a_focus_command_gets_the_line_too(self, restarted: Mock) -> None:
        result, _ = _run(_prompt("hooks-daemon focus off"))
        assert len(self._mode_lines(result.context)) == 1
        assert sum("FOCUS MODE OFF" in line for line in result.context) == 1

    def test_a_machine_prompt_gets_the_line_too(self, restarted: Mock) -> None:
        result, _ = _run(_prompt(CANONICAL_CRON_PROMPT))
        assert len(self._mode_lines(result.context)) == 1

    def test_unattended_is_named_beside_the_restart(self, restarted: Mock) -> None:
        restarted.get_mode.return_value = {ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value}
        result, _ = _run(_prompt("carry on"))
        [line] = self._mode_lines(result.context)
        assert "the daemon is in unattended mode" in line

    def test_a_usage_pause_from_before_the_restart_is_restated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        now = time.time()
        usage_pause.write_usage_pause(
            tmp_path,
            usage_pause.UsagePause(
                session_id=_SESSION,
                paused_at=now - 60,
                resume_at=now + 3600,
                window=usage_pause.WINDOW_FIVE_HOUR,
                used_percentage=91.0,
                ceiling=90.0,
                reason="five_hour at 91%",
            ),
        )
        pin_session_modes(monkeypatch, tmp_path)
        with patch(f"{_MODULE}.get_controller") as controller:
            controller.return_value.get_mode.return_value = {}
            result, _ = _run(_prompt("carry on"))
        [line] = self._mode_lines(result.context)
        assert "usage-paused (five_hour at 91%) survived a daemon restart" in line


def test_the_statement_is_the_only_reader_of_the_pop_once_notices() -> None:
    """``take_notices`` is pop-once: a second reader would steal the other's lines."""
    src = Path(__file__).resolve().parents[4] / "src" / "claude_code_hooks_daemon"
    readers = sorted(
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if ".take_notices(" in path.read_text(encoding="utf-8")
    )
    assert readers == ["core/session_mode_statement.py"]


class TestFailsLoud:
    def test_an_unreadable_registry_on_a_command_is_stated_and_warned(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(registry, "enter", side_effect=OSError("disk gone")),
            caplog.at_level(logging.WARNING),
        ):
            result, _ = _run(_prompt("hooks-daemon focus x"))
        assert result.decision is Decision.ALLOW
        assert len(result.context) == 1
        assert "could not" in result.context[0]
        assert "disk gone" in result.context[0]
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_an_unreadable_registry_on_a_plain_prompt_warns(
        self, registry: SessionModeRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch.object(registry, "note_prompt", side_effect=OSError("disk gone")),
            caplog.at_level(logging.WARNING),
        ):
            result, _ = _run(_prompt("carry on"))
        assert result.decision is Decision.ALLOW
        assert result.context == []
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_a_command_without_a_session_is_stated(self) -> None:
        result, calls = _run(_prompt("hooks-daemon focus x", session_id=None))
        assert len(result.context) == 1
        assert "session" in result.context[0]
        assert calls == []

    def test_a_plain_prompt_without_a_session_adds_nothing(self) -> None:
        result, _ = _run(_prompt("carry on", session_id=None))
        assert result.context == []
