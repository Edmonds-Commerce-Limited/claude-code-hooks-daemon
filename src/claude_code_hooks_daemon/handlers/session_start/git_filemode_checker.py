"""GitFilemodeCheckerHandler - Warns when git core.fileMode is disabled.

Runs on SessionStart to detect core.fileMode=false, which causes hook scripts
to lose their executable permission after git operations (checkout, merge, rebase).
Advisory only - warns loudly but does not block.
"""

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    Priority,
)
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.git_repo import GitRepo
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

# Named constants (no magic strings)
_GIT_CONFIG_KEY = "core.fileMode"
_FILEMODE_FALSE = "false"


class GitFilemodeCheckerHandler(SessionStartHandlerBase):
    """Warn when git core.fileMode=false is detected.

    Advisory handler that runs on new sessions only (not resumes).
    Warns about the risk of hook scripts losing executable permissions
    after git operations when core.fileMode is disabled.
    """

    def __init__(self) -> None:
        """Initialise the git filemode checker handler."""
        super().__init__(
            handler_id=HandlerID.GIT_FILEMODE_CHECKER,
            priority=Priority.GIT_FILEMODE_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.GIT,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )

    def _get_filemode_setting(self) -> str | None:
        """Query git for core.fileMode value.

        Returns:
            "true", "false", or None if not in a git repo or error
        """
        try:
            root: Path = ProjectContext.project_root()
        except RuntimeError:
            # ProjectContext not initialized (e.g. running without daemon) - use cwd fallback
            logger.debug("ProjectContext not initialized, using cwd for git fileMode check")
            root = Path.cwd()

        return GitRepo(root).read_config(_GIT_CONFIG_KEY)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only match on new sessions (not resumes).

        Args:
            hook_input: SessionStart hook input

        Returns:
            True for new sessions, False for resumes
        """
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Check git core.fileMode and warn if disabled.

        Args:
            hook_input: SessionStart hook input

        Returns:
            AdvisoryResult with ALLOW decision and advisory context
        """
        filemode = self._get_filemode_setting()

        lines: list[str] = []

        # Lean SessionStart (Plan 00128): only speak when there is something to
        # act on. core.fileMode=false is the sole actionable state — every other
        # value (true, unset, not-a-repo, unknown) is healthy/irrelevant and
        # stays silent.
        if filemode == _FILEMODE_FALSE:
            lines.append(
                "WARNING: git core.fileMode=false detected - "
                "hook scripts may lose executable permissions"
            )
            lines.append("")
            lines.append(
                "When core.fileMode is disabled, git does not track the executable bit. "
                "After checkout, merge, or rebase, hook scripts in .claude/hooks/ may "
                "become non-executable, silently breaking all hooks."
            )
            lines.append("")
            lines.append("Recommended fix:")
            lines.append("  git config core.fileMode true")
            lines.append("")
            lines.append(
                "The install/upgrade process uses git update-index --chmod=+x to "
                "force the executable bit in the index, but this does not help if "
                "core.fileMode=false strips it on checkout."
            )

        return AdvisoryResult(decision=Decision.ALLOW, context=lines)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="git filemode checker - reports core.fileMode status",
                command='echo "test"',
                description=(
                    "Tests that the handler detects git core.fileMode setting and warns "
                    "about hook scripts potentially losing executable permissions "
                    "after git operations when core.fileMode=false."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"GIT FILEMODE|core\.fileMode"],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
