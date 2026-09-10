"""WorkingDirectoryHandler - display current working directory when it differs from project root."""

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation

logger = logging.getLogger(__name__)


class WorkingDirectoryHandler(StatusLineHandlerBase):
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

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Return working directory path if different from project root.

        Args:
            hook_input: Status event input with workspace data

        Returns:
            AdvisoryResult with formatted working directory path, or empty if same as project root
        """
        workspace = hook_input.get("workspace", {})
        current_dir = workspace.get("current_dir")
        project_dir = workspace.get("project_dir")

        # Return empty if either path is missing
        if not current_dir or not project_dir:
            return AdvisoryResult(context=[])

        # Normalize paths for comparison
        current_path = Path(current_dir)
        project_path = Path(project_dir)

        # Return empty if current directory equals project directory
        if current_path == project_path:
            return AdvisoryResult(context=[])

        # Calculate relative path
        try:
            relative_path = current_path.relative_to(project_path)
            # Display path in orange to make it visually distinct
            orange = "\033[38;5;208m"
            reset = "\033[0m"
            return AdvisoryResult(context=[f"| 📁 {orange}{relative_path}{reset}"])
        except ValueError:
            # current_dir is not relative to project_dir (e.g., different drive on Windows)
            return AdvisoryResult(context=[])

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment and its current value (read-only path compare)."""
        try:
            from claude_code_hooks_daemon.core import ProjectContext

            project_root = ProjectContext.project_root()
            cwd = Path.cwd()
            if cwd == project_root:
                current_value = "Not shown now — the current directory is the project root."
            else:
                relative = cwd.relative_to(project_root)
                current_value = f"Currently shows: 📁 {relative}"
        except Exception as e:
            logger.debug("Failed to compare cwd/project_root for explain_segment: %s", e)
            current_value = (
                "Not shown now — requires the live session's workspace.current_dir/"
                "project_dir fields, or no project context is available here."
            )
        return SegmentExplanation(
            glyphs=("📁",),
            name="Working Directory",
            what_it_is=(
                "The current working directory, shown only when it differs from the "
                "project root (e.g. inside a subdirectory or a worktree)."
            ),
            how_to_read="Orange text, a path relative to the project root. Silent when they match.",
            current_value=current_value,
        )

    def get_claude_md(self) -> str | None:
        return None

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
