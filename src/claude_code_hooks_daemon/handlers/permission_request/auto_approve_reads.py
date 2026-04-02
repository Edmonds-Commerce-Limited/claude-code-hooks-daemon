"""AutoApproveReadsHandler - automatically approves read-only tool permission requests.

Uses tool_name from the PermissionRequest event to determine whether the
operation is read-only. Real PermissionRequest events contain tool_name and
permission_suggestions (NOT permission_type).
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

# Read-only tools that are safe to auto-approve
_READ_ONLY_TOOLS: tuple[str, ...] = (
    ToolName.READ,
    ToolName.GLOB,
    ToolName.GREP,
)


class AutoApproveReadsHandler(Handler):
    """Auto-approve read-only tool permission requests.

    Automatically approves permission requests for read-only operations
    (Read, Glob, Grep) to reduce permission prompt friction. All other
    tools are denied — write/execute operations should be controlled by
    PreToolUse hooks instead.

    Matches on tool_name from real PermissionRequest events, NOT the
    non-existent permission_type field.
    """

    def __init__(self) -> None:
        """Initialise handler with high priority for early approval."""
        super().__init__(
            handler_id=HandlerID.AUTO_APPROVE_READS,
            priority=Priority.AUTO_APPROVE_READS,
            tags=[HandlerTag.WORKFLOW, HandlerTag.AUTOMATION, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a permission request for a read-only tool.

        Uses tool_name from the real PermissionRequest event structure.
        Only matches read-only tools (Read, Glob, Grep).

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            True if tool_name is a read-only tool
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        return tool_name in _READ_ONLY_TOOLS

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Auto-approve read-only tools, deny everything else.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with allow for read-only tools, deny for others
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        if tool_name in _READ_ONLY_TOOLS:
            return HookResult(decision=Decision.ALLOW)

        # Defensive: deny non-read tools that somehow reach handle()
        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"BLOCKED: Permission request for non-read tool '{tool_name}'\n\n"
                "Only read-only tools (Read, Glob, Grep) are auto-approved.\n"
                "Write/execute operations should be controlled by PreToolUse hooks."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Auto Approve Reads."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Auto-approve read permissions",
                command="Read file permission request",
                description="Auto-approves read-only operations (Read, Glob, Grep)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"read", r"approved"],
                safety_notes="Read-only operations are safe",
                test_type=TestType.CONTEXT,
                requires_event="PermissionRequest for Read tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
