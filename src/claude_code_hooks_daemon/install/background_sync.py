"""Sync a pulled daemon version change in the background (Plan 00477 Task 5.2).

A pull that changes ``daemon.expected_version`` leaves the gitignored clone at
the old version. ``version_check`` notices at SessionStart, and must not do the
sync inside that hook's time budget, so it starts
``bash .claude/provision.sh --background`` DETACHED and returns. The sync is
provision's own (tag fetch from the fixed URL, ``version.py`` check, the target
release's pre-deploy gate, venv rebuild, restart); this module only names the
files it records its progress in, reads them back, and starts the process.

``provision.sh`` writes one state file per target version, ``key=value`` lines:
``status`` (running | synced | failed | needs-reading), ``target``, ``from``,
``pid`` and ``detail``. The file existing is the marker that the target has been
attempted, so a target is synced in the background at most once; ``provision.sh``
also holds a lock while it runs, so two syncs never overlap.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

#: Under the daemon's untracked directory. Spelled in provision.sh as well
#: (``SYNC_STATE_DIR_NAME``); a test holds the two together.
SYNC_STATE_DIR_NAME: Final[str] = "background-sync"

#: The provision.sh argument that selects the background sync.
BACKGROUND_FLAG: Final[str] = "--background"

_STATE_SUFFIX: Final[str] = ".state"
_LOG_SUFFIX: Final[str] = ".log"


class SyncStatus(StrEnum):
    """How far a background sync to one target version got."""

    RUNNING = "running"
    SYNCED = "synced"
    FAILED = "failed"
    NEEDS_READING = "needs-reading"


class BackgroundSyncError(Exception):
    """The background sync could not be started."""


@dataclass(frozen=True)
class SyncRecord:
    """What provision.sh recorded about a background sync to one version."""

    status: SyncStatus
    from_version: str
    pid: int | None
    detail: str
    state_path: Path
    log_path: Path


def state_path(untracked_dir: Path, version: str) -> Path:
    """The state file of the background sync to ``version``."""
    return untracked_dir / SYNC_STATE_DIR_NAME / f"v{version}{_STATE_SUFFIX}"


def log_path(untracked_dir: Path, version: str) -> Path:
    """The log the background sync to ``version`` writes its output to."""
    return untracked_dir / SYNC_STATE_DIR_NAME / f"v{version}{_LOG_SUFFIX}"


def read_sync_record(untracked_dir: Path, version: str) -> SyncRecord | None:
    """Read what the background sync to ``version`` recorded.

    Returns None when no sync to it was ever started. A state file that cannot
    be read, or names no known status, is a FAILED record saying so: it exists
    only because a sync was attempted, and staying silent about it would hide
    that attempt's outcome. A RUNNING record whose process is gone is FAILED too.
    """
    path = state_path(untracked_dir, version)
    logs = log_path(untracked_dir, version)
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return _unreadable(path, logs, f"the state file {path} cannot be read ({exc})")

    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key] = value

    try:
        status = SyncStatus(fields.get("status", ""))
    except ValueError:
        return _unreadable(path, logs, f"the state file {path} names no known status")

    pid_text = fields.get("pid", "")
    pid = int(pid_text) if pid_text.isdigit() else None
    detail = fields.get("detail", "")
    if status is SyncStatus.RUNNING and pid is not None and not _process_alive(pid):
        status = SyncStatus.FAILED
        detail = (
            f"the sync process (pid {pid}) ended without recording a result "
            "(killed, or the machine restarted)"
        )
    return SyncRecord(
        status=status,
        from_version=fields.get("from", ""),
        pid=pid,
        detail=detail,
        state_path=path,
        log_path=logs,
    )


def _unreadable(path: Path, logs: Path, detail: str) -> SyncRecord:
    return SyncRecord(
        status=SyncStatus.FAILED,
        from_version="",
        pid=None,
        detail=detail,
        state_path=path,
        log_path=logs,
    )


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists and belongs to someone else: alive.
        return True
    return True


def launch_background_sync(
    provision_script: Path, project_root: Path, untracked_dir: Path, version: str
) -> Path:
    """Start ``provision.sh --background`` detached, and return at once.

    The process gets its own session, so the daemon restart it ends with does
    not take it down with the daemon that started it, and its output goes to the
    target version's log. A thread reaps it when it exits, so it never lingers
    as a zombie of a daemon that stays up (a sync that fails keeps the old one).

    Returns:
        The log the sync writes to.

    Raises:
        BackgroundSyncError: The script is missing, there is no bash, or the
            process could not be started.
    """
    if not provision_script.is_file():
        raise BackgroundSyncError(f"{provision_script} does not exist")
    bash = shutil.which("bash")
    if bash is None:
        raise BackgroundSyncError("no bash on PATH to run provision.sh with")

    logs = log_path(untracked_dir, version)
    try:
        logs.parent.mkdir(parents=True, exist_ok=True)
        with logs.open("a") as log:
            process = subprocess.Popen(
                [bash, str(provision_script), BACKGROUND_FLAG],
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except OSError as exc:
        raise BackgroundSyncError(f"could not start {provision_script}: {exc}") from exc

    threading.Thread(target=process.wait, name="background-sync-reaper", daemon=True).start()
    return logs
