"""
Path management for daemon Unix socket and PID files.

Generates unique socket and PID file paths based on project directory,
enabling multi-project daemon isolation.
"""

import contextlib
import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def get_project_hash(project_path: Path | str) -> str:
    """
    Generate a short hash from the absolute project path.

    Args:
        project_path: Absolute path to project directory

    Returns:
        First 8 characters of MD5 hash of absolute path
    """
    abs_path = str(Path(project_path).resolve())
    hash_obj = hashlib.md5(abs_path.encode("utf-8"))
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


def get_socket_path(project_dir: Path | str) -> Path:
    """
    Generate Unix socket path for project-specific daemon.

    Pattern: /tmp/claude-hooks-{project-name}-{hash}.sock

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for Unix socket file

    Example:
        >>> get_socket_path(Path('/home/dev/alpha'))
        Path('/tmp/claude-hooks-alpha-a1b2c3d4.sock')
    """
    project_name = get_project_name(project_dir)
    project_hash = get_project_hash(project_dir)
    return Path(f"/tmp/claude-hooks-{project_name}-{project_hash}.sock")


def get_pid_path(project_dir: Path | str) -> Path:
    """
    Generate PID file path for project-specific daemon.

    Pattern: /tmp/claude-hooks-{project-name}-{hash}.pid

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for PID file

    Example:
        >>> get_pid_path(Path('/home/dev/alpha'))
        Path('/tmp/claude-hooks-alpha-a1b2c3d4.pid')
    """
    project_name = get_project_name(project_dir)
    project_hash = get_project_hash(project_dir)
    return Path(f"/tmp/claude-hooks-{project_name}-{project_hash}.pid")


def get_log_path(project_dir: Path | str) -> Path:
    """
    Generate log file path for project-specific daemon.

    Pattern: /tmp/claude-hooks-{project-name}-{hash}.log

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for log file

    Example:
        >>> get_log_path(Path('/home/dev/alpha'))
        Path('/tmp/claude-hooks-alpha-a1b2c3d4.log')
    """
    project_name = get_project_name(project_dir)
    project_hash = get_project_hash(project_dir)
    return Path(f"/tmp/claude-hooks-{project_name}-{project_hash}.log")


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
