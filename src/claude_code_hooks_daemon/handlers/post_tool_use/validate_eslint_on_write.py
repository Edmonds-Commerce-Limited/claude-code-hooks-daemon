"""ValidateEslintOnWriteHandler - runs ESLint validation on TypeScript/TSX files after write."""

import subprocess  # nosec B404 - subprocess used for eslint validation only (trusted tool)
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.utils import get_file_path


class ValidateEslintOnWriteHandler(Handler):
    """Run ESLint validation on TypeScript/TSX files after write."""

    VALIDATE_EXTENSIONS: ClassVar[list[str]] = [".ts", ".tsx"]
    SKIP_PATHS: ClassVar[list[str]] = ["node_modules", "dist", ".build", "coverage", "test-results"]

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        """
        Initialize handler with optional workspace root for test isolation.

        Args:
            workspace_root: Optional Path to project root (for testing).
                          If None, auto-detects using ProjectContext.
                          This allows tests to provide isolated test directories.
        """
        super().__init__(
            handler_id=HandlerID.VALIDATE_ESLINT_ON_WRITE,
            priority=Priority.VALIDATE_ESLINT_ON_WRITE,
            tags=[
                HandlerTag.VALIDATION,
                HandlerTag.TYPESCRIPT,
                HandlerTag.JAVASCRIPT,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self.workspace_root = (
            Path(workspace_root) if workspace_root else ProjectContext.project_root()
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing TypeScript/TSX file that needs validation."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Only check TypeScript/TSX files
        if not any(file_path.endswith(ext) for ext in self.VALIDATE_EXTENSIONS):
            return False

        # Skip build artifacts
        if any(skip in file_path for skip in self.SKIP_PATHS):
            return False

        # File must exist (PostToolUse runs after write)
        file_path_obj = Path(file_path)
        return file_path_obj.exists()

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Run ESLint on the file and block if errors found."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return HookResult(decision=Decision.ALLOW, reason="No file path found in hook input")

        file_path_obj = Path(file_path)

        print(f"\n🔍 Running ESLint validation on {file_path_obj.name}...")

        # Check if this is a worktree file
        is_worktree = "untracked/worktrees/" in file_path

        # Run ESLint using wrapper script
        try:
            command = [
                "tsx",
                "scripts/eslint-wrapper.ts",
                file_path,
                "--max-warnings",
                "0",
                "--human",
            ]
            cwd = str(self.workspace_root)

            if is_worktree:
                print("  [Detected worktree file - using ESLint wrapper for consistent config]")

            result = (
                subprocess.run(  # nosec B603 - eslint/npx are trusted tools, file path validated
                    command, cwd=cwd, capture_output=True, text=True, timeout=Timeout.ESLINT_CHECK
                )
            )

            if result.returncode != 0:
                error_message = (
                    f"ESLint validation FAILED for {file_path}\n\n"
                    + "=" * 80
                    + "\n"
                    + result.stdout
                    + "\n"
                )

                if result.stderr:
                    error_message += result.stderr + "\n"

                error_message += (
                    "=" * 80 + "\n\n"
                    "🚫 FILE WAS WRITTEN BUT HAS ESLINT ERRORS!\n"
                    "   You MUST fix these errors before continuing.\n\n"
                    f"   Run: npx eslint {file_path} --fix\n"
                    "   Or:  npm run lint -- --fix\n"
                )

                return HookResult(decision=Decision.DENY, reason=error_message)

            print(f"✅ ESLint validation passed for {file_path_obj.name}\n")
            return HookResult(decision=Decision.ALLOW)

        except subprocess.TimeoutExpired:
            return HookResult(
                decision=Decision.DENY,
                reason=f"ESLint timed out after {Timeout.ESLINT_CHECK} seconds",
            )
        except Exception as e:
            return HookResult(decision=Decision.DENY, reason=f"Failed to run ESLint: {e!s}")

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="validate eslint on write handler test",
                command='echo "test"',
                description="Tests validate eslint on write handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="PostToolUse event",
            ),
        ]
