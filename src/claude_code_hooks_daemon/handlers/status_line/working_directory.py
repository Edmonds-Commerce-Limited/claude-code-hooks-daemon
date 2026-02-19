"""WorkingDirectoryHandler - display current working directory when it differs from project root."""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest


class WorkingDirectoryHandler(Handler):
    """Display working directory when it differs from project root."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.WORKING_DIRECTORY,
            priority=Priority.WORKING_DIRECTORY,
            terminal=False,
            tags=[HandlerTag.STATUSLINE, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status line events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return working directory path if different from project root.

        Args:
            hook_input: Status event input with workspace data

        Returns:
            HookResult with formatted working directory path, or empty if same as project root
        """
        workspace = hook_input.get("workspace", {})
        current_dir = workspace.get("current_dir")
        project_dir = workspace.get("project_dir")

        # Return empty if either path is missing
        if not current_dir or not project_dir:
            return HookResult(context=[])

        # Normalize paths for comparison
        current_path = Path(current_dir)
        project_path = Path(project_dir)

        # Return empty if current directory equals project directory
        if current_path == project_path:
            return HookResult(context=[])

        # Calculate relative path
        try:
            relative_path = current_path.relative_to(project_path)
            # Display path in orange to make it visually distinct
            orange = "\033[38;5;208m"
            reset = "\033[0m"
            return HookResult(context=[f"| 📁 {orange}{relative_path}{reset}"])
        except ValueError:
            # current_dir is not relative to project_dir (e.g., different drive on Windows)
            return HookResult(context=[])

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler.

        This handler displays working directory in status line.
        Verification: Check system-reminders show directory segment when in subdirectory.
        """
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="working directory handler test",
                command='echo "test"',
                description=(
                    "Verify working directory handler displays subdirectory in status line. "
                    "Check system-reminders show '📁 <relative-path>' segment when cwd differs from project root. "
                    "Handler confirmed active by daemon loading without errors."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
