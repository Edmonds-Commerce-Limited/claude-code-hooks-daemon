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
        # Check if file is in tests directory OR filename starts with test_
        filename = Path(file_path).name
        if "/tests/" in file_path or filename.startswith("test_"):
            return False

        # Must be in a handlers subdirectory OR src directory (production code)
        # Note: handlers/ not /handlers/ to match paths like test-handlers/
        return bool("handlers/" in file_path or "/src/" in file_path)

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
        """Get the expected test file path for a handler file.

        Uses generic src/ directory detection to mirror source structure into tests/unit/.
        Pattern: src/{package}/{subdir}/.../file.py -> tests/unit/{subdir}/.../test_file.py

        The package directory (first dir after src/) is stripped since test directories
        typically don't replicate the package name.
        """
        handler_filename = Path(handler_path).name
        test_filename = f"test_{handler_filename}"

        path_parts = Path(handler_path).parts

        # Generic src/-based path mapping
        if "src" in path_parts:
            try:
                src_idx = path_parts.index("src")

                # Workspace root is everything before src/
                workspace_parts = path_parts[:src_idx]
                workspace_root = Path(*workspace_parts) if workspace_parts else Path("/workspace")

                # Parts after src/: {package}/{subdir}/.../file.py
                after_src = path_parts[src_idx + 1 :]

                # Skip the package directory (first dir after src/) and the filename (last)
                # Remaining parts are the subdirectory structure to mirror
                if len(after_src) > 2:
                    # after_src[0] = package name (skip)
                    # after_src[1:-1] = subdirectories to mirror
                    # after_src[-1] = filename (replaced with test_filename)
                    sub_dirs = after_src[1:-1]
                    test_file_path = workspace_root / "tests" / "unit"
                    for sub_dir in sub_dirs:
                        test_file_path = test_file_path / sub_dir
                    return test_file_path / test_filename
                elif len(after_src) == 2:
                    # src/{package}/file.py -> tests/unit/test_file.py
                    return workspace_root / "tests" / "unit" / test_filename
            except (ValueError, IndexError):
                pass

        # Fallback for non-src/ paths (e.g., controller-based structure)
        try:
            controller_idx = path_parts.index("controller")
            controller_dir = Path(*path_parts[: controller_idx + 1])
        except ValueError:
            controller_dir = Path(handler_path).parent.parent.parent

        return controller_dir / "tests" / test_filename

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Tdd Enforcement."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="Create handler without test file",
                command="Write to handler file without corresponding test",
                description="Blocks handler file creation without test file (TDD enforcement)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"TDD REQUIRED", r"test file", r"Write tests first"],
                safety_notes="Tests TDD enforcement without actual file operations",
                test_type=TestType.BLOCKING,
                requires_event="PreToolUse with Write tool to handler file",
            ),
        ]
