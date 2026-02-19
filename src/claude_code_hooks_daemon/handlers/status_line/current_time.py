"""CurrentTimeHandler - display current time in status line."""

from datetime import datetime
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest


class CurrentTimeHandler(Handler):
    """Display current local time in status line (24-hour format, no seconds)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CURRENT_TIME,
            priority=Priority.CURRENT_TIME,
            terminal=False,
            tags=[HandlerTag.STATUSLINE, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status line events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return current time in 24-hour format without seconds."""
        now = datetime.now()
        time_str = now.strftime("%H:%M")  # 24-hour format, no seconds

        return HookResult(context=[f"| 🕐 {time_str}"])

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler.

        This handler displays current time in status line.
        Verification: Check system-reminders show time segment in HH:MM format.
        """
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="current time handler test",
                command='echo "test"',
                description=(
                    "Verify current time handler displays time in status line. "
                    "Check system-reminders show '🕐 HH:MM' time segment. "
                    "Handler confirmed active by daemon loading without errors."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
