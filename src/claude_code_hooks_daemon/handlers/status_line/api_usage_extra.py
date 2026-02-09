"""Extra usage credits handler for status line.

Displays extra/overage credits when enabled on the account.
Format: "extra: ●○○○○○○○○○ $5.23/$50.00"
Only shown when extra_usage.is_enabled is true.
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.status_line.api_usage_base import (
    ApiUsageBaseHandler,
)
from claude_code_hooks_daemon.utils.formatting import build_progress_bar


class ApiUsageExtraHandler(ApiUsageBaseHandler):
    """Display extra usage credits when enabled."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.API_USAGE_EXTRA,
            priority=Priority.API_USAGE_EXTRA,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def _format_usage(self, usage_data: dict[str, Any]) -> str | None:
        """Format extra usage credits for display.

        Args:
            usage_data: Full API response

        Returns:
            Formatted string like "extra: ●○○○○○○○○○ $5.23/$50.00", or None if disabled
        """
        # If no credentials, return None (error is shown by base handler only once)
        if usage_data.get("_no_credentials"):
            return None

        extra = usage_data.get("extra_usage")
        if not extra:
            return None

        if not extra.get("is_enabled"):
            return None

        utilization = extra.get("utilization", 0)
        bar = build_progress_bar(float(utilization))

        # Credits are in cents, convert to dollars
        used_cents = extra.get("used_credits", 0)
        limit_cents = extra.get("monthly_limit", 0)
        used_dollars = float(used_cents) / 100
        limit_dollars = float(limit_cents) / 100

        return f"extra: {bar} ${used_dollars:.2f}/${limit_dollars:.2f}"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="extra usage credits display",
                command='echo "test"',
                description="Displays extra usage credits when enabled",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"extra:.*\$"],
                safety_notes="Context/utility handler - display only",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
            ),
        ]
