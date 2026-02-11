"""
Path management for daemon Unix socket and PID files.

Generates unique socket and PID file paths based on project directory,
enabling multi-project daemon isolation.

SECURITY: All runtime files stored in daemon's untracked directory,
not /tmp, to prevent security vulnerabilities.
"""

import contextlib
import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# AF_UNIX socket path limit (108 bytes on Linux, 104 bytes on macOS)
# Use conservative limit for cross-platform compatibility
_UNIX_SOCKET_PATH_LIMIT = 104


def _get_hostname_suffix() -> str:
    """
    Get hostname-based suffix for runtime files.

    Uses HOSTNAME environment variable directly to isolate daemon runtime
    files across different environments (containers, machines).

    Returns:
        "-{sanitized-hostname}" or "-{time-hash}" if no hostname

    Example:
        HOSTNAME="laptop" -> "-laptop"
        HOSTNAME="506355bfbc76" -> "-506355bfbc76"
        HOSTNAME="My-Server" -> "-my-server"
        No HOSTNAME -> "-a1b2c3d4" (MD5 of timestamp)
    """
    hostname = os.environ.get("HOSTNAME", "")

    # No hostname? Use MD5 of current time for uniqueness
    if not hostname:
        import time

        timestamp = str(time.time())
        hash_obj = hashlib.md5(timestamp.encode("utf-8"), usedforsecurity=False)
        return f"-{hash_obj.hexdigest()[:8]}"

    # Sanitize hostname for filesystem safety: lowercase, no spaces
    sanitized = hostname.lower().replace(" ", "-")
    return f"-{sanitized}"


def get_project_hash(project_path: Path | str) -> str:
    """
    Generate a short hash from the absolute project path.

    Args:
        project_path: Absolute path to project directory

    Returns:
        First 8 characters of MD5 hash of absolute path
    """
    abs_path = str(Path(project_path).resolve())
    # MD5 used only for generating short path identifier, not for security
    hash_obj = hashlib.md5(abs_path.encode("utf-8"), usedforsecurity=False)
    return hash_obj.hexdigest()[:8]


def get_project_name(project_path: Path | str) -> str:
    """
    Extract sanitized project name from path, truncated to 20 characters.

    Args:
        project_path: Path to project directory

    Returns:
        Last component of path (directory name), truncated to 20 chars for readability
    """
    name = Path(project_path).resolve().name
    # Truncate to 20 characters for readability in /tmp/
    return name[:20]


def _get_fallback_runtime_dir(project_dir: Path, filename: str) -> Path:
    """
    Get fallback path when project path exceeds Unix socket length limit.

    Tries directories in order of preference:
    1. $XDG_RUNTIME_DIR (standard on modern Linux)
    2. /run/user/{uid} (common on Linux)
    3. /tmp (last resort, with warning logged)

    Args:
        project_dir: Resolved project directory path
        filename: File extension without dot (e.g. "sock", "pid", "log")

    Returns:
        Path in a shorter directory using project hash for uniqueness
    """
    project_hash = get_project_hash(project_dir)
    base_name = f"hooks-daemon-{project_hash}"

    # Try XDG_RUNTIME_DIR first (standard)
    xdg_dir = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_dir and Path(xdg_dir).is_dir():
        fallback_dir = Path(xdg_dir)
        logger.info("Socket path too long, using XDG_RUNTIME_DIR: %s", fallback_dir)
        return fallback_dir / f"{base_name}.{filename}"

    # Try /run/user/{uid} (common on Linux)
    run_user = Path(f"/run/user/{os.getuid()}")
    if run_user.is_dir():
        logger.info("Socket path too long, using /run/user: %s", run_user)
        return run_user / f"{base_name}.{filename}"

    # Last resort: /tmp (with warning)
    logger.warning(
        "Socket path too long and no XDG_RUNTIME_DIR or /run/user available. "
        "Using /tmp for runtime files. Set CLAUDE_HOOKS_SOCKET_PATH to override."
    )
    return Path("/tmp") / f"{base_name}.{filename}"  # nosec B108 - /tmp is last resort fallback


def _get_untracked_dir(project_path: Path) -> Path:
    """
    Get the untracked directory for daemon runtime files.

    Detects self-install mode (daemon source at project root) to use the
    shorter path, avoiding unnecessary `.claude/hooks-daemon/` nesting.

    Args:
        project_path: Resolved absolute project directory path

    Returns:
        - Self-install mode: {project}/untracked
        - Normal mode: {project}/.claude/hooks-daemon/untracked
    """
    # Self-install mode: daemon source exists at project root
    if (project_path / "src" / "claude_code_hooks_daemon").is_dir():
        return project_path / "untracked"
    return project_path / ".claude" / "hooks-daemon" / "untracked"


def get_socket_path(project_dir: Path | str) -> Path:
    """
    Generate Unix socket path for project-specific daemon.

    SECURITY: Stored in daemon's untracked directory, not /tmp.
    Pattern: {project}/.claude/hooks-daemon/untracked/daemon.sock
    Container: {project}/.claude/hooks-daemon/untracked/daemon-{hash}.sock

    Can be overridden via CLAUDE_HOOKS_SOCKET_PATH environment variable
    (useful for testing to avoid collision with production daemon).

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for Unix socket file

    Example:
        >>> get_socket_path(Path('/home/dev/alpha'))
        Path('/home/dev/alpha/.claude/hooks-daemon/untracked/daemon.sock')
    """
    # Allow environment variable override for testing
    if env_path := os.environ.get("CLAUDE_HOOKS_SOCKET_PATH"):
        return Path(env_path)

    # Use daemon's untracked directory (secure, project-specific)
    # Self-install mode uses shorter path: {project}/untracked/
    # Normal mode uses: {project}/.claude/hooks-daemon/untracked/
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    untracked_dir.mkdir(parents=True, exist_ok=True)

    # Add hostname-based suffix for isolation
    suffix = _get_hostname_suffix()
    path = untracked_dir / f"daemon{suffix}.sock"

    # Fallback if path exceeds AF_UNIX socket length limit
    if len(str(path)) > _UNIX_SOCKET_PATH_LIMIT:
        return _get_fallback_runtime_dir(project_path, "sock")

    return path


def get_pid_path(project_dir: Path | str) -> Path:
    """
    Generate PID file path for project-specific daemon.

    SECURITY: Stored in daemon's untracked directory, not /tmp.
    Pattern: {project}/.claude/hooks-daemon/untracked/daemon.pid
    Self-install: {project}/untracked/daemon.pid
    Container: daemon-{hostname}.pid

    Can be overridden via CLAUDE_HOOKS_PID_PATH environment variable
    (useful for testing to avoid collision with production daemon).

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for PID file

    Example:
        >>> get_pid_path(Path('/home/dev/alpha'))
        Path('/home/dev/alpha/.claude/hooks-daemon/untracked/daemon.pid')
    """
    # Allow environment variable override for testing
    if env_path := os.environ.get("CLAUDE_HOOKS_PID_PATH"):
        return Path(env_path)

    # Use daemon's untracked directory (secure, project-specific)
    # Self-install mode uses shorter path: {project}/untracked/
    # Normal mode uses: {project}/.claude/hooks-daemon/untracked/
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    untracked_dir.mkdir(parents=True, exist_ok=True)

    # Add hostname-based suffix for isolation
    suffix = _get_hostname_suffix()
    path = untracked_dir / f"daemon{suffix}.pid"

    # Fallback if path exceeds AF_UNIX socket length limit (consistency with socket)
    if len(str(path)) > _UNIX_SOCKET_PATH_LIMIT:
        return _get_fallback_runtime_dir(project_path, "pid")

    return path


def get_log_path(project_dir: Path | str) -> Path:
    """
    Generate log file path for project-specific daemon.

    SECURITY: Stored in daemon's untracked directory, not /tmp.
    Pattern: {project}/.claude/hooks-daemon/untracked/daemon.log
    Self-install: {project}/untracked/daemon.log
    Container: daemon-{hostname}.log

    Can be overridden via CLAUDE_HOOKS_LOG_PATH environment variable
    (useful for testing to avoid collision with production daemon).

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for log file

    Example:
        >>> get_log_path(Path('/home/dev/alpha'))
        Path('/home/dev/alpha/.claude/hooks-daemon/untracked/daemon.log')
    """
    # Allow environment variable override for testing
    if env_path := os.environ.get("CLAUDE_HOOKS_LOG_PATH"):
        return Path(env_path)

    # Use daemon's untracked directory (secure, project-specific)
    # Self-install mode uses shorter path: {project}/untracked/
    # Normal mode uses: {project}/.claude/hooks-daemon/untracked/
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    untracked_dir.mkdir(parents=True, exist_ok=True)

    # Add hostname-based suffix for isolation
    suffix = _get_hostname_suffix()
    path = untracked_dir / f"daemon{suffix}.log"

    # Fallback if path exceeds AF_UNIX socket length limit (consistency with socket)
    if len(str(path)) > _UNIX_SOCKET_PATH_LIMIT:
        return _get_fallback_runtime_dir(project_path, "log")

    return path


def is_pid_alive(pid: int) -> bool:
    """
    Check if process with given PID is running.

    Args:
        pid: Process ID to check

    Returns:
        True if process exists and is running
    """
    try:
        # Send signal 0 - no actual signal sent, just checks if process exists
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't access it
        return True
    except (OSError, TypeError, ValueError) as e:
        logger.debug("PID check failed for %d: %s", pid, e)
        return False
    except Exception as e:
        logger.error("Unexpected error checking PID %d: %s", pid, e, exc_info=True)
        return False


def read_pid_file(pid_path: Path | str) -> int | None:
    """
    Read PID from file and verify process is alive.

    Args:
        pid_path: Path to PID file (Path object or string)

    Returns:
        PID if file exists and process is alive, None otherwise
    """
    pid_path = Path(pid_path)
    try:
        with pid_path.open() as f:
            pid = int(f.read().strip())

        if is_pid_alive(pid):
            return pid
        else:
            # Stale PID file, clean it up
            with contextlib.suppress(Exception):
                pid_path.unlink()
            return None
    except FileNotFoundError:
        return None
    except ValueError as e:
        logger.debug("Invalid PID value in %s: %s", pid_path, e)
        return None
    except (OSError, PermissionError) as e:
        logger.debug("Failed to read PID file %s: %s", pid_path, e)
        return None


def write_pid_file(pid_path: Path | str, pid: int) -> None:
    """
    Write PID to file.

    Args:
        pid_path: Path to PID file (Path object or string)
        pid: Process ID to write
    """
    pid_path = Path(pid_path)
    with pid_path.open("w") as f:
        f.write(str(pid))


def cleanup_socket(socket_path: Path | str) -> None:
    """
    Remove Unix socket file if it exists.

    Args:
        socket_path: Path to socket file (Path object or string)
    """
    try:
        socket_path = Path(socket_path)
        if socket_path.exists():
            socket_path.unlink()
    except (OSError, PermissionError) as e:
        logger.warning("Failed to cleanup socket %s: %s", socket_path, e)
    except Exception as e:
        logger.error("Unexpected error cleaning socket %s: %s", socket_path, e, exc_info=True)


def cleanup_pid_file(pid_path: Path | str) -> None:
    """
    Remove PID file if it exists.

    Args:
        pid_path: Path to PID file (Path object or string)
    """
    try:
        pid_path = Path(pid_path)
        if pid_path.exists():
            pid_path.unlink()
    except (OSError, PermissionError) as e:
        logger.warning("Failed to cleanup PID file %s: %s", pid_path, e)
    except Exception as e:
        logger.error("Unexpected error cleaning PID file %s: %s", pid_path, e, exc_info=True)
