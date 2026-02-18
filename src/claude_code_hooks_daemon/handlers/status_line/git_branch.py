"""Git branch handler for status line.

Shows current git branch if the workspace is in a git repository.
Fails silently if not in a git repo or if git commands error.
"""

import logging
import subprocess  # nosec B404 - subprocess used for git commands only (trusted system tool)
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, Timeout
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)


class GitBranchHandler(Handler):
    """Show current git branch if in a git repo."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_BRANCH,
            priority=Priority.GIT_BRANCH,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.GIT, HandlerTag.NON_TERMINAL],
        )
        self._default_branch: str | None = None
        self._default_branch_detected: bool = False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Get current git branch and format for status line.

        Args:
            hook_input: Status event input with workspace data

        Returns:
            HookResult with formatted git branch text, or empty if not in git repo
        """
        workspace = hook_input.get("workspace", {})
        cwd = workspace.get("current_dir") or workspace.get("project_dir")

        if not cwd or not Path(cwd).exists():
            return HookResult(context=[])

        try:
            # Check if in git repo
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )

            if result.returncode != 0:
                return HookResult(context=[])  # Not a git repo

            # Get current branch
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "branch", "--show-current"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=True,
            )

            branch = result.stdout.decode().strip()
            if branch:
                if not self._default_branch_detected:
                    self._default_branch = self._get_default_branch(cwd)
                    self._default_branch_detected = True
                green = "\033[32m"
                orange = "\033[38;5;208m"
                grey = "\033[37m"
                reset = "\033[0m"
                if self._default_branch is None:
                    color = grey
                elif branch == self._default_branch:
                    color = green
                else:
                    color = orange
                return HookResult(context=[f"| ⎇ {color}{branch}{reset}"])

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to get git branch: %s", e)
        except Exception as e:
            logger.error("Unexpected error in git branch handler: %s", e, exc_info=True)

        return HookResult(context=[])

    def _get_default_branch(self, cwd: str) -> str | None:
        """Detect the default branch for the repo.

        Strategy:
        1. Try git symbolic-ref refs/remotes/origin/HEAD (fast, no network)
        2. Fall back to checking if 'main' or 'master' exist locally
        3. Return None if undetermined (branch will be shown orange)
        """
        try:
            result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )
            if result.returncode == 0:
                # Output: refs/remotes/origin/main → extract "main"
                return result.stdout.decode().strip().split("/")[-1]

            # Fallback: check common default branch names locally
            for candidate in ("main", "master"):
                result = (
                    subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
                        ["git", "show-ref", "--verify", f"refs/heads/{candidate}"],
                        cwd=cwd,
                        capture_output=True,
                        timeout=Timeout.GIT_STATUS_SHORT,
                        check=False,
                    )
                )
                if result.returncode == 0:
                    return candidate
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to detect default branch: %s", e)

        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="git branch handler test",
                command='echo "test"',
                description="Tests git branch handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
            ),
        ]
