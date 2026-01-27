"""AutoApproveReadsHandler - automatically approves Read tool for safe file types."""

from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class AutoApproveReadsHandler(Handler):
    """Auto-approve Read tool permission requests for safe documentation files.

    Automatically approves Read tool usage for .md and .txt files to reduce
    permission prompt friction while maintaining security for sensitive files.
    """

    def __init__(self) -> None:
        """Initialise handler with high priority for early approval."""
        super().__init__(
            name="auto-approve-safe-reads",
            priority=10,
            tags=["workflow", "automation", "non-terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if Read tool is requesting .md or .txt file.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            True if Read tool with .md/.txt file
        """
        tool_name = hook_input.get("tool_name")

        # Only match Read tool
        if tool_name != "Read":
            return False

        tool_input = hook_input.get("tool_input", {})
        file_path = str(tool_input.get("file_path", ""))

        # Check file_path exists and is non-empty
        if not file_path:
            return False

        # Case-insensitive extension check for .md and .txt
        file_path_lower = file_path.lower()
        return bool(file_path_lower.endswith(".md") or file_path_lower.endswith(".txt"))

    def handle(self, _hook_input: dict[str, Any]) -> HookResult:
        """Auto-approve the read operation.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            HookResult with allow decision (silent approval)
        """
        return HookResult(decision=Decision.ALLOW)
