"""Teardown for a test that started real daemons: stop them, tolerate one exiting.

A daemon that is already shutting down has an empty command line for a moment,
which ``stop_verified_daemon`` rightly refuses to identify. For a teardown that
process is as good as stopped, so it is not an error; a live process that is
genuinely not a daemon still is (N268).
"""

from __future__ import annotations

import time
from pathlib import Path

import psutil

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.process_verification import find_all_daemon_processes
from claude_code_hooks_daemon.utils.safe_signal import RefusedSignalTarget, stop_verified_daemon

#: How often an exiting process is looked at again.
_POLL_SECONDS = 0.1
_POLLS = int(Timeout.PROCESS_DEATH_WAIT / _POLL_SECONDS)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _is_exiting(pid: int) -> bool:
    """True if ``pid`` is gone, a zombie, or shows an empty command line for a
    bounded number of looks. Any command line that appears means a live
    process, which is not exiting."""
    for _ in range(_POLLS):
        try:
            process = psutil.Process(pid)
            if process.status() == psutil.STATUS_ZOMBIE:
                return True
            if process.cmdline():
                return False
        except psutil.NoSuchProcess:
            return True
        _sleep(_POLL_SECONDS)
    return True


def stop_daemons_of(project_root: Path | str, *, grace_seconds: float) -> None:
    """Stop every daemon serving ``project_root`` through the verified path.

    A launcher stopped mid-start may already have forked the daemon it was
    launching, which the scan that found the launcher could not see (N527). So
    the project is scanned again after each round of stops, until a scan finds
    nothing it has not already stopped.

    Raises:
        RefusedSignalTarget: A live process that is not this project's daemon.
        RuntimeError: Daemons were still appearing after every round allowed.
    """
    stopped: set[int] = set()
    for _ in range(_POLLS):
        new = [
            pid
            for pid in find_all_daemon_processes(project_root=project_root)
            if pid not in stopped
        ]
        if not new:
            return
        for pid in new:
            stopped.add(pid)
            try:
                stop_verified_daemon(pid, project_root=project_root, grace_seconds=grace_seconds)
            except RefusedSignalTarget:
                if not _is_exiting(pid):
                    raise
    raise RuntimeError(f"daemons of {project_root} kept appearing while they were stopped")
