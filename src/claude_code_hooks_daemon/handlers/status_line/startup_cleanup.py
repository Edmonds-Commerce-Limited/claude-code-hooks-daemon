"""Startup cleanup status handler.

Shows a brief 🧹 indicator after daemon startup when stale files were cleaned.
Disappears after 30 seconds so it doesn't clutter the status line permanently.
"""

import json
import logging
import time
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext

logger = logging.getLogger(__name__)

# How long (seconds) to show the startup indicator after daemon start
_DISPLAY_WINDOW_SECONDS = 30

# Transition point between "starting" icon and "result" message
_STARTUP_PHASE_SECONDS = 5


class StartupCleanupHandler(Handler):
    """Show 🧹 briefly after daemon startup to indicate stale-file cleanup ran."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.STARTUP_CLEANUP,
            priority=Priority.STARTUP_CLEANUP,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DAEMON, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Show cleanup indicator briefly after daemon startup.

        - First 5 seconds:  | 🧹  (startup phase — brush icon only)
        - 5–30 seconds, files cleaned: | 🧹 N stale  (result phase)
        - After 30 seconds: nothing

        Returns:
            HookResult with cleanup context, or empty if outside display window
        """
        try:
            status_file = ProjectContext.daemon_untracked_dir() / "cleanup_status.json"
            if not status_file.exists():
                return HookResult(context=[])

            data = json.loads(status_file.read_text())
            timestamp: float = data.get("timestamp", 0.0)
            count: int = data.get("count", 0)
            elapsed = time.time() - timestamp

            if elapsed < _STARTUP_PHASE_SECONDS:
                return HookResult(context=["| 🧹"])
            elif elapsed < _DISPLAY_WINDOW_SECONDS and count > 0:
                return HookResult(context=[f"| 🧹 {count} stale"])

        except (OSError, json.JSONDecodeError, KeyError) as e:
            logger.debug("Failed to read cleanup status: %s", e)

        return HookResult(context=[])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="startup cleanup handler test",
                command='echo "test"',
                description="Tests startup cleanup statusline handler",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler — minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
