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

        FAIL FAST: Logs all errors at WARNING level for visibility.
        Returns None only for expected cases (not in git repo).

        Parses git remote origin URL to extract repo name.
        Handles both SSH and HTTPS URLs:
        - git@github.com:user/repo.git -> repo
        - https://github.com/user/repo.git -> repo

        Returns:
            Repository name or None if not in git repo
        """
        try:
            # TEMPORARY: Use CWD (will be replaced by ProjectContext in Plan 00014)
            project_root = Path.cwd()
            logger.info("GitRepoNameHandler: Attempting to get repo name from %s", project_root)

            if not project_root.exists():
                logger.warning("GitRepoNameHandler: Project root does not exist: %s", project_root)
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
                stderr = result.stderr.decode().strip()
                logger.info(
                    "GitRepoNameHandler: Not a git repository (expected in non-git projects): %s",
                    stderr or "no error output",
                )
                return None  # Expected: not in git repo

            toplevel = result.stdout.decode().strip()
            logger.info("GitRepoNameHandler: Git toplevel: %s", toplevel)

            # Get remote origin URL
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=project_root,
                capture_output=True,
                timeout=Timeout.GIT_STATUS_SHORT,
                check=False,
            )

            if result.returncode != 0:
                # No remote origin configured - FAIL FAST: warn and fall back to dir name
                stderr = result.stderr.decode().strip()
                logger.warning(
                    "GitRepoNameHandler: No git remote 'origin' configured, falling back to directory name. "
                    "Error: %s",
                    stderr or "no error output",
                )
                # Fall back to directory name
                dir_name = Path(toplevel).name if toplevel else None
                logger.info("GitRepoNameHandler: Using directory name as fallback: %s", dir_name)
                return dir_name

            remote_url = result.stdout.decode().strip()
            logger.info("GitRepoNameHandler: Git remote origin URL: %s", remote_url)

            # Parse repo name from URL
            # SSH format: git@github.com:user/repo.git
            # HTTPS format: https://github.com/user/repo.git

            if not remote_url:
                logger.warning("GitRepoNameHandler: Empty remote URL returned")
                return None

            # Extract last path component and remove .git suffix
            # Handle SSH format (user@host:path)
            if ":" in remote_url and "@" in remote_url:
                path_part = remote_url.split(":")[-1]
                logger.debug("GitRepoNameHandler: Parsed SSH path: %s", path_part)
            else:
                # Handle HTTPS format
                path_part = remote_url.split("/")[-1]
                logger.debug("GitRepoNameHandler: Parsed HTTPS path: %s", path_part)

            # Remove .git suffix
            repo_name = re.sub(r"\.git$", "", path_part)
            logger.info("GitRepoNameHandler: Extracted repo name: %s", repo_name)

            if not repo_name:
                logger.warning(
                    "GitRepoNameHandler: Failed to extract repo name from URL: %s", remote_url
                )
                return None

            return repo_name

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            # FAIL FAST: These should not happen in normal operation
            logger.warning("GitRepoNameHandler: Git command failed: %s", e, exc_info=True)
            return None
        except FileNotFoundError as e:
            # FAIL FAST: Git not installed
            logger.warning("GitRepoNameHandler: Git command not found: %s", e)
            return None
        except Exception as e:
            # FAIL FAST: Unexpected errors must be visible
            logger.error(
                "GitRepoNameHandler: Unexpected error getting repo name: %s", e, exc_info=True
            )
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
