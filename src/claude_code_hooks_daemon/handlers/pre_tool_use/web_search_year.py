"""WebSearchYearHandler - validates WebSearch queries don't use outdated years."""

from datetime import datetime
from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class WebSearchYearHandler(Handler):
    """Validate WebSearch queries don't use outdated years."""

    @property
    def CURRENT_YEAR(self) -> int:
        """Get current year dynamically."""
        return datetime.now().year

    def __init__(self) -> None:
        super().__init__(name="validate-websearch-year", priority=55)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if WebSearch query uses old year."""
        tool_name = hook_input.get("tool_name")
        if tool_name != "WebSearch":
            return False

        query = hook_input.get("tool_input", {}).get("query", "")
        if not query:
            return False

        # Check for years 2020-2024 in query
        return any(str(year) in query for year in range(2020, self.CURRENT_YEAR))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block outdated year in WebSearch."""
        query = hook_input.get("tool_input", {}).get("query", "")

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"🚫 BLOCKED: WebSearch query contains outdated year\n\n"
                f"Query: {query}\n\n"
                f"Current year is {self.CURRENT_YEAR}. Don't search for old years.\n\n"
                "✅ CORRECT APPROACH:\n"
                f"  - Use {self.CURRENT_YEAR} for current information\n"
                "  - Remove year if searching general topics\n"
                "  - Only use old years if specifically researching history"
            ),
        )
