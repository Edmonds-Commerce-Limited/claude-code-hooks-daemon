"""Installation validation functions for the hooks daemon.

Provides validation functions to prevent nested installations and detect
the hooks-daemon repository. Used by both install.py and daemon/cli.py.
"""

import logging
import subprocess  # nosec B404 - subprocess used for git commands only (trusted system tool)
import tomllib
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import ConfigKey, Timeout

logger = logging.getLogger(__name__)

# The [project].name this repository declares in its own pyproject.toml. Used as
# an offline signal for "project_root IS the hooks-daemon repo itself" so the
# installer can distinguish that from a consumer project that merely cloned the
# daemon into .claude/hooks-daemon/ as a dependency (Issue #3).
_DAEMON_PACKAGE_NAME = "claude-code-hooks-daemon"


class InstallationError(Exception):
    """Error during installation validation."""

    pass


# Memoisation for is_hooks_daemon_repo (Plan 00155 T1). The result forks
# `git remote get-url origin`, which daemon_restart_verifier would otherwise
# run on EVERY Bash PreToolUse event (~1.4 ms p50, ~75% of the Bash-event
# daemon-side cost). A repo's origin URL cannot change under a running daemon
# in any way that matters, so the answer is cached per directory — one fork per
# daemon lifetime instead of one per event. A stale entry would require someone
# re-pointing `origin` mid-daemon; a restart heals it (see _clear cache below).
_REPO_DETECTION_CACHE: dict[Path, bool] = {}


def _clear_repo_detection_cache() -> None:
    """Empty the is_hooks_daemon_repo memoisation cache.

    Used by tests for isolation; also available if a caller ever needs to force
    re-resolution (e.g. after deliberately re-pointing the git remote).
    """
    _REPO_DETECTION_CACHE.clear()


def _detect_hooks_daemon_repo(directory: Path) -> bool:
    """Fork git to determine whether ``directory`` is the hooks-daemon repo.

    This is the uncached implementation; ``is_hooks_daemon_repo`` memoises it.
    """
    try:
        result = subprocess.run(  # nosec B603 B607 - git is trusted system tool, no user input
            ["git", "-C", str(directory), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=Timeout.VALIDATION_CHECK,
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


def is_hooks_daemon_repo(directory: Path) -> bool:
    """Check if directory is the hooks-daemon repository by git remote.

    Uses git remote URL as source of truth rather than magic path detection.
    This correctly identifies the hooks-daemon repo even if cloned with a
    different directory name.

    The result is memoised per ``directory`` (Plan 00155 T1) so hot callers
    such as daemon_restart_verifier fork git at most once per daemon lifetime
    rather than once per Bash event. Call ``_clear_repo_detection_cache`` to
    force re-resolution.

    Args:
        directory: Directory to check

    Returns:
        True if directory is the hooks-daemon repository
    """
    cached = _REPO_DETECTION_CACHE.get(directory)
    if cached is not None:
        return cached
    result = _detect_hooks_daemon_repo(directory)
    _REPO_DETECTION_CACHE[directory] = result
    return result


def project_root_is_daemon_repo(project_root: Path) -> bool:
    """Return True if ``project_root`` itself is the hooks-daemon repository.

    Detected offline via ``pyproject.toml`` ``[project].name`` matching this
    package, so it works without a git remote. This is the correct signal for
    "the install target IS the daemon repo" (the self-install case) and, crucially,
    does NOT fire for a consumer project that merely cloned the daemon into
    ``.claude/hooks-daemon/`` as a dependency — the documented manual-install
    layout, which creates ``.claude/hooks-daemon/src`` at the *consumer's* root
    (Issue #3).

    Args:
        project_root: Directory to check.

    Returns:
        True if ``project_root/pyproject.toml`` declares the daemon package.
    """
    pyproject = project_root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.debug("Failed to parse %s for daemon-repo detection: %s", pyproject, e)
        return False
    project_table = data.get("project")
    if not isinstance(project_table, dict):
        return False
    return project_table.get("name") == _DAEMON_PACKAGE_NAME


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
    except (OSError, PermissionError, yaml.YAMLError) as e:
        logger.debug("Failed to load config from %s: %s", config_file, e)
        return None
    except Exception as e:
        logger.error("Unexpected error loading config %s: %s", config_file, e, exc_info=True)
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
    # Delegate nested install check to single source of truth
    nested_error = check_for_nested_installation(project_root)
    if nested_error:
        raise InstallationError(nested_error)

    # Fail fast only if project_root ITSELF is the hooks-daemon repo being
    # installed without self_install_mode. A consumer project that merely cloned
    # the daemon into .claude/hooks-daemon/ (the documented manual-install
    # layout, which creates .claude/hooks-daemon/src at the consumer root) is NOT
    # this case and must be allowed through — previously this over-broad marker
    # check blocked every legitimate manual install (Issue #3).
    if project_root_is_daemon_repo(project_root):
        # Check for self_install_mode in the repo's own config
        config = load_config_safe(project_root)
        if config:
            daemon_config = config.get(ConfigKey.DAEMON, {})
            if daemon_config.get(ConfigKey.SELF_INSTALL_MODE, False):
                return  # Self-install mode enabled, allow

        raise InstallationError(
            f"Cannot install: {project_root} is the hooks-daemon repository itself.\n"
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
    if (project_root / ".git").exists() and is_hooks_daemon_repo(project_root):
        # Check if self-install is being requested or already configured
        config = load_config_safe(project_root)
        has_self_install_config = config and config.get(ConfigKey.DAEMON, {}).get(
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


def is_inside_daemon_directory(candidate: Path) -> bool:
    """Check if a candidate path is inside a .claude/hooks-daemon/ directory tree.

    When the hooks-daemon repo is installed at {project}/.claude/hooks-daemon/
    and git checkout brings the repo's own .claude/ (self-install dogfooding files),
    path detection can find {project}/.claude/hooks-daemon/.claude/ first and
    incorrectly use .claude/hooks-daemon/ as the project root.

    This function detects that scenario by checking if consecutive path components
    contain ".claude" followed by "hooks-daemon".

    Args:
        candidate: Path to check (typically a candidate project root)

    Returns:
        True if path is inside a .claude/hooks-daemon/ directory tree
    """
    parts = candidate.resolve().parts
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "hooks-daemon":
            return True
    return False


def check_for_nested_installation(project_root: Path) -> str | None:
    """Check for nested installation and actively clean it up.

    If .claude/hooks-daemon/.claude/hooks-daemon exists, it is a nested install
    artifact (runtime files created when daemon used the wrong project root).
    This function removes it and allows startup to continue.

    Args:
        project_root: Project root to check

    Returns:
        Error message string if cleanup fails, None otherwise
    """
    nested_install = project_root / ".claude" / "hooks-daemon" / ".claude" / "hooks-daemon"
    if nested_install.exists():
        # If the outer .claude/hooks-daemon IS the hooks-daemon repo itself
        # (identified by having pyproject.toml), then the inner .claude/hooks-daemon
        # is just the repo's own dogfooding config directory, not a genuine nested
        # installation. Skip the false positive.
        outer_hooks_daemon = project_root / ".claude" / "hooks-daemon"
        if (outer_hooks_daemon / "pyproject.toml").is_file():
            return None

        # Actively remove the nested install artifacts
        import shutil

        logger.warning("Removing nested install artifacts: %s", nested_install)
        shutil.rmtree(nested_install)

    return None
