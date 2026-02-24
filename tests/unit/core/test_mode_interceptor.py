"""Tests for ModeInterceptor and UnattendedModeInterceptor."""

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.mode_interceptor import (
    UnattendedModeInterceptor,
    get_interceptor_for_mode,
)


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
