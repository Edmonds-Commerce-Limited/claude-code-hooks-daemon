"""Thinking mode status handler for status line.

Reads ~/.claude/settings.json to show thinking mode status.
Format: "thinking: On/Off".

Uses alwaysThinkingEnabled key (same as PowerShell reference implementation).
Effort level display is handled by ModelContextHandler (shown next to model name).
"""

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)


class ThinkingModeHandler(Handler):
    """Display thinking mode and effort level in status line."""

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
        """Read settings and display thinking mode and effort level.

        Args:
            hook_input: Status event input (not used)

        Returns:
            HookResult with thinking mode and effort level in context
        """
        try:
            settings = self._read_settings()

            orange = "\033[38;5;208m"
            dim = "\033[2m"
            reset = "\033[0m"

            parts: list[str] = []

            # Only show thinking status when we actually know the state
            if "alwaysThinkingEnabled" in settings:
                thinking_on = bool(settings["alwaysThinkingEnabled"])
                if thinking_on:
                    parts.append(f"thinking: {orange}On{reset}")
                else:
                    parts.append(f"thinking: {dim}Off{reset}")

            return HookResult(context=parts)
        except Exception:
            logger.info("Error reading thinking mode settings")
            return HookResult(context=[])

    def _read_settings(self) -> dict[str, Any]:
        """Read Claude settings file.

        Returns:
            Parsed settings dict, or empty dict on failure
        """
        settings_path = self._get_settings_path()

        if not settings_path.exists():
            return {}

        try:
            raw = settings_path.read_text()
            result: dict[str, Any] = json.loads(raw)
            return result
        except (json.JSONDecodeError, OSError):
            return {}

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
