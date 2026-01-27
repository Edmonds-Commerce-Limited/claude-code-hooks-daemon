"""AbsolutePathHandler - requires absolute paths in file operations."""

from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class AbsolutePathHandler(Handler):
    """Require absolute paths for Read/Write/Edit tool file_path parameters.

    This handler enforces that all file operations use absolute paths to avoid
    ambiguity and ensure operations target the correct files.
    """

    def __init__(self) -> None:
        super().__init__(
            name="require-absolute-paths",
            priority=12,
            tags=["safety", "file-ops", "blocking", "terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if tool uses relative path in file_path parameter."""
        tool_name = hook_input.get("tool_name")

        # Only check Read, Write, and Edit tools
        if tool_name not in ["Read", "Write", "Edit"]:
            return False

        tool_input = hook_input.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        if not file_path:
            return False

        # Check if path is relative (doesn't start with /)
        return not file_path.startswith("/")

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block relative paths with explanation."""
        tool_name = hook_input.get("tool_name")
        tool_input = hook_input.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"BLOCKED: {tool_name} tool requires absolute path\n\n"
                f"Relative path provided: {file_path}\n\n"
                "Why absolute paths are required:\n"
                "  - Eliminates ambiguity about current working directory\n"
                "  - Prevents accidental operations on wrong files\n"
                "  - Makes file operations explicit and traceable\n\n"
                "REQUIRED ACTION:\n"
                f"  Use absolute path starting with /\n"
                f"  Example: /workspace/{file_path}\n\n"
                "Note: Claude Code's Read tool documentation states:\n"
                "'The file_path parameter must be an absolute path, not a relative path'"
            ),
        )
