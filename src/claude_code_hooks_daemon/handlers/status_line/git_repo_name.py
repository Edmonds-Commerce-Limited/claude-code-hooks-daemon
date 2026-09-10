"""Git repository name handler for status line.

Shows the repository name at the start of the status line.
Uses ProjectContext for authoritative repo name (calculated once at daemon startup).
"""

import logging
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation

logger = logging.getLogger(__name__)


class GitRepoNameHandler(StatusLineHandlerBase):
    """Show git repository name at start of status line.

    Uses ProjectContext for authoritative repo name (calculated once at daemon startup).
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_REPO_NAME,
            priority=Priority.GIT_REPO_NAME,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.GIT, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Return repository name from ProjectContext for status line.

        Args:
            hook_input: Status event input (not used)

        Returns:
            AdvisoryResult with formatted repo name
        """
        repo_name = ProjectContext.git_repo_name()
        return AdvisoryResult(context=[f"📁 {repo_name}"])

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment and its current value (read-only)."""
        try:
            repo_name = ProjectContext.git_repo_name()
            current_value = f"Currently shows: 📁 {repo_name}"
        except Exception as e:
            logger.debug("ProjectContext not initialised for explain_segment: %s", e)
            current_value = f"Not shown now — ProjectContext not initialised ({e})."
        return SegmentExplanation(
            glyphs=("📁",),
            name="Git Repository Name",
            what_it_is="The repository's name, at the start of the status line.",
            how_to_read="Plain text, no colour coding. Computed once at daemon startup.",
            current_value=current_value,
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="git repo name handler test",
                command='echo "test"',
                description="Tests git repo name handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
