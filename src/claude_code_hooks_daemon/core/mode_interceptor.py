"""Mode interceptor - Pre-dispatch event interception based on daemon mode.

Interceptors short-circuit event processing before the handler chain runs.
This keeps mode logic separate from handlers (Open/Closed principle).
"""

import logging
from typing import Any, Protocol

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult

logger = logging.getLogger(__name__)


class ModeInterceptor(Protocol):
    """Protocol for mode interceptors.

    Interceptors examine an event before the handler chain and can
    short-circuit processing by returning a HookResult. Returning None
    means the event should proceed to the normal handler chain.
    """

    def intercept(self, event_type: EventType, hook_input: dict[str, Any]) -> HookResult | None:
        """Intercept an event before handler dispatch.

        Args:
            event_type: The type of hook event.
            hook_input: The hook input dictionary.

        Returns:
            HookResult to short-circuit, or None to continue to handlers.
        """
        ...


class UnattendedModeInterceptor:
    """Intercepts Stop events to keep Claude working without interruption.

    Only intercepts EventType.STOP (not SubagentStop per user preference).
    Checks re-entry protection to prevent infinite loops.
    """

    __slots__ = ("_custom_message",)

    def __init__(self, custom_message: str | None = None) -> None:
        """Initialize interceptor.

        Args:
            custom_message: Optional text appended to the block reason.
        """
        self._custom_message = custom_message

    def intercept(self, event_type: EventType, hook_input: dict[str, Any]) -> HookResult | None:
        """Intercept Stop events unconditionally.

        Args:
            event_type: The type of hook event.
            hook_input: The hook input dictionary.

        Returns:
            HookResult with DENY for Stop events, None for all others.
        """
        # Only intercept Stop events (not SubagentStop)
        if event_type != EventType.STOP:
            return None

        # Re-entry protection: check both snake_case and camelCase variants
        # Mirrors AutoContinueStopHandler._is_stop_hook_active()
        if hook_input.get("stop_hook_active", False) or hook_input.get("stopHookActive", False):
            logger.debug("Unattended mode: stop_hook_active detected, skipping to prevent loop")
            return None

        # Build block reason
        reason = ModeConstant.UNATTENDED_BLOCK_REASON
        if self._custom_message:
            reason = f"{reason} User message: {self._custom_message}"

        logger.info("Unattended mode: blocking Stop event")
        return HookResult(decision=Decision.DENY, reason=reason)


def get_interceptor_for_mode(
    mode: DaemonMode,
    custom_message: str | None = None,
) -> ModeInterceptor | None:
    """Factory function to get the interceptor for a given mode.

    Args:
        mode: The current daemon mode.
        custom_message: Optional custom message for the interceptor.

    Returns:
        A ModeInterceptor instance, or None for default mode.
    """
    if mode == DaemonMode.UNATTENDED:
        return UnattendedModeInterceptor(custom_message=custom_message)
    return None
