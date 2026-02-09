"""5-hour API usage handler for status line.

Displays current 5-hour usage window with progress bar and reset time.
Format: "current: ●●●○○○○○○○ 30% | resets 3:45pm"
"""

from datetime import datetime
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.status_line.api_usage_base import (
    ApiUsageBaseHandler,
)
from claude_code_hooks_daemon.utils.formatting import build_progress_bar, format_reset_time


class ApiUsageFiveHourHandler(ApiUsageBaseHandler):
    """Display 5-hour usage window with progress bar and reset time."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.API_USAGE_FIVE_HOUR,
            priority=Priority.API_USAGE_FIVE_HOUR,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def _format_usage(self, usage_data: dict[str, Any]) -> str | None:
        """Format 5-hour usage data for display.

        Args:
            usage_data: Full API response

        Returns:
            Formatted string like "current: ●●●○○○○○○○ 30% | resets 3:45pm"
        """
        # If no credentials, return None (error is shown by base handler only once)
        if usage_data.get("_no_credentials"):
            return None

        five_hour = usage_data.get("five_hour")
        if not five_hour:
            return None

        utilization = five_hour.get("utilization")
        if utilization is None:
            return None

        pct = round(float(utilization))
        bar = build_progress_bar(float(utilization))

        parts = [f"current: {bar} {pct}%"]

        resets_at = five_hour.get("resets_at")
        if resets_at:
            try:
                dt = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
                reset_str = format_reset_time(dt, style="time")
                parts.append(f"resets {reset_str}")
            except (ValueError, TypeError):
                pass

        return " | ".join(parts)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="5-hour usage display",
                command='echo "test"',
                description="Displays 5-hour usage window with progress bar",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"current:.*%"],
                safety_notes="Context/utility handler - display only",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
            ),
        ]
