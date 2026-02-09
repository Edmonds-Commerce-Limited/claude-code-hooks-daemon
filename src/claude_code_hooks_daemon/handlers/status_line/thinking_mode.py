"""Thinking mode status handler for status line.

Reads ~/.claude/settings.json to show whether thinking mode is enabled.
Format: "thinking: On" (orange) or "thinking: Off" (dim)
"""

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)


class ThinkingModeHandler(Handler):
    """Display thinking mode status (On/Off) in status line."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.THINKING_MODE,
            priority=Priority.THINKING_MODE,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Read settings and display thinking mode status.

        Args:
            hook_input: Status event input (not used)

        Returns:
            HookResult with thinking mode status in context
        """
        try:
            thinking_on = self._is_thinking_enabled()

            orange = "\033[38;5;208m"
            dim = "\033[2m"
            reset = "\033[0m"

            if thinking_on:
                status = f"thinking: {orange}On{reset}"
            else:
                status = f"thinking: {dim}Off{reset}"

            return HookResult(context=[status])
        except Exception:
            logger.info("Error reading thinking mode settings")
            return HookResult(context=[])

    def _is_thinking_enabled(self) -> bool:
        """Check if thinking mode is enabled in settings.

        Returns:
            True if alwaysThinkingEnabled is true in settings
        """
        settings_path = self._get_settings_path()

        if not settings_path.exists():
            return False

        try:
            raw = settings_path.read_text()
            settings = json.loads(raw)
            return bool(settings.get("alwaysThinkingEnabled", False))
        except (json.JSONDecodeError, OSError):
            return False

    def _get_settings_path(self) -> Path:
        """Get path to Claude settings file.

        Returns:
            Path to ~/.claude/settings.json
        """
        return Path.home() / ".claude" / "settings.json"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="thinking mode display",
                command='echo "test"',
                description="Displays thinking mode On/Off status",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"thinking:"],
                safety_notes="Context/utility handler - display only",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
            ),
        ]
