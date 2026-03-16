"""GitFilemodeCheckerHandler - Warns when git core.fileMode is disabled.

Runs on SessionStart to detect core.fileMode=false, which causes hook scripts
to lose their executable permission after git operations (checkout, merge, rebase).
Advisory only - warns loudly but does not block.
"""

import logging
import subprocess  # nosec B404 - subprocess used for git commands only (trusted system tool)
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)

# Named constants (no magic strings)
_GIT_CONFIG_KEY = "core.fileMode"
_FILEMODE_FALSE = "false"
_GIT_COMMAND = "git"
_RESUME_TRANSCRIPT_MIN_BYTES = 100


class GitFilemodeCheckerHandler(Handler):
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

    def _is_resume_session(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a resumed session (transcript has content).

        Args:
            hook_input: SessionStart hook input

        Returns:
            True if resume, False if new session
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False

        try:
            path = Path(transcript_path)
            if not path.exists():
                return False
            return path.stat().st_size > _RESUME_TRANSCRIPT_MIN_BYTES
        except (OSError, ValueError):
            return False

    def _get_filemode_setting(self) -> str | None:
        """Query git for core.fileMode value.

        Returns:
            "true", "false", or None if not in a git repo or error
        """
        try:
            # SECURITY: This subprocess call is safe because:
            # - Command is hardcoded: "git"
            # - All arguments are hardcoded (no user input)
            # - No shell=True (prevents command injection)
            # - Timeout prevents hanging
            result = subprocess.run(  # nosec B603 B607
                [_GIT_COMMAND, "config", "--local", _GIT_CONFIG_KEY],
                capture_output=True,
                text=True,
                timeout=Timeout.VERSION_CHECK,
                check=False,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
            logger.debug("Failed to check git fileMode: %s", exc)
            return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only match on new sessions (not resumes).

        Args:
            hook_input: SessionStart hook input

        Returns:
            True for new sessions, False for resumes
        """
        return not self._is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check git core.fileMode and warn if disabled.

        Args:
            hook_input: SessionStart hook input

        Returns:
            HookResult with ALLOW decision and advisory context
        """
        filemode = self._get_filemode_setting()

        lines: list[str] = []

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
        elif filemode is None:
            # Not in a git repo or error - silently pass
            lines.append("GIT FILEMODE: Not in a git repository or unable to check")
        else:
            lines.append(f"GIT FILEMODE: core.fileMode={filemode} (OK)")

        return HookResult(decision=Decision.ALLOW, context=lines)

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
