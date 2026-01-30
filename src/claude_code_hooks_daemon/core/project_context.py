"""Project context singleton with calculated constants.

Provides authoritative project root, git repo name, and other project-level
constants calculated once at daemon startup and cached for the session.

This eliminates unreliable CWD usage throughout the codebase.

Usage:
    # In DaemonController.initialise():
    from claude_code_hooks_daemon.core.project_context import ProjectContext
    ProjectContext.initialize(config_path="/path/to/.claude/hooks-daemon.yaml")

    # In handlers:
    from claude_code_hooks_daemon.core.project_context import ProjectContext
    project_root = ProjectContext.project_root()
    repo_name = ProjectContext.git_repo_name()
"""

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from claude_code_hooks_daemon.constants import Timeout

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ProjectContextData:
    """Immutable data class holding calculated project constants.

    Attributes:
        project_root: Absolute path to project root directory
        config_path: Absolute path to hooks-daemon.yaml config file
        config_dir: Absolute path to .claude directory
        self_install_mode: True if daemon is running in self-install mode (dogfooding)
        git_repo_name: Repository name from git remote URL (FAIL FAST: always present)
        git_toplevel: Git repository root path (FAIL FAST: always present)
    """

    project_root: Path
    config_path: Path
    config_dir: Path
    self_install_mode: bool
    git_repo_name: str
    git_toplevel: Path


class ProjectContext:
    """Singleton providing authoritative project-level constants.

    Calculated once at daemon startup and cached for the session.
    FAIL FAST if accessed before initialization or if project root cannot be determined.
    """

    _instance: ClassVar[_ProjectContextData | None] = None
    _initialized: ClassVar[bool] = False

    @classmethod
    def initialize(cls, config_path: Path | str) -> None:
        """Initialize project context from config file path.

        This MUST be called exactly once during daemon startup before any handlers
        are registered or invoked.

        Args:
            config_path: Path to hooks-daemon.yaml config file

        Raises:
            RuntimeError: If already initialized (must only call once)
            ValueError: If config_path is invalid or project root cannot be determined
        """
        if cls._initialized:
            raise RuntimeError(
                "ProjectContext already initialized. "
                "initialize() must be called exactly once at daemon startup."
            )

        config_path = Path(config_path).resolve()

        # Validate config path
        if not config_path.exists():
            raise ValueError(f"Config file does not exist: {config_path}")

        if not config_path.is_file():
            raise ValueError(f"Config path is not a file: {config_path}")

        if config_path.name != "hooks-daemon.yaml":
            raise ValueError(
                f"Config file must be named 'hooks-daemon.yaml', got: {config_path.name}"
            )

        # Config directory is .claude/
        config_dir = config_path.parent
        if config_dir.name != ".claude":
            raise ValueError(f"Config file must be in .claude directory, got: {config_dir}")

        # Determine self-install mode by checking if daemon source exists at project root
        # Normal install: /project/.claude/hooks-daemon.yaml, daemon at /project/.claude/hooks-daemon/
        # Self-install: /project/.claude/hooks-daemon.yaml, daemon at /project/
        project_root_candidate = config_dir.parent  # Go up from .claude to project root

        daemon_src_at_root = (project_root_candidate / "src" / "claude_code_hooks_daemon").exists()
        self_install_mode = daemon_src_at_root

        if self_install_mode:
            project_root = project_root_candidate
            logger.info(
                "ProjectContext: Self-install mode detected (daemon source at project root)"
            )
        else:
            project_root = project_root_candidate
            logger.info("ProjectContext: Normal install mode (daemon in .claude/hooks-daemon/)")

        logger.info("ProjectContext: Project root: %s", project_root)
        logger.info("ProjectContext: Config path: %s", config_path)
        logger.info("ProjectContext: Config directory: %s", config_dir)

        # Calculate git values (FAIL FAST - must be in git repo)
        git_repo_name = cls._get_git_repo_name(project_root)
        if git_repo_name is None:
            raise ValueError(
                f"FAIL FAST: Project at {project_root} is not a git repository or has no remote origin. "
                "All projects must be in git repositories."
            )

        git_toplevel = cls._get_git_toplevel(project_root)
        if git_toplevel is None:
            raise ValueError(
                f"FAIL FAST: Cannot determine git toplevel for {project_root}. "
                "All projects must be in git repositories."
            )

        logger.info("ProjectContext: Git repo name: %s", git_repo_name)
        logger.info("ProjectContext: Git toplevel: %s", git_toplevel)

        # Store instance
        cls._instance = _ProjectContextData(
            project_root=project_root,
            config_path=config_path,
            config_dir=config_dir,
            self_install_mode=self_install_mode,
            git_repo_name=git_repo_name,
            git_toplevel=git_toplevel,
        )
        cls._initialized = True

        logger.info("ProjectContext initialized successfully")

    @classmethod
    def _get_git_repo_name(cls, project_root: Path) -> str | None:
        """Get repository name from git remote URL.

        Non-fatal: Returns None if not in git repo or if git operations fail.

        Args:
            project_root: Project root directory to check

        Returns:
            Repository name or None
        """
        try:
            # Check if in git repo
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=project_root,
                capture_output=True,
                timeout=Timeout.GIT_CONTEXT,
                check=False,
            )

            if result.returncode != 0:
                logger.info("ProjectContext: Not a git repository")
                return None

            # Get remote origin URL
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=project_root,
                capture_output=True,
                timeout=Timeout.GIT_CONTEXT,
                check=False,
            )

            if result.returncode != 0:
                logger.warning("ProjectContext: No git remote 'origin' configured")
                return None

            remote_url = result.stdout.decode().strip()
            if not remote_url:
                logger.warning("ProjectContext: Empty git remote URL")
                return None

            # Parse repo name from URL
            # SSH: git@github.com:user/repo.git -> repo
            # HTTPS: https://github.com/user/repo.git -> repo
            # Both formats: split by / and take last component
            path_part = remote_url.split("/")[-1]

            # Remove .git suffix
            repo_name = re.sub(r"\.git$", "", path_part)

            if not repo_name:
                logger.warning(
                    "ProjectContext: Failed to extract repo name from URL: %s", remote_url
                )
                return None

            return repo_name

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("ProjectContext: Git command failed: %s", e)
            return None
        except Exception as e:
            logger.error(
                "ProjectContext: Unexpected error getting git repo name: %s", e, exc_info=True
            )
            return None

    @classmethod
    def _get_git_toplevel(cls, project_root: Path) -> Path | None:
        """Get git repository root path.

        Non-fatal: Returns None if not in git repo.

        Args:
            project_root: Project root directory to check

        Returns:
            Git toplevel path or None
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=project_root,
                capture_output=True,
                timeout=Timeout.GIT_CONTEXT,
                check=False,
            )

            if result.returncode != 0:
                return None

            toplevel = result.stdout.decode().strip()
            return Path(toplevel) if toplevel else None

        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("ProjectContext: Git command failed: %s", e)
            return None
        except Exception as e:
            logger.error(
                "ProjectContext: Unexpected error getting git toplevel: %s", e, exc_info=True
            )
            return None

    @classmethod
    def _ensure_initialized(cls) -> None:
        """Ensure ProjectContext has been initialized.

        Raises:
            RuntimeError: If not initialized (FAIL FAST)
        """
        if not cls._initialized or cls._instance is None:
            raise RuntimeError(
                "ProjectContext not initialized. "
                "Call ProjectContext.initialize(config_path) during daemon startup."
            )

    @classmethod
    def project_root(cls) -> Path:
        """Get authoritative project root directory.

        Returns:
            Absolute path to project root

        Raises:
            RuntimeError: If ProjectContext not initialized
        """
        cls._ensure_initialized()
        assert cls._instance is not None  # For type checker
        return cls._instance.project_root

    @classmethod
    def config_path(cls) -> Path:
        """Get config file path.

        Returns:
            Absolute path to hooks-daemon.yaml

        Raises:
            RuntimeError: If ProjectContext not initialized
        """
        cls._ensure_initialized()
        assert cls._instance is not None
        return cls._instance.config_path

    @classmethod
    def config_dir(cls) -> Path:
        """Get .claude directory path.

        Returns:
            Absolute path to .claude directory

        Raises:
            RuntimeError: If ProjectContext not initialized
        """
        cls._ensure_initialized()
        assert cls._instance is not None
        return cls._instance.config_dir

    @classmethod
    def self_install_mode(cls) -> bool:
        """Check if running in self-install mode (dogfooding).

        Returns:
            True if daemon source is at project root (self-install/dogfooding mode)

        Raises:
            RuntimeError: If ProjectContext not initialized
        """
        cls._ensure_initialized()
        assert cls._instance is not None
        return cls._instance.self_install_mode

    @classmethod
    def git_repo_name(cls) -> str:
        """Get git repository name from remote URL.

        FAIL FAST: Always returns a value. If project is not in git repo,
        initialization would have already failed.

        Returns:
            Repository name

        Raises:
            RuntimeError: If ProjectContext not initialized
        """
        cls._ensure_initialized()
        assert cls._instance is not None
        return cls._instance.git_repo_name

    @classmethod
    def git_toplevel(cls) -> Path:
        """Get git repository root path.

        FAIL FAST: Always returns a value. If project is not in git repo,
        initialization would have already failed.

        Returns:
            Absolute path to git repository root

        Raises:
            RuntimeError: If ProjectContext not initialized
        """
        cls._ensure_initialized()
        assert cls._instance is not None
        return cls._instance.git_toplevel

    @classmethod
    def reset(cls) -> None:
        """Reset ProjectContext (for testing only).

        WARNING: Only use this in test teardown. Never call in production code.
        """
        cls._instance = None
        cls._initialized = False
