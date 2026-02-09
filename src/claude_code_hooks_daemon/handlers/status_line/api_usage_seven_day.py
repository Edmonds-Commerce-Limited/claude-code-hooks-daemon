"""7-day API usage handler for status line.

Displays weekly usage window with progress bar and reset time.
Format: "weekly: ●●●●●○○○○○ 50% | resets Feb 15, 4:30pm"
"""

from datetime import datetime
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.status_line.api_usage_base import (
    ApiUsageBaseHandler,
)
from claude_code_hooks_daemon.utils.formatting import build_progress_bar, format_reset_time


class ApiUsageSevenDayHandler(ApiUsageBaseHandler):
    """Display 7-day usage window with progress bar and reset time."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.API_USAGE_SEVEN_DAY,
            priority=Priority.API_USAGE_SEVEN_DAY,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def _format_usage(self, usage_data: dict[str, Any]) -> str | None:
        """Format 7-day usage data for display.

        Args:
            usage_data: Full API response

        Returns:
            Formatted string like "weekly: ●●●●●○○○○○ 50% | resets Feb 15, 4:30pm"
        """
        # If no credentials, return None (error is shown by base handler only once)
        if usage_data.get("_no_credentials"):
            return None

        seven_day = usage_data.get("seven_day")
        if not seven_day:
            return None

        utilization = seven_day.get("utilization")
        if utilization is None:
            return None

        pct = round(float(utilization))
        bar = build_progress_bar(float(utilization))

        parts = [f"weekly: {bar} {pct}%"]

        resets_at = seven_day.get("resets_at")
        if resets_at:
            try:
                dt = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
                reset_str = format_reset_time(dt, style="datetime")
                parts.append(f"resets {reset_str}")
            except (ValueError, TypeError):
                pass

        return " | ".join(parts)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="7-day usage display",
                command='echo "test"',
                description="Displays 7-day usage window with progress bar",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"weekly:.*%"],
                safety_notes="Context/utility handler - display only",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
            ),
        ]
