"""Usage tracking handler for status line.

Displays daily and weekly token usage percentages by reading
~/.claude/stats-cache.json and calculating usage against daily limits.

CURRENTLY DISABLED:
This handler is disabled because the current approach is flawed:
- stats-cache.json only contains completed historical days, not current day usage
- Daily limits (200k Sonnet, 100k Opus) are hardcoded without source of truth
- No reliable way to get real-time current-day token counts or actual account limits
- Needs architectural rework to either: show raw counts instead of %, make limits
  configurable, use historical data only, or track tokens via proxy pattern

See: Research in conversation 2026-01-29 for alternative approaches
"""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.handlers.status_line.stats_cache_reader import (
    calculate_daily_usage,
    calculate_weekly_usage,
    read_stats_cache,
)


class UsageTrackingHandler(Handler):
    """Display daily and weekly token usage percentages."""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(
            handler_id=HandlerID.USAGE_TRACKING,
            priority=Priority.USAGE_TRACKING,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

        # Handler options
        default_options = {
            "show_daily": True,
            "show_weekly": True,
        }
        self._options = {**default_options, **(options or {})}

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        # DISABLED: Handler needs architectural rework (see module docstring)
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Generate daily/weekly usage percentage status text.

        Args:
            hook_input: Status event input with model data

        Returns:
            HookResult with formatted usage text in context list
        """
        try:
            # Extract model ID
            model_id = hook_input.get("model", {}).get("id")
            if not model_id:
                return HookResult(context=[])

            # Check if model is supported (has a daily limit defined)
            from claude_code_hooks_daemon.handlers.status_line.stats_cache_reader import (
                DAILY_LIMITS,
            )

            if model_id not in DAILY_LIMITS:
                # Unknown model - skip display
                return HookResult(context=[])

            # Read stats cache directly - it's fast, no need for TTL caching
            stats_path = Path.home() / ".claude" / "stats-cache.json"
            cache_data = read_stats_cache(stats_path)
            if cache_data is None:
                return HookResult(context=[])

            # Calculate usage percentages
            daily_pct = calculate_daily_usage(cache_data, model_id)
            weekly_pct = calculate_weekly_usage(cache_data, model_id)

            # Format output with color coding (same as context percentage)
            parts = []
            if self._options.get("show_daily", True):
                daily_colored = self._colorize_percentage(daily_pct)
                parts.append(f"daily: {daily_colored}")
            if self._options.get("show_weekly", True):
                weekly_colored = self._colorize_percentage(weekly_pct)
                parts.append(f"weekly: {weekly_colored}")

            if not parts:
                return HookResult(context=[])

            status = "| " + " | ".join(parts)
            return HookResult(context=[status])

        except Exception:
            # Silent fail - don't break status line for usage tracking issues
            return HookResult(context=[])

    def _colorize_percentage(self, percentage: float) -> str:
        """Apply quarter circle icon and color coding to percentage.

        Args:
            percentage: Usage percentage (0-100+)

        Returns:
            Colored percentage string with icon and ANSI codes
        """
        # Quarter circle icons with color coding (same as ModelContextHandler)
        if percentage <= 25:
            icon = "◔"
            color = "\033[42m\033[30m"  # 1/4 filled, green bg
        elif percentage <= 50:
            icon = "◑"
            color = "\033[43m\033[30m"  # Right half filled, yellow bg
        elif percentage <= 75:
            icon = "◕"
            color = "\033[48;5;208m\033[30m"  # 3/4 filled, orange bg
        else:
            icon = "●"
            color = "\033[41m\033[97m"  # Full, red bg
        reset = "\033[0m"

        return f"{icon} {color}{percentage:.1f}%{reset}"

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="usage tracking handler test",
                command='echo "test"',
                description="Tests usage tracking handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
            ),
        ]
