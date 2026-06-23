"""WebSearchYearHandler - validates WebSearch queries don't use outdated years."""

import re
from datetime import datetime
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

# First year considered an "outdated" year for a web-search query. Years from
# this value up to (but excluding) the current year trigger the advisory.
_OLDEST_TRACKED_YEAR = 2020


class WebSearchYearHandler(Handler):
    """Validate WebSearch queries don't use outdated years."""

    @property
    def CURRENT_YEAR(self) -> int:
        """Get current year dynamically."""
        return datetime.now().year

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.WEB_SEARCH_YEAR,
            priority=Priority.WEB_SEARCH_YEAR,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if WebSearch query uses old year."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name != ToolName.WEB_SEARCH:
            return False

        query = hook_input.get(HookInputField.TOOL_INPUT, {}).get("query", "")
        if not query:
            return False

        # Match an outdated year only when it stands alone (word boundaries), so
        # embedded digit runs such as "20200", "12025" or "2021abc" do NOT trigger
        # a false positive. The alternation is built from the live year range.
        return self._outdated_year_pattern().search(query) is not None

    def _outdated_year_pattern(self) -> re.Pattern[str]:
        """Build a word-boundary regex matching any outdated year (oldest..current-1)."""
        years = "|".join(str(year) for year in range(_OLDEST_TRACKED_YEAR, self.CURRENT_YEAR))
        return re.compile(rf"\b(?:{years})\b")

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Provide guidance about outdated year in WebSearch."""
        query = hook_input.get(HookInputField.TOOL_INPUT, {}).get("query", "")

        return HookResult(
            decision=Decision.ALLOW,
            context=[
                f"WebSearch query contains outdated year: {query}",
                f"Current year is {self.CURRENT_YEAR}. Consider updating the year for current information.",
            ],
            guidance=(
                "SUGGESTION: Update year for better results\n\n"
                f"Current query: {query}\n\n"
                f"Current year is {self.CURRENT_YEAR}. For current information:\n"
                f"  - Use {self.CURRENT_YEAR} instead of old years\n"
                "  - Remove year if searching general topics\n"
                "  - Only use old years if specifically researching history"
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Web Search Year."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Outdated year in search query",
                command="Use the WebSearch tool with query 'Python best practices 2024'",
                description="Advises current year for web searches (advisory)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"current year", r"2026"],
                safety_notes="Advisory handler - suggests updating year. WebSearch may not be available to subagent.",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse with WebSearch tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
