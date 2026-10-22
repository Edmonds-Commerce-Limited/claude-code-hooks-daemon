"""Sync a pulled daemon version change in the background (Plan 00477 Task 5.2).

A pull that changes ``daemon.expected_version`` leaves the gitignored clone at
the old version. The tracked session-start forwarder starts
``bash .claude/provision.sh --background`` DETACHED at every session start, in
shell, so neither the hook's time budget nor this daemon waits on it; it decides
for itself whether there is anything to sync. The sync is provision's own (tag
fetch from the fixed URL, ``version.py`` check, the target release's pre-deploy
gate, venv rebuild, restart). This module only names the files it records its
progress in and reads them back, for ``version_check`` to report.

``provision.sh`` writes one state file per target version, ``key=value`` lines:
``status`` (running | synced | failed | needs-reading), ``target``, ``from``,
``pid`` and ``detail``. The file existing is the marker that the target has been
attempted, so a target is synced in the background at most once; ``provision.sh``
also holds a lock while it runs, so two syncs never overlap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

#: Under the daemon's untracked directory. Spelled in provision.sh as well
#: (``SYNC_STATE_DIR_NAME``); a test holds the two together.
SYNC_STATE_DIR_NAME: Final[str] = "background-sync"

#: The provision.sh argument that selects the background sync. Spelled in the
#: session-start forwarder that passes it; a test holds the two together.
BACKGROUND_FLAG: Final[str] = "--background"

_STATE_SUFFIX: Final[str] = ".state"
_LOG_SUFFIX: Final[str] = ".log"


class SyncStatus(StrEnum):
    """How far a background sync to one target version got."""

    RUNNING = "running"
    SYNCED = "synced"
    FAILED = "failed"
    NEEDS_READING = "needs-reading"


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
    return read_state_file(state_path(untracked_dir, version), log_path(untracked_dir, version))


def read_state_file(path: Path, logs: Path) -> SyncRecord | None:
    """Read one ``key=value`` background-job state file, as :func:`read_sync_record` does.

    Shared with the detached relay repair (``relay_repair``), which records its
    progress in the same format so one reader judges both.
    """
    if not path.exists():
        return None
    try:
        text = path.read_text()
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
