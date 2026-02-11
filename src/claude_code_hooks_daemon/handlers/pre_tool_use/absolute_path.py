"""AbsolutePathHandler - requires absolute paths in file operations."""

from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class AbsolutePathHandler(Handler):
    """Require absolute paths for Read/Write/Edit tool file_path parameters.

    This handler enforces that all file operations use absolute paths to avoid
    ambiguity and ensure operations target the correct files.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ABSOLUTE_PATH,
            priority=Priority.ABSOLUTE_PATH,
            tags=[HandlerTag.SAFETY, HandlerTag.FILE_OPS, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if tool uses relative path in file_path parameter."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Only check Read, Write, and Edit tools
        if tool_name not in [ToolName.READ, ToolName.WRITE, ToolName.EDIT]:
            return False

        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = tool_input.get("file_path", "")

        if not file_path:
            return False

        # Check if path is relative (doesn't start with /)
        return not file_path.startswith("/")

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block relative paths with explanation."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
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

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for absolute path handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="Read with relative path",
                command="Use the Read tool to read file_path 'relative/path/file.txt' (relative path, no leading slash)",
                description="Blocks Read tool with relative path (requires absolute path)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"requires absolute path",
                    r"Relative path provided",
                ],
                safety_notes="Handler blocks before any file I/O occurs.",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="Write with relative path",
                command="Use the Write tool with file_path 'some/relative/path.txt' and content 'test' (relative path, no leading slash)",
                description="Blocks Write tool with relative path",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"absolute path",
                ],
                safety_notes="Handler blocks before any file I/O occurs.",
                test_type=TestType.BLOCKING,
            ),
        ]
