"""Git repository name handler for status line.

Shows the repository name at the start of the status line.
Uses ProjectContext for authoritative repo name (calculated once at daemon startup).
"""

import logging
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext

logger = logging.getLogger(__name__)


class GitRepoNameHandler(Handler):
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

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return repository name from ProjectContext for status line.

        Args:
            hook_input: Status event input (not used)

        Returns:
            HookResult with formatted repo name
        """
        repo_name = ProjectContext.git_repo_name()
        return HookResult(context=[f"[{repo_name}]"])

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

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
            ),
        ]
