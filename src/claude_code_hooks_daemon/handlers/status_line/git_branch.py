"""Git branch handler for status line.

Shows current git branch if the workspace is in a git repository.
Fails silently if not in a git repo or if git commands error.
"""

import logging
import subprocess  # nosec B404 - subprocess used for git commands only (trusted system tool)
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, Timeout
from claude_code_hooks_daemon.core import Handler, HookResult

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
                return HookResult(context=[f"| {branch}"])

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to get git branch: %s", e)
        except Exception as e:
            logger.error("Unexpected error in git branch handler: %s", e, exc_info=True)

        return HookResult(context=[])
