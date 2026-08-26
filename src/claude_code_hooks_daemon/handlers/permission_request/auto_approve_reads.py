"""AutoApproveReadsHandler - automatically approves read-only tool permission requests.

Uses tool_name from the PermissionRequest event to determine whether the
operation is read-only. Real PermissionRequest events contain tool_name and
permission_suggestions (NOT permission_type).

Gated on `permission_mode == "bypassPermissions"` — in any other mode the
handler defers (matches() returns False) so Claude Code's normal approval
flow runs. Silently auto-approving in non-YOLO modes was the bug fixed by
Plan 00106: it converted a default session into YOLO behaviour without
user consent.
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PermissionRequestHandlerBase
from claude_code_hooks_daemon.utils.permission_mode import is_bypass_mode

# Read-only tools that are safe to auto-approve
_READ_ONLY_TOOLS: tuple[str, ...] = (
    ToolName.READ,
    ToolName.GLOB,
    ToolName.GREP,
)


class AutoApproveReadsHandler(PermissionRequestHandlerBase):
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
        """Check if this is a permission request for a read-only tool in bypass mode.

        Only fires when Claude Code reports `permission_mode == "bypassPermissions"`.
        In every other mode (default, plan, acceptEdits, dontAsk) the handler
        defers so Claude Code's normal approval prompt is shown — the user
        has not opted out of per-tool approvals.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            True iff in bypass mode AND tool_name is a read-only tool
        """
        if not is_bypass_mode(hook_input):
            return False

        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        return tool_name in _READ_ONLY_TOOLS

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Auto-approve read-only tools, deny everything else.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            BlockingResult with allow for read-only tools, deny for others
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        if tool_name in _READ_ONLY_TOOLS:
            return BlockingResult(decision=Decision.ALLOW)

        # Defensive: deny non-read tools that somehow reach handle()
        return BlockingResult(
            decision=Decision.DENY,
            reason=(
                f"BLOCKED: Permission request for non-read tool '{tool_name}'\n\n"
                "Only read-only tools (Read, Glob, Grep) are auto-approved.\n"
                "Write/execute operations should be controlled by PreToolUse hooks."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## auto_approve_reads — gated on bypassPermissions mode\n\n"
            "Read-only tool permission requests (`Read`, `Glob`, `Grep`) are "
            "auto-approved **only** when Claude Code reports "
            '`permission_mode == "bypassPermissions"` (YOLO mode).\n\n'
            "In every other mode (`default`, `plan`, `acceptEdits`, `dontAsk`) "
            "the handler defers and Claude Code's normal approval prompt is "
            "shown — the user has not opted out of per-tool approvals, so the "
            "daemon must not silently approve on their behalf.\n\n"
            "If a permission prompt for `Read` appears in `default` mode, "
            "that is correct behaviour — approve it via Claude Code's UI."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Auto Approve Reads.

        Includes positive (bypass mode → auto-approve) and negative
        (default mode → defer to Claude Code's prompt) cases to verify
        the Plan 00106 bypass-mode gate at the daemon boundary.
        """
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Auto-approve Read in bypassPermissions mode",
                command="Read file permission request (permission_mode=bypassPermissions)",
                description=(
                    "In YOLO/bypass mode, Read/Glob/Grep permission requests "
                    "are auto-approved by the daemon — no prompt is shown."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"read", r"approved"],
                safety_notes="Read-only operations are safe to auto-approve in bypass mode",
                test_type=TestType.CONTEXT,
                requires_event="PermissionRequest for Read tool in bypassPermissions mode",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Defer Read in default mode (Plan 00106 fix)",
                command="Read file permission request (permission_mode=default)",
                description=(
                    "In default (non-bypass) mode the handler MUST defer — "
                    "Claude Code's normal approval prompt should be shown so "
                    "the user retains per-tool control. Silently approving "
                    "here was the security bug fixed by Plan 00106."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"defer|prompt|approval"],
                safety_notes=(
                    "Verifies the daemon does not silently bypass the user's "
                    "permission settings in non-YOLO sessions."
                ),
                test_type=TestType.CONTEXT,
                requires_event="PermissionRequest for Read tool in default mode",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
