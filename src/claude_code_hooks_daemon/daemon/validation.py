"""Installation validation functions for the hooks daemon.

Provides validation functions to prevent nested installations and detect
the hooks-daemon repository. Used by both install.py and daemon/cli.py.
"""

import subprocess
from pathlib import Path
from typing import Any


class InstallationError(Exception):
    """Error during installation validation."""

    pass


def is_hooks_daemon_repo(directory: Path) -> bool:
    """Check if directory is the hooks-daemon repository by git remote.

    Uses git remote URL as source of truth rather than magic path detection.
    This correctly identifies the hooks-daemon repo even if cloned with a
    different directory name.

    Args:
        directory: Directory to check

    Returns:
        True if directory is the hooks-daemon repository
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        remote_url = result.stdout.strip().lower()
        # Match any of the known hooks-daemon repo URLs
        hooks_daemon_patterns = [
            "claude-code-hooks-daemon",
            "claude_code_hooks_daemon",
        ]
        return any(pattern in remote_url for pattern in hooks_daemon_patterns)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def load_config_safe(project_root: Path) -> dict[str, Any] | None:
    """Safely load config file without raising exceptions.

    Args:
        project_root: Project root directory

    Returns:
        Config dict or None if loading fails
    """
    import yaml

    config_file = project_root / ".claude" / "hooks-daemon.yaml"
    if not config_file.exists():
        return None

    try:
        with config_file.open() as f:
            result: dict[str, Any] | None = yaml.safe_load(f)
            return result
    except Exception:
        return None


def validate_not_nested(project_root: Path) -> None:
    """Fail fast if nested installation detected.

    Checks for two scenarios:
    1. Existing nested structure (.claude/hooks-daemon/.claude)
    2. Trying to install in the hooks-daemon repo without self_install_mode

    Args:
        project_root: Project root to validate

    Raises:
        InstallationError: If nested installation detected
    """
    # Check for existing nested structure
    nested_claude = project_root / ".claude" / "hooks-daemon" / ".claude"
    if nested_claude.exists():
        raise InstallationError(
            f"NESTED INSTALLATION DETECTED!\n"
            f"Found: {nested_claude}\n"
            f"Remove {project_root / '.claude' / 'hooks-daemon'} and reinstall."
        )

    # Check if we're inside an existing hooks-daemon directory
    hooks_daemon_marker = project_root / ".claude" / "hooks-daemon" / "src"
    if hooks_daemon_marker.exists():
        # Check for self_install_mode in the outer project's config
        config = load_config_safe(project_root)
        if config:
            daemon_config = config.get("daemon", {})
            if daemon_config.get("self_install_mode", False):
                return  # Self-install mode enabled, allow

        raise InstallationError(
            f"Cannot install: appears to be inside an existing hooks-daemon installation.\n"
            f"Found daemon source at: {hooks_daemon_marker}\n"
            f"To develop on hooks-daemon itself, set 'self_install_mode: true' in config."
        )


def validate_installation_target(project_root: Path, self_install_requested: bool = False) -> None:
    """Comprehensive pre-flight validation before installation.

    Validates:
    1. Not inside an existing hooks-daemon installation
    2. Not the hooks-daemon repo itself (unless self_install_mode)
    3. No nested structure exists

    Args:
        project_root: Project root to install into
        self_install_requested: Whether --self-install flag was passed

    Raises:
        InstallationError: If installation would create invalid state
    """
    # 1. Check not inside existing hooks-daemon installation
    for parent in project_root.parents:
        if (parent / ".claude" / "hooks-daemon").exists():
            raise InstallationError(
                f"Cannot install: {project_root} is inside an existing installation at {parent}"
            )

    # 2. Check git remote if this looks like a git repo
    if (project_root / ".git").exists():
        if is_hooks_daemon_repo(project_root):
            # Check if self-install is being requested or already configured
            config = load_config_safe(project_root)
            has_self_install_config = config and config.get("daemon", {}).get(
                "self_install_mode", False
            )

            if not self_install_requested and not has_self_install_config:
                raise InstallationError(
                    "This is the hooks-daemon repository.\n"
                    "To install for development, use --self-install flag or add to "
                    ".claude/hooks-daemon.yaml:\n"
                    "  daemon:\n"
                    "    self_install_mode: true"
                )

    # 3. Check for nested structure
    validate_not_nested(project_root)


def check_for_nested_installation(project_root: Path) -> str | None:
    """Check for nested installation and return error message if found.

    This is a lighter version of validate_not_nested that returns an error message
    instead of raising an exception. Used by CLI for runtime validation.

    Args:
        project_root: Project root to check

    Returns:
        Error message string if nested installation detected, None otherwise
    """
    # Check for existing nested structure
    nested_claude = project_root / ".claude" / "hooks-daemon" / ".claude"
    if nested_claude.exists():
        return (
            f"NESTED INSTALLATION DETECTED!\n"
            f"Found: {nested_claude}\n"
            f"Remove {project_root / '.claude' / 'hooks-daemon'} and reinstall."
        )

    return None
