"""Process verification utilities for daemon enforcement.

This module provides system-wide daemon process detection and management,
particularly useful in container environments for single-process enforcement.
"""

import logging
import os

import psutil

from claude_code_hooks_daemon.constants import Timeout

logger = logging.getLogger(__name__)

# Process name pattern to search for
DAEMON_PROCESS_NAME = "claude_code_hooks_daemon"


def find_all_daemon_processes() -> list[int]:
    """Find all daemon processes running on the system.

    Searches for processes with 'claude_code_hooks_daemon' in their name or command line.
    This is a system-wide search, not project-specific.

    Returns:
        List of PIDs for all daemon processes found (excluding current process).

    Note:
        - Ignores processes that raise AccessDenied or NoSuchProcess errors
        - Excludes the current process from results
        - Case-sensitive matching for 'claude_code_hooks_daemon'
    """
    daemon_pids: list[int] = []
    current_pid = os.getpid()

    for proc in psutil.process_iter():
        try:
            pid = proc.pid
            name = proc.name()
            cmdline = proc.cmdline()

            # Skip current process
            if pid == current_pid:
                continue

            # Check if daemon name appears in process name or cmdline
            if _is_daemon_process(name, cmdline):
                daemon_pids.append(pid)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process disappeared or we don't have permission - skip it
            continue

    return daemon_pids


def kill_daemon_process(pid: int) -> bool:
    """Safely terminate a daemon process.

    Uses SIGTERM first, waits 2 seconds, then SIGKILL if needed.

    Args:
        pid: Process ID to terminate

    Returns:
        True if process was successfully terminated, False otherwise.

    Note:
        - Refuses to kill current process (safety check)
        - Returns False for non-existent PIDs
        - Returns False for permission denied errors
    """
    # Safety check: never kill current process
    if pid == os.getpid():
        logger.warning(f"Refusing to kill current process (PID {pid})")
        return False

    try:
        process = psutil.Process(pid)

        # Try graceful termination first (SIGTERM)
        logger.info(f"Terminating daemon process (PID {pid})")
        process.terminate()

        # Wait up to 2 seconds for process to exit
        try:
            process.wait(timeout=Timeout.PROCESS_KILL_WAIT)
        except psutil.TimeoutExpired:
            # Process didn't exit, force kill (SIGKILL)
            logger.warning(f"Process {pid} did not respond to SIGTERM, using SIGKILL")
            process.kill()

        # Verify termination
        if not process.is_running():
            logger.info(f"Successfully killed daemon process (PID {pid})")
            return True

        logger.error(f"Failed to kill daemon process (PID {pid})")
        return False

    except psutil.NoSuchProcess:
        logger.debug(f"Process {pid} does not exist")
        return False

    except psutil.AccessDenied:
        logger.error(f"Permission denied to kill process {pid}")
        return False


def is_process_running(pid: int) -> bool:
    """Check if a process is currently running.

    Args:
        pid: Process ID to check

    Returns:
        True if process exists and is running, False otherwise.

    Note:
        Returns False for permission denied errors (conservative approach).
    """
    try:
        process = psutil.Process(pid)
        return bool(process.is_running())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _is_daemon_process(name: str | None, cmdline: list[str] | None) -> bool:
    """Check if process name or cmdline indicates a daemon process.

    Args:
        name: Process name from psutil
        cmdline: Command line arguments from psutil

    Returns:
        True if process appears to be a daemon process, False otherwise.

    Note:
        - Case-sensitive exact substring match for 'claude_code_hooks_daemon'
        - Checks both process name and command line arguments
    """
    # Check process name
    if name and DAEMON_PROCESS_NAME in name:
        return True

    # Check command line
    if cmdline:
        cmdline_str = " ".join(cmdline)
        if DAEMON_PROCESS_NAME in cmdline_str:
            return True

    return False
