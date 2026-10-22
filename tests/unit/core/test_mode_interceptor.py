"""Tests for ModeInterceptor and UnattendedModeInterceptor."""

import logging
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core import mode_interceptor
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.mode_interceptor import (
    UnattendedModeInterceptor,
    get_interceptor_for_mode,
)
from claude_code_hooks_daemon.utils.session_modes import (
    BlockReason,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    SessionPolicy,
)
from tests.support.autonomy import awaiting_human_entry, focus_entry, pin_session_modes


class TestGetInterceptorForMode:
    """Tests for the get_interceptor_for_mode factory."""

    def test_default_mode_returns_none(self) -> None:
        result = get_interceptor_for_mode(DaemonMode.DEFAULT)
        assert result is None

    def test_unattended_mode_returns_interceptor(self) -> None:
        result = get_interceptor_for_mode(DaemonMode.UNATTENDED)
        assert result is not None
        assert isinstance(result, UnattendedModeInterceptor)

    def test_unattended_mode_with_custom_message(self) -> None:
        result = get_interceptor_for_mode(DaemonMode.UNATTENDED, custom_message="finish tasks")
        assert result is not None
        assert isinstance(result, UnattendedModeInterceptor)

    def test_default_mode_ignores_custom_message(self) -> None:
        result = get_interceptor_for_mode(DaemonMode.DEFAULT, custom_message="ignored")
        assert result is None


class TestUnattendedModeInterceptor:
    """Tests for UnattendedModeInterceptor."""

    def test_intercepts_stop_event(self) -> None:
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.STOP, {})
        assert result is not None
        assert result.decision == Decision.DENY
        assert ModeConstant.UNATTENDED_BLOCK_REASON in (result.reason or "")

    def test_does_not_intercept_subagent_stop(self) -> None:
        """SubagentStop should NOT be intercepted per design."""
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.SUBAGENT_STOP, {})
        assert result is None

    def test_does_not_intercept_pre_tool_use(self) -> None:
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.PRE_TOOL_USE, {})
        assert result is None

    def test_does_not_intercept_post_tool_use(self) -> None:
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.POST_TOOL_USE, {})
        assert result is None

    def test_does_not_intercept_session_start(self) -> None:
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.SESSION_START, {})
        assert result is None

    def test_reentry_protection_snake_case(self) -> None:
        """Should return None if stop_hook_active is True (prevents infinite loops)."""
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.STOP, {"stop_hook_active": True})
        assert result is None

    def test_reentry_protection_camel_case(self) -> None:
        """Should return None if stopHookActive is True (prevents infinite loops)."""
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.STOP, {"stopHookActive": True})
        assert result is None

    def test_no_reentry_when_false(self) -> None:
        """Should intercept when stop_hook_active is False."""
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.STOP, {"stop_hook_active": False})
        assert result is not None
        assert result.decision == Decision.DENY

    def test_custom_message_appended(self) -> None:
        interceptor = UnattendedModeInterceptor(custom_message="finish the release")
        result = interceptor.intercept(EventType.STOP, {})
        assert result is not None
        assert "finish the release" in (result.reason or "")
        assert ModeConstant.UNATTENDED_BLOCK_REASON in (result.reason or "")

    def test_no_custom_message(self) -> None:
        interceptor = UnattendedModeInterceptor()
        result = interceptor.intercept(EventType.STOP, {})
        assert result is not None
        assert result.reason == ModeConstant.UNATTENDED_BLOCK_REASON


_SESSION = "session-under-test"
_OTHER_SESSION = "another-session"


def _goal_blocked_entry(session_id: str) -> SessionModeEntry:
    """A live goal-loop BLOCKED mode for ``session_id``."""
    now = time.time()
    return SessionModeEntry(
        mode=SessionMode.BLOCKED,
        session_id=session_id,
        entered_at=now,
        expires_at=now + 3600.0,
        source=ModeSource.DETECTOR,
        reason=BlockReason.GOAL_LOOP,
    )


def _stop(session_id: str = _SESSION) -> HookResult | None:
    return UnattendedModeInterceptor().intercept(EventType.STOP, {"session_id": session_id})


class TestUnattendedStandsDownForHaltingModes:
    """Plan 00501 Task 2.3: halting beats driving -- BLOCKED or usage-paused lets the stop through."""

    @pytest.fixture(autouse=True)
    def _not_usage_paused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mode_interceptor, "hook_is_usage_paused", lambda _hook_input: False)

    def test_no_mode_still_blocks(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        pin_session_modes(monkeypatch, tmp_path / "modes")
        result = _stop()
        assert result is not None
        assert result.decision == Decision.DENY

    def test_awaiting_human_allows_the_stop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path / "modes", awaiting_human_entry(_SESSION))
        assert _stop() is None

    def test_goal_blocked_allows_the_stop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path / "modes", _goal_blocked_entry(_SESSION))
        assert _stop() is None

    def test_usage_paused_allows_the_stop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path / "modes")
        seen: list[Mapping[str, Any]] = []

        def paused(hook_input: Mapping[str, Any]) -> bool:
            seen.append(hook_input)
            return True

        monkeypatch.setattr(mode_interceptor, "hook_is_usage_paused", paused)
        assert _stop() is None
        assert seen == [{"session_id": _SESSION}]

    def test_focus_does_not_stand_it_down(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pin_session_modes(monkeypatch, tmp_path / "modes", focus_entry(_SESSION))
        result = _stop()
        assert result is not None
        assert result.decision == Decision.DENY

    def test_another_sessions_mode_changes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pin_session_modes(
            monkeypatch,
            tmp_path / "modes",
            awaiting_human_entry(_OTHER_SESSION),
            _goal_blocked_entry(_OTHER_SESSION),
        )
        result = _stop()
        assert result is not None
        assert result.decision == Decision.DENY

    def test_unreadable_registry_keeps_the_block(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No mode can be asserted, so the operator's unattended setting holds; logged at WARNING."""

        def unreadable(_hook_input: Mapping[str, Any]) -> SessionPolicy:
            raise OSError("registry unreadable")

        monkeypatch.setattr(mode_interceptor, "session_policy", unreadable)
        with caplog.at_level(logging.WARNING, logger=mode_interceptor.__name__):
            result = _stop()
        assert result is not None
        assert result.decision == Decision.DENY
        assert "registry unreadable" in caplog.text
