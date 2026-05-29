"""Process verification utilities for daemon enforcement.

This module provides system-wide daemon process detection and management,
particularly useful in container environments for single-process enforcement.
"""

import logging
import os
from pathlib import Path

import psutil

from claude_code_hooks_daemon.constants import Timeout

logger = logging.getLogger(__name__)

# Process name pattern to search for
DAEMON_PROCESS_NAME = "claude_code_hooks_daemon"

# Command-line flag that explicitly names a daemon's project root.
_PROJECT_ROOT_FLAG = "--project-root"

# Path fragments that mark the start of a daemon's venv directory, ordered from
# most-specific to least-specific. The text preceding the matched fragment in
# the interpreter path is the daemon's project root. The normal-install layout
# nests its untracked dir under ``.claude/hooks-daemon/`` so that fragment MUST
# be tested before the bare self-install fragment, otherwise a normal-install
# path would resolve to ``{root}/.claude/hooks-daemon`` instead of ``{root}``.
_VENV_PATH_MARKERS = (
    "/.claude/hooks-daemon/untracked/venv",
    "/untracked/venv",
)


def find_all_daemon_processes(project_root: str | Path | None = None) -> list[int]:
    """Find daemon processes running on the system.

    Searches for processes with 'claude_code_hooks_daemon' in their name or command line.

    Args:
        project_root: When provided, the search is scoped to daemons whose own
            project root matches this path. Daemons serving a different project
            root — and daemons whose project root cannot be positively
            determined — are excluded. When ``None`` the search is system-wide
            (legacy behaviour).

    Returns:
        List of PIDs for matching daemon processes (excluding current process).

    Note:
        - Ignores processes that raise AccessDenied or NoSuchProcess errors
        - Excludes the current process from results
        - Case-sensitive matching for 'claude_code_hooks_daemon'
        - Project-root scoping NEVER kills a daemon we cannot attribute to the
          requested project (fail-safe against cross-project termination).
    """
    daemon_pids: list[int] = []
    current_pid = os.getpid()
    target_root = _normalize_root(project_root) if project_root is not None else None

    for proc in psutil.process_iter():
        try:
            pid = proc.pid
            name = proc.name()
            cmdline = proc.cmdline()

            # Skip current process
            if pid == current_pid:
                continue

            # Check if daemon name appears in process name or cmdline
            if not _is_daemon_process(name, cmdline):
                continue

            # Scope to our own project root when requested. A daemon whose root
            # cannot be determined is left alone — never terminated.
            if target_root is not None:
                proc_root = _extract_project_root(cmdline)
                if proc_root is None or proc_root != target_root:
                    continue

            daemon_pids.append(pid)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process disappeared or we don't have permission - skip it
            continue

    return daemon_pids


def _normalize_root(root: str | Path) -> str:
    """Normalise a project-root path for cross-process string comparison.

    Uses ``os.path.normpath`` only — never ``resolve()`` — because daemon
    processes may reference paths inside other mount namespaces (e.g. a
    container's ``/workspace``) that do not exist on this side of the boundary.
    """
    return os.path.normpath(str(root))


def _extract_project_root(cmdline: list[str] | None) -> str | None:
    """Derive a daemon process's project root from its command line.

    Resolution order:
        1. An explicit ``--project-root PATH`` (or ``--project-root=PATH``) flag.
        2. The project root embedded in the interpreter's venv path
           (``{root}/untracked/venv...`` or
           ``{root}/.claude/hooks-daemon/untracked/venv...``).

    Returns:
        The normalised project root, or ``None`` when it cannot be determined.
    """
    if not cmdline:
        return None

    flag_root = _root_from_flag(cmdline)
    if flag_root is not None:
        return flag_root

    return _root_from_interpreter(cmdline[0])


def _root_from_flag(cmdline: list[str]) -> str | None:
    """Extract the project root from a ``--project-root`` command-line flag."""
    for index, token in enumerate(cmdline):
        if token == _PROJECT_ROOT_FLAG and index + 1 < len(cmdline):
            return _normalize_root(cmdline[index + 1])
        prefix = f"{_PROJECT_ROOT_FLAG}="
        if token.startswith(prefix):
            return _normalize_root(token[len(prefix) :])
    return None


def _root_from_interpreter(interpreter: str) -> str | None:
    """Extract the project root from the daemon interpreter's venv path."""
    for marker in _VENV_PATH_MARKERS:
        if marker in interpreter:
            return _normalize_root(interpreter.split(marker, 1)[0])
    return None


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
