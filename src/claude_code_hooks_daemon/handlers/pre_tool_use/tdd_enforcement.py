"""TddEnforcementHandler - enforces test-first development for handler files."""

from pathlib import Path
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


class TddEnforcementHandler(Handler):
    """Enforce TDD by blocking handler file creation without corresponding test file."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TDD_ENFORCEMENT,
            priority=Priority.TDD_ENFORCEMENT,
            tags=[
                HandlerTag.TDD,
                HandlerTag.PYTHON,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a Write operation to a production Python file."""
        # Only match Write tool
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.WRITE:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Must be a .py file
        if not file_path.endswith(".py"):
            return False

        # Exclude __init__.py files
        if file_path.endswith("__init__.py"):
            return False

        # Exclude test files (test files can be created without TDD enforcement)
        if "/tests/" in file_path or "/test_" in file_path:
            return False

        # Must be in a handlers subdirectory OR src directory (production code)
        if "/handlers/" in file_path or "/src/" in file_path:
            return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check if test file exists, deny if not."""
        handler_path = get_file_path(hook_input)
        if not handler_path:
            return HookResult(decision=Decision.ALLOW)

        test_file_path = self._get_test_file_path(handler_path)

        # Check if test file exists
        if test_file_path.exists():
            return HookResult(decision=Decision.ALLOW)

        # Test file doesn't exist - block with helpful message
        handler_filename = Path(handler_path).name
        test_filename = test_file_path.name

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"🚫 TDD REQUIRED: Cannot create handler without test file\n\n"
                f"Handler file: {handler_filename}\n"
                f"Missing test: {test_filename}\n\n"
                f"PHILOSOPHY: Test-Driven Development\n"
                f"In TDD, we write the test first, then implement the handler.\n"
                f"This ensures:\n"
                f"  • Clear requirements before coding\n"
                f"  • 100% test coverage from the start\n"
                f"  • Design-focused implementation\n"
                f"  • Prevents untested code in production\n\n"
                f"REQUIRED ACTION:\n"
                f"1. Create the test file first:\n"
                f"   {test_file_path}\n\n"
                f"2. Write comprehensive tests for the handler\n"
                f"   - Test matches() logic with various inputs\n"
                f"   - Test handle() decision and reason\n"
                f"   - Test edge cases and error conditions\n\n"
                f"3. Run tests (they should fail - red)\n\n"
                f"4. THEN create the handler file:\n"
                f"   {handler_path}\n\n"
                f"5. Run tests again (they should pass - green)\n\n"
                f"REFERENCE:\n"
                f"  See existing test files in tests/ for examples\n"
                f"  File: .claude/hooks/controller/GUIDE-TESTING.md\n"
                f"  File: .claude/hooks/CLAUDE.md (TDD mandatory)"
            ),
        )

    def _get_test_file_path(self, handler_path: str) -> Path:
        """Get the expected test file path for a handler file."""
        # Extract just the handler filename
        handler_filename = Path(handler_path).name

        # Convert handler filename to test filename
        # e.g., git_handler.py -> test_git_handler.py
        test_filename = f"test_{handler_filename}"

        # Get controller directory by finding 'controller' in path
        path_parts = Path(handler_path).parts
        try:
            controller_idx = path_parts.index("controller")
            # Reconstruct path from parts (properly handles leading /)
            controller_dir = Path(*path_parts[: controller_idx + 1])
        except ValueError:
            # Fallback: assume standard structure
            controller_dir = Path(handler_path).parent.parent.parent

        # Test file should be in tests/ directory
        test_file_path = controller_dir / "tests" / test_filename

        return test_file_path
