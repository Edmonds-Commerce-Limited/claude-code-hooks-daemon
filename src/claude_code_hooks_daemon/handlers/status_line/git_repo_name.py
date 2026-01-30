"""Git repository name handler for status line.

Shows the repository name at the start of the status line.
Calculated once at handler initialization (daemon startup) and cached.
Parses git remote URL to get actual repo name, not directory name.
Fails silently if not in a git repo.
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, Timeout
from claude_code_hooks_daemon.core import Handler, HookResult

logger = logging.getLogger(__name__)


class GitRepoNameHandler(Handler):
    """Show git repository name at start of status line.

    Calculates repo name once at initialization (daemon startup) by parsing
    git remote URL. Cached for performance.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_REPO_NAME,
            priority=Priority.GIT_REPO_NAME,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.GIT, HandlerTag.NON_TERMINAL],
        )
        # Calculate repo name once at startup
        self._repo_name: str | None = self._get_repo_name()

    def _get_repo_name(self) -> str | None:
        """Get repository name from git remote URL.

        Parses git remote origin URL to extract repo name.
        Handles both SSH and HTTPS URLs:
        - git@github.com:user/repo.git -> repo
        - https://github.com/user/repo.git -> repo

        Returns:
            Repository name or None if not in git repo
        """
        try:
            # Use current working directory (where daemon was started)
            project_root = Path.cwd()
            if not project_root.exists():
                return None

            # Check if in git repo
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=project_root,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )

            if result.returncode != 0:
                return None  # Not a git repo

            # Get remote origin URL
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=project_root,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )

            if result.returncode != 0:
                # No remote origin configured - fall back to directory name
                toplevel = (
                    subprocess.run(
                        ["git", "rev-parse", "--show-toplevel"],
                        cwd=project_root,
                        capture_output=True,
                        timeout=Timeout.GIT_STATUS_SHORT,
                        check=True,
                    )
                    .stdout.decode()
                    .strip()
                )
                return Path(toplevel).name if toplevel else None

            remote_url = result.stdout.decode().strip()

            # Parse repo name from URL
            # SSH format: git@github.com:user/repo.git
            # HTTPS format: https://github.com/user/repo.git

            # Extract last path component and remove .git suffix
            if remote_url:
                # Handle SSH format (user@host:path)
                if ":" in remote_url and "@" in remote_url:
                    path_part = remote_url.split(":")[-1]
                else:
                    # Handle HTTPS format
                    path_part = remote_url.split("/")[-1]

                # Remove .git suffix
                repo_name = re.sub(r"\.git$", "", path_part)
                return repo_name if repo_name else None

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Failed to get git repo name: %s", e)
        except Exception as e:
            logger.error("Unexpected error in git repo name handler init: %s", e, exc_info=True)

        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return cached repository name for status line.

        Args:
            hook_input: Status event input (not used, repo name cached at init)

        Returns:
            HookResult with formatted repo name, or empty if not available
        """
        if self._repo_name:
            return HookResult(context=[f"[{self._repo_name}]"])
        return HookResult(context=[])
