"""Git repository name handler for status line.

Shows the repository name at the start of the status line.
Calculated once at first invocation and cached for performance.
Fails silently if not in a git repo.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, Timeout
from claude_code_hooks_daemon.core import Handler, HookResult

logger = logging.getLogger(__name__)


class GitRepoNameHandler(Handler):
    """Show git repository name at start of status line."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_REPO_NAME,
            priority=Priority.GIT_REPO_NAME,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.GIT, HandlerTag.NON_TERMINAL],
        )
        self._repo_name: str | None = None  # Cached repo name
        self._initialized: bool = False  # Whether we've attempted to get repo name

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Get repository name and format for status line.

        Calculates repo name once on first call and caches it for performance.

        Args:
            hook_input: Status event input with workspace data

        Returns:
            HookResult with formatted repo name, or empty if not in git repo
        """
        # Return cached result if already initialized
        if self._initialized:
            if self._repo_name:
                return HookResult(context=[f"[{self._repo_name}]"])
            return HookResult(context=[])

        # First time - calculate and cache
        self._initialized = True
        workspace = hook_input.get("workspace", {})
        cwd = workspace.get("current_dir") or workspace.get("project_dir")

        if not cwd or not Path(cwd).exists():
            return HookResult(context=[])

        try:
            # Get git toplevel directory
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cwd,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )

            if result.returncode != 0:
                return HookResult(context=[])  # Not a git repo

            toplevel = result.stdout.decode().strip()
            if toplevel:
                # Extract repo name from path
                self._repo_name = Path(toplevel).name

                return HookResult(context=[f"[{self._repo_name}]"])

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to get git repo name: %s", e)
        except Exception as e:
            logger.error("Unexpected error in git repo name handler: %s", e, exc_info=True)

        return HookResult(context=[])
