"""PlanCompletionAdvisorHandler - advises when a plan is being marked as complete.

Detects edits to CLAUDE/Plan/NNNNN-*/PLAN.md that change status to Complete,
and reminds the agent to git mv the plan folder to Completed/ and update README.md.
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path

# Pattern to match CLAUDE/Plan/<digits>-<name>/PLAN.md (NOT in Completed/)
_PLAN_PATH_PATTERN = re.compile(r"CLAUDE/Plan/(\d+-[^/]+)/PLAN\.md$", re.IGNORECASE)

# Pattern to match **Status**: followed by "complete" (case-insensitive)
# Matches: **Status**: Complete, **Status**: Completed, **Status**: Complete (2026-02-06)
_STATUS_COMPLETE_PATTERN = re.compile(
    r"\*\*Status\*\*:\s*[Cc][Oo][Mm][Pp][Ll][Ee][Tt][Ee]", re.MULTILINE
)


class PlanCompletionAdvisorHandler(Handler):
    """Advise when a plan is being marked as complete.

    Detects edits to CLAUDE/Plan/NNNNN-*/PLAN.md that change status
    to Complete, and reminds the agent to:
    1. git mv the plan folder to CLAUDE/Plan/Completed/
    2. Update CLAUDE/Plan/README.md
    3. Update plan statistics
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_COMPLETION_ADVISOR,
            priority=Priority.PLAN_COMPLETION_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if editing PLAN.md with completion markers.

        Matches when:
        - Tool is Write or Edit
        - File path matches CLAUDE/Plan/NNNNN-*/PLAN.md (NOT in Completed/)
        - Content or edit contains status change to Complete/Completed
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Normalize path separators
        normalized = file_path.replace("\\", "/")

        # Exclude files already in Completed/ directory
        if "/Completed/" in normalized:
            return False

        # Must match CLAUDE/Plan/<digits>-<name>/PLAN.md
        if not _PLAN_PATH_PATTERN.search(normalized):
            return False

        # Check content for status completion marker
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})

        if tool_name == ToolName.WRITE:
            content = tool_input.get("content", "")
            return bool(_STATUS_COMPLETE_PATTERN.search(content))

        # Edit tool: check new_string for status completion marker
        new_string = tool_input.get("new_string", "")
        return bool(_STATUS_COMPLETE_PATTERN.search(new_string))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return advisory guidance about plan completion steps."""
        file_path = get_file_path(hook_input) or ""
        normalized = file_path.replace("\\", "/")

        # Extract plan folder name from path
        match = _PLAN_PATH_PATTERN.search(normalized)
        folder_name = match.group(1) if match else "NNNNN-description"

        guidance = (
            f"Plan {folder_name} appears to be marked as complete. Remember to:\n"
            f"1. Move to Completed/: git mv CLAUDE/Plan/{folder_name} "
            f"CLAUDE/Plan/Completed/\n"
            "2. Update CLAUDE/Plan/README.md "
            "(move from Active to Completed section, update link path)\n"
            "3. Update plan statistics in README.md "
            "(increment Completed count, update total)"
        )

        return HookResult(decision=Decision.ALLOW, context=[guidance])

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Plan Completion Advisor."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Writing PLAN.md with Status: Complete",
                command=(
                    "Use the Write tool to write to /tmp/acceptance-test-plancomp/CLAUDE/Plan/098-test/PLAN.md"
                    " with content '# Plan 098\\n\\n**Status**: Complete (2026-02-11)\\n\\nDone.'"
                ),
                description="Provides advisory about git mv and README.md updates when completing a plan",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"git mv", r"README", r"[Cc]omplete"],
                safety_notes="Uses /tmp path - safe. Advisory handler allows write and adds guidance.",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-plancomp/CLAUDE/Plan/098-test"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-plancomp"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
