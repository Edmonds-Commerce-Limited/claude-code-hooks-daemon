"""PlanTimeEstimatesHandler - blocks time estimates in plan documents."""

import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path


class PlanTimeEstimatesHandler(Handler):
    """Block time estimates in plan documents."""

    ESTIMATE_PATTERNS: ClassVar[list[str]] = [
        r"\*\*Estimated\s+Effort\*\*:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"Estimated\s+Effort:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"(?:Time\s+)?[Ee]stimated\s+(?:time)?:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"\*\*Total\s+Estimated\s+Time\*\*:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"Total\s+Estimated\s+Time:\s*[^\n]*(?:hours?|minutes?|days?|weeks?)",
        r"\*\*Target\s+Completion\*\*:\s*\d{4}-\d{2}-\d{2}",
        r"Target\s+Completion:\s*\d{4}-\d{2}-\d{2}",
        r"\*\*Completion\*\*:\s*\d{4}-\d{2}-\d{2}",
        r"Completion:\s*\d{4}-\d{2}-\d{2}",
        # Work estimate patterns (with context clues)
        r"\b(?:take|takes|require|requires|need|needs|approximately|about)\s+\d+[-]\d+\s*(?:hour|hr|minute|min|day|week|month)s?\b",
        r"\b(?:take|takes|require|requires|need|needs|approximately|about)\s+\d+\s+(?:hour|hr|minute|min|day|week|month)s?\b",
        r"\bPhase\s+\d+[^:]*:\s*[^\(]*\(\s*\d+[-]\d+\s*(?:hour|hr|minute|min|day|week)s?\s*\)",
        r"\bPhase\s+\d+[^:]*:\s*[^\(]*\(\s*\d+\s+(?:hour|hr|minute|min|day|week)s?\s*\)",
        r"\b(?:Total|Overall|Combined)[^\n:]*:\s*\d+[-]\d+\s*(?:hour|hr|minute|min|day|week)s?\b",
        r"\b(?:Total|Overall|Combined)[^\n:]*:\s*\d+\s+(?:hour|hr|minute|min|day|week)s?\b",
        r"\b\d+[-]\d+\s*(?:hour|hr|minute|min|day|week)s?\s+(?:of\s+)?(?:work|implementation|development|effort|time)\b",
        r"\b\d+\s+(?:hour|hr|minute|min|day|week)s?\s+(?:of\s+)?(?:work|implementation|development|effort|time)\b",
        r"\b(ETA|timeline|deadline|due date):\s*\d",
    ]

    # Technical terms that should NOT be flagged (feature descriptions)
    TECHNICAL_PATTERNS: ClassVar[list[str]] = [
        r"\bTTL\b",
        r"\bcache\b",
        r"\bretention\b",
        r"\bpolicy\b",
        r"\bwindow\b",
        r"\btimeout\b",
        r"\bexpir(?:e|es|ation|y)\b",
        r"\btracking\b",
        r"\btrial\b",
        r"\bperiod\b",
        r"\bsession\b",
        r"\brolling\b",
        r"\busage\b",
        r"\bAPI\b",
        r"\brate\s+limit",
    ]

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_TIME_ESTIMATES,
            priority=Priority.PLAN_TIME_ESTIMATES,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing time estimates to plan files."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path or "/Plan/" not in file_path or not file_path.endswith(".md"):
            return False

        content = get_file_content(hook_input)
        if tool_name == ToolName.EDIT:
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return False

        # Check for time estimate patterns
        has_estimate_pattern = any(
            re.search(pattern, content, re.IGNORECASE) for pattern in self.ESTIMATE_PATTERNS
        )

        if not has_estimate_pattern:
            return False

        # Check if this is a technical term (not a work estimate)
        # Look for technical keywords near the time unit
        is_technical = any(
            re.search(pattern, content, re.IGNORECASE) for pattern in self.TECHNICAL_PATTERNS
        )

        # If technical keywords found, it's likely a feature description, not a work estimate
        return not is_technical

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block time estimates."""
        file_path = get_file_path(hook_input)

        return HookResult(
            decision=Decision.DENY,
            reason=(
                "🚫 BLOCKED: Time estimates not allowed in plan documents\n\n"
                f"File: {file_path}\n\n"
                "Plans should focus on WHAT needs to be done, not WHEN.\n\n"
                "WHY: Time estimates in plans create false expectations and pressure.\n\n"
                "✅ CORRECT APPROACH:\n"
                "  - Break work into concrete tasks\n"
                "  - Describe implementation steps\n"
                "  - Let user decide scheduling\n"
                "  - Focus on actionable work, not timelines"
            ),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Plan Time Estimates."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="Block time estimates in plan",
                command=(
                    "Use the Write tool to write to /tmp/acceptance-test-plantime/Plan/001-test/PLAN.md"
                    " with content '# Plan 001\\n\\n**Estimated Effort**: 4 hours\\n\\nTask list here.'"
                ),
                description="Blocks time estimates in plan documents (plans focus on WHAT not WHEN)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"time estimate", r"BLOCKED"],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-plantime/Plan/001-test"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-plantime"],
            ),
        ]
