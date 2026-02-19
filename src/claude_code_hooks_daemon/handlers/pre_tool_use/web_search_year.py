"""WebSearchYearHandler - validates WebSearch queries don't use outdated years."""

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

        # Check for years 2020-2024 in query
        return any(str(year) in query for year in range(2020, self.CURRENT_YEAR))

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
