"""Single daemon process enforcement.

Provides enforcement logic to prevent multiple daemon instances from running
simultaneously, particularly useful in container environments.
"""

import logging
import os
from pathlib import Path

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.daemon.paths import cleanup_pid_file, read_pid_file
from claude_code_hooks_daemon.daemon.process_verification import (
    find_all_daemon_processes,
    is_process_running,
    kill_daemon_process,
)
from claude_code_hooks_daemon.utils.container_detection import is_container_environment

logger = logging.getLogger(__name__)


def enforce_single_daemon(config: Config, pid_path: Path) -> None:
    """Enforce single daemon process constraint.

    In containers: Kills all daemon processes except current process (system-wide).
    Outside containers: Only cleans up stale PID files (conservative).

    Args:
        config: Daemon configuration
        pid_path: Path to PID file
    """
    # Check if enforcement is enabled
    if not config.daemon.enforce_single_daemon_process:
        logger.debug("Single daemon enforcement disabled, skipping check")
        return

    logger.info("Enforcing single daemon process constraint")

    # Detect if we're in a container
    in_container = is_container_environment()
    logger.debug(f"Container environment: {in_container}")

    # Find all daemon processes
    daemon_pids = find_all_daemon_processes()
    current_pid = os.getpid()

    # Remove current process from list
    other_daemons = [pid for pid in daemon_pids if pid != current_pid]

    logger.debug(f"Found {len(other_daemons)} other daemon process(es)")

    # In container: Kill all other daemons (system-wide enforcement)
    if in_container and other_daemons:
        logger.warning(
            f"Container environment: Killing {len(other_daemons)} other daemon process(es)"
        )
        for pid in other_daemons:
            logger.info(f"Killing daemon process {pid}")
            if kill_daemon_process(pid):
                logger.info(f"Successfully killed daemon process {pid}")
            else:
                logger.error(f"Failed to kill daemon process {pid}")

    # Outside container: Only clean up stale PID file (conservative)
    elif not in_container:
        logger.debug("Non-container environment: Using conservative cleanup")

        # Check if PID file exists and points to dead process
        pid_from_file = read_pid_file(str(pid_path))
        if pid_from_file is not None and not is_process_running(pid_from_file):
            logger.info(f"Cleaning up stale PID file: {pid_path} (PID {pid_from_file})")
            cleanup_pid_file(str(pid_path))
