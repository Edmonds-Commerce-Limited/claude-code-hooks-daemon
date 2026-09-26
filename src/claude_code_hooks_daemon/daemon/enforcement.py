"""Single daemon process enforcement.

Provides enforcement logic to prevent multiple daemon instances from running
simultaneously, particularly useful in container environments.
"""

import logging
import os
from pathlib import Path

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.paths import cleanup_pid_file, read_pid_file
from claude_code_hooks_daemon.daemon.process_verification import (
    find_all_daemon_processes,
    is_process_running,
)
from claude_code_hooks_daemon.daemon.server import _socket_is_live
from claude_code_hooks_daemon.utils.container_detection import is_container_environment
from claude_code_hooks_daemon.utils.safe_signal import (
    DaemonStop,
    RefusedSignalTarget,
    stop_verified_daemon,
)

logger = logging.getLogger(__name__)


def _stop_peer_daemon(pid: int, project_root: Path) -> str | None:
    """SIGTERM, then SIGKILL, one peer daemon once it is proven to be ours.

    Returns:
        None when the peer is gone, otherwise why it could not be stopped.
    """
    try:
        outcome = stop_verified_daemon(
            pid, project_root=project_root, grace_seconds=Timeout.PROCESS_KILL_WAIT
        )
    except (RefusedSignalTarget, PermissionError) as failure:
        return str(failure)
    return "it survived SIGKILL" if outcome is DaemonStop.SURVIVED else None


def enforce_single_daemon(
    config: Config,
    pid_path: Path,
    project_root: Path | None = None,
    socket_path: Path | None = None,
) -> None:
    """Enforce single daemon process constraint.

    In containers: Kills other daemon processes serving THIS project root
    (SIGTERM then SIGKILL). Daemons serving a different project root are never
    touched — critical when PID namespaces are shared between a container and
    its host (or between containers), where a system-wide kill would terminate
    an unrelated project's daemon.

    Outside containers: Only cleans up stale PID files (conservative).

    Defence-in-depth (Plan 00127, Decision 1 — REUSE): the daemon that owns a
    LIVE ``socket_path`` is a healthy shared incumbent we intend to reuse, never
    a process to kill. When ``socket_path`` is live and its PID-file PID is
    among the other daemons, that PID is excluded from the kill list. (In the
    common case ``cmd_start`` short-circuits to reuse BEFORE this runs, so this
    is a backstop.)

    Args:
        config: Daemon configuration
        pid_path: Path to PID file
        project_root: This daemon's project root, used to scope the search so a
            daemon serving a different project is never terminated. When
            ``None`` the search is system-wide (legacy behaviour).
        socket_path: This start's socket path. When the socket is live, its
            PID-file owner is spared from termination. ``None`` disables the
            spare (legacy behaviour).
    """
    # Check if enforcement is enabled
    if not config.daemon.enforce_single_daemon_process:
        logger.debug("Single daemon enforcement disabled, skipping check")
        return

    logger.info("Enforcing single daemon process constraint")

    # Detect if we're in a container
    in_container = is_container_environment()
    logger.debug(f"Container environment: {in_container}")

    # Find daemon processes scoped to our own project root (when known) so we
    # never terminate a daemon belonging to a different project.
    daemon_pids = find_all_daemon_processes(project_root=project_root)
    current_pid = os.getpid()

    # Remove current process from list
    other_daemons = [pid for pid in daemon_pids if pid != current_pid]

    # Spare the live incumbent that owns our socket (Plan 00127). If the socket
    # is live and its PID-file owner is among the peers, exclude it — it is the
    # healthy shared daemon we will reuse, not an orphan to reap.
    if socket_path is not None and _socket_is_live(socket_path):
        incumbent_pid = read_pid_file(str(pid_path))
        if incumbent_pid is not None and incumbent_pid in other_daemons:
            logger.info(f"Sparing live socket owner (PID {incumbent_pid}) from enforcement")
            other_daemons = [pid for pid in other_daemons if pid != incumbent_pid]

    logger.debug(f"Found {len(other_daemons)} other daemon process(es)")

    # In container: stop every other daemon of THIS project root. Each pid is
    # re-proven by stop_verified_daemon, so without a project root nothing can
    # be proven ours and nothing is signalled (Plan 00466 N59).
    if in_container and other_daemons and project_root is None:
        logger.error(
            f"Container environment: {len(other_daemons)} other daemon process(es) found, "
            "but no project root to prove they are this project's; signalling none"
        )
    elif in_container and other_daemons and project_root is not None:
        logger.warning(
            f"Container environment: Killing {len(other_daemons)} other daemon process(es)"
        )
        for pid in other_daemons:
            logger.info(f"Killing daemon process {pid}")
            failure = _stop_peer_daemon(pid, project_root)
            if failure is None:
                logger.info(f"Successfully killed daemon process {pid}")
            else:
                logger.error(f"Failed to kill daemon process {pid}: {failure}")

    # Outside container: Only clean up stale PID file (conservative)
    elif not in_container:
        logger.debug("Non-container environment: Using conservative cleanup")

        # Check if PID file exists and points to dead process
        pid_from_file = read_pid_file(str(pid_path))
        if pid_from_file is not None and not is_process_running(pid_from_file):
            logger.info(f"Cleaning up stale PID file: {pid_path} (PID {pid_from_file})")
            cleanup_pid_file(str(pid_path))
