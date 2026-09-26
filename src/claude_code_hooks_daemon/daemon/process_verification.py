"""Process verification utilities for daemon enforcement.

This module provides system-wide daemon process detection and management,
particularly useful in container environments for single-process enforcement.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import psutil

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.paths import is_self_install_mode, prospective_socket_path

logger = logging.getLogger(__name__)

# The CLI module that, given a launch subcommand, becomes the daemon server.
# Matching requires this exact module token PLUS a launch subcommand (below) so
# that transient CLI helpers (status/stop/logs/...) and the per-event hook
# forwarders (the bash wrappers' python3 socket transport) are never mistaken
# for a daemon server.
DAEMON_CLI_MODULE: Final = "claude_code_hooks_daemon.daemon.cli"

# The ONLY subcommands that daemonize. Daemonization (os.fork x2, os.setsid,
# HooksDaemon(...), asyncio.run(daemon.start())) lives solely in cmd_start,
# reachable only from the ``start`` subcommand and from cmd_restart (the
# ``restart`` subcommand), which calls cmd_start. os.fork does not rewrite argv,
# so a start-launched daemon's cmdline carries ``start`` and a restart-launched
# one carries ``restart``. This allowlist is therefore provably complete — every
# real daemon server is matched (zero false negatives). If a future subcommand
# daemonizes, add it here; a unit test guards this tuple.
_DAEMON_LAUNCH_SUBCOMMANDS = ("start", "restart")

# Command-line flag that explicitly names a daemon's project root.
_PROJECT_ROOT_FLAG = "--project-root"

# Where a client install keeps the daemon, below the project it serves.
_CLIENT_DAEMON_DIR = (".claude", "hooks-daemon")


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

            # Skip current process
            if pid == current_pid:
                continue

            # Matching is cmdline-only: a daemon server is identified by the cli
            # module token plus a launch subcommand. cmdline() also raises
            # NoSuchProcess/AccessDenied for inaccessible processes, which the
            # except below skips.
            cmdline = proc.cmdline()
            if not _is_daemon_server_process(cmdline):
                continue

            # Scope to our own project root when requested. A daemon whose root
            # cannot be determined is left alone — never terminated.
            if target_root is not None:
                proc_root = _root_from_flag(cmdline) or _root_from_listening_socket(proc)
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


def _root_from_flag(cmdline: list[str]) -> str | None:
    """Extract the project root from a ``--project-root`` command-line flag."""
    for index, token in enumerate(cmdline):
        if token == _PROJECT_ROOT_FLAG and index + 1 < len(cmdline):
            return _normalize_root(cmdline[index + 1])
        prefix = f"{_PROJECT_ROOT_FLAG}="
        if token.startswith(prefix):
            return _normalize_root(token[len(prefix) :])
    return None


def _project_of_socket(path: Path) -> str | None:
    """The project whose daemon binds ``path`` as its natural socket, or None.

    A client install's socket is ``{root}/.claude/hooks-daemon/untracked/...``
    and a self-install's ``{root}/untracked/...``. A client install's daemon
    clone is itself a self-install tree, but ``get_project_path`` never
    serves it, so a socket there belongs to the project holding the clone.
    """
    untracked = path.parent
    if untracked.name != "untracked":
        return None
    candidate = untracked.parent
    if (candidate.parent.name, candidate.name) == _CLIENT_DAEMON_DIR:
        candidate = candidate.parent.parent
    natural = prospective_socket_path(candidate, self_install=is_self_install_mode(candidate))
    return _normalize_root(candidate) if natural == path else None


def _root_from_listening_socket(process: psutil.Process) -> str | None:
    """The project whose natural socket ``process`` has bound, or None.

    A daemon started without ``--project-root`` serves the project its
    working directory finds, and leaves that directory at once
    (``os.chdir("/")``). Its interpreter's venv names only the install it
    runs from, which a worktree can share (Plan 00466 round 6, Sh-1). The
    socket it binds names the project it serves. A socket anywhere else (an
    override, the AF_UNIX-overflow fallback), or those of two projects,
    prove nothing.
    """
    try:
        if hasattr(process, "net_connections"):
            connections = process.net_connections(kind="unix")
        else:
            connections = process.connections(kind="unix")
    except psutil.Error as e:
        logger.debug("Cannot read the sockets of PID %d: %s", process.pid, e)
        return None
    roots: set[str] = set()
    for connection in connections:
        # A unix socket's address is its path, which psutil's stubs do not
        # say: they type every address as an (ip, port) pair.
        address: object = connection.laddr
        if isinstance(address, str) and address.startswith("/"):
            root = _project_of_socket(Path(address))
            if root is not None:
                roots.add(root)
    if len(roots) != 1:
        return None
    return roots.pop()


@dataclass(frozen=True)
class RootProof:
    """Which project a pid's daemon serves, or why that cannot be proven.

    Exactly one of ``root`` and ``refusal`` is set. ``source`` says where the
    root came from, so a caller refusing on a mismatch can say how the pid was
    attributed.
    """

    root: str | None
    refusal: str | None
    source: str | None = None


_FLAG_SOURCE: Final = f"its {_PROJECT_ROOT_FLAG} flag"
_SOCKET_SOURCE: Final = "the socket it listens on"


def is_this_users_process(pid: int) -> bool:
    """True when ``pid``'s real and effective uids are both this process's
    effective uid.

    Ownership is the owner's uid, never permission to signal (Plan 00466
    round 6, P5-1): root may signal every process, so a process of another
    user's passed as this user's whenever the hook ran as root.
    """
    # type() rather than isinstance(): see daemon_process_project_root.
    if type(pid) is not int or pid <= 1:
        return False
    try:
        uids = psutil.Process(pid).uids()
    except psutil.Error as e:
        logger.debug("Cannot read the owner of PID %d: %s", pid, e)
        return False
    euid = os.geteuid()
    return bool(uids.real == euid and uids.effective == euid)


def daemon_process_project_root(pid: int) -> RootProof:
    """Prove which real project root a live daemon SERVER pid serves.

    This is the proof a caller needs before it signals ``pid`` on behalf of one
    project: compare ``root`` with that project's own ``os.path.realpath``.
    ``realpath`` is safe here, unlike in :func:`_normalize_root`, because a pid
    this process can signal lives in its own mount namespace.

    Args:
        pid: Candidate process id.

    Returns:
        A proof with the resolved root, or with the reason there is none:
        ``pid`` is not a real ``int`` above 1, is this process, is gone or
        inaccessible, is not a daemon server, or neither its command line nor
        the socket it listens on names a project.
    """
    # type() rather than isinstance(): a bool is an int, and a MagicMock pid
    # coerces to 1 through __index__ (Plan 00466 N59), so neither is a pid.
    if type(pid) is not int or pid <= 1 or pid == os.getpid():
        return RootProof(root=None, refusal=f"{pid!r} is not a pid another process can own")
    try:
        process = psutil.Process(pid)
        cmdline = process.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        logger.debug("Cannot inspect PID %d cmdline: %s", pid, e)
        return RootProof(root=None, refusal=f"PID {pid} cannot be inspected ({type(e).__name__})")
    if not _is_daemon_server_process(cmdline):
        return RootProof(root=None, refusal=f"PID {pid} is not a hooks daemon server")
    flag_root = _root_from_flag(cmdline)
    if flag_root is not None:
        return RootProof(root=os.path.realpath(flag_root), refusal=None, source=_FLAG_SOURCE)
    socket_root = _root_from_listening_socket(process)
    if socket_root is not None:
        return RootProof(root=os.path.realpath(socket_root), refusal=None, source=_SOCKET_SOURCE)
    return RootProof(
        root=None,
        refusal=f"PID {pid} is a daemon server whose command line names no project, "
        "nor does a socket it listens on",
    )


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


def _is_daemon_server_process(cmdline: list[str] | None) -> bool:
    """Check if a command line identifies a daemon SERVER process.

    A daemon server is launched via ``python -m {cli module} [global flags]
    {start|restart}``. We require BOTH the cli module token AND a launch
    subcommand appearing after it. This deliberately excludes:

    - transient CLI helpers (``status``, ``stop``, ``logs``, ``health``,
      ``repair``, ``check-truth-changes``, ``generate-docs``, ``validate-*``, …)
    - the per-event hook forwarders (the bash wrappers' python3 socket transport)
    - a bare ``cli`` invocation with no subcommand

    none of which are daemon servers and so must never be terminated by
    single-daemon enforcement.

    Args:
        cmdline: Command line arguments from psutil.

    Returns:
        True only if the cmdline is a daemon server invocation.

    Note:
        Case-sensitive matching. See ``_DAEMON_LAUNCH_SUBCOMMANDS`` for why the
        allowlist is provably complete (zero false negatives).
    """
    if not cmdline:
        return False

    module_index: int | None = None
    for index, token in enumerate(cmdline):
        if DAEMON_CLI_MODULE in token:
            module_index = index
            break
    if module_index is None:
        return False

    # A launch subcommand must appear AFTER the module token (global flags such
    # as ``--project-root PATH`` may sit between the module and the subcommand).
    return any(token in _DAEMON_LAUNCH_SUBCOMMANDS for token in cmdline[module_index + 1 :])
