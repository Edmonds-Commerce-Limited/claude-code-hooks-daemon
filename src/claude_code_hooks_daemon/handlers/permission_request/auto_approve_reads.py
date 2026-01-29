"""AutoApproveReadsHandler - automatically approves file read permission requests."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class AutoApproveReadsHandler(Handler):
    """Auto-approve file_read permission requests.

    Automatically approves file read operations to reduce permission prompt
    friction while blocking write operations.
    """

    def __init__(self) -> None:
        """Initialise handler with high priority for early approval."""
        super().__init__(
            handler_id=HandlerID.AUTO_APPROVE_READS,
            priority=Priority.AUTO_APPROVE_READS,
            tags=[HandlerTag.WORKFLOW, HandlerTag.AUTOMATION, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a file read or write permission request.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            True if file_read or file_write permission type
        """
        permission_type = hook_input.get(HookInputField.PERMISSION_TYPE)

        # Match both read and write to handle them differently
        return permission_type in ("file_read", "file_write")

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Auto-approve reads, deny writes.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with allow for reads, deny for writes
        """
        permission_type = hook_input.get(HookInputField.PERMISSION_TYPE)

        if permission_type == "file_read":
            # Auto-approve read operations
            return HookResult(decision=Decision.ALLOW)
        else:
            # Block write operations (should use PreToolUse hooks instead)
            resource = hook_input.get("resource", "unknown")
            return HookResult(
                decision=Decision.DENY,
                reason=(
                    f"BLOCKED: file_write permission request\n\n"
                    f"Resource: {resource}\n\n"
                    "File write operations should be controlled by PreToolUse hooks,\n"
                    "not PermissionRequest hooks. This handler only auto-approves reads."
                ),
            )
