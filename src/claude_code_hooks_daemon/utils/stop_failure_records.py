"""The daemon's record of turns that ended on an API error (Plan 00470 Task 3.1).

A ``StopFailure`` hook fires instead of ``Stop`` when a turn ends on an API error
(``remote-docs/code.claude.com/docs/en/hooks.md``, "StopFailure"). Claude Code
ignores that hook's output, so the only way to make the failure visible is to
write it down and show it elsewhere: the ``stop_failure_recorder`` handler
records it here and the status line reads it back.

Only the errors that stop a persistent session until a human or a credential
changes are recorded (``RECORDED_ERRORS``); ``overloaded`` and ``server_error``
are transient and the next prompt simply retries.

**Resolution.** A failure is resolved once the same session submits a later
prompt (``stop_failure_resolver``). A prompt is the one event every way of
continuing passes through -- a human typing, a cron tick, a resume -- and a
turn that succeeds always began with one. A prompt that fails again records a
newer failure, which is unresolved again. No successful-``Stop`` signal is
needed: a Stop cannot follow a StopFailure without a prompt in between.

**History is bounded by count** (``MAX_RECORDS``, oldest dropped first). The
daemon keeps no registry of live sessions, so age is no more trustworthy a
signal than count, and a few dozen small records are the whole cost.

**Writes fail open** like the cron records: a recorder that raised would take a
hook down for the sake of bookkeeping.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.blockage_marker import write_json_atomically

logger = logging.getLogger(__name__)

#: Placed under ``ProjectContext.daemon_untracked_dir()``, beside the cron records.
STOP_FAILURE_RECORDS_FILENAME: Final[str] = "stop-failures.json"

#: The ``error`` values worth surfacing, spelled as the hooks reference spells them.
RECORDED_ERRORS: Final[frozenset[str]] = frozenset(
    {"rate_limit", "authentication_failed", "cloud_credential_error"}
)

#: Newest records kept; older ones are dropped on write.
MAX_RECORDS: Final[int] = 50

_KEY_RECORDS: Final[str] = "records"
_FIELD_SESSION_ID: Final[str] = "session_id"
_FIELD_ERROR: Final[str] = "error"
_FIELD_RECORDED_AT: Final[str] = "recorded_at"
_FIELD_RESOLVED_AT: Final[str] = "resolved_at"

#: The epoch-seconds range a record time must fall in: 1970 up to the last
#: second of year 9999, the largest time ``datetime`` can represent.
_MIN_EPOCH_SECONDS: Final[int] = 0
_MAX_EPOCH_SECONDS: Final[int] = 253_402_300_799

#: Hook events dispatch on concurrent threads of the one daemon process, and a
#: record is a read-modify-write of one file.
_WRITE_LOCK: Final[threading.Lock] = threading.Lock()


@dataclass(frozen=True)
class StopFailureRecord:
    """One turn that ended on an API error, and whether the session has moved on."""

    session_id: str
    error: str
    recorded_at: float
    resolved_at: float | None = None


def default_records_path() -> Path | None:
    """The project's record file, or None when there is no project context."""
    if not ProjectContext.is_initialized():
        logger.debug("stop_failure_records: no project context, so no records")
        return None
    return ProjectContext.daemon_untracked_dir() / STOP_FAILURE_RECORDS_FILENAME


def epoch_seconds(value: object) -> float | None:
    """``value`` as a float when it is a representable epoch time, else None.

    A bool is not a number here. ``json.loads`` accepts ``NaN``, ``Infinity`` and
    integers too large for a float; the range test rejects all three before any
    conversion (every comparison with NaN is false), so ``datetime.fromtimestamp``
    is never handed a value it cannot represent.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not _MIN_EPOCH_SECONDS <= value <= _MAX_EPOCH_SECONDS:
        return None
    return float(value)


def _parse_entry(entry: object) -> StopFailureRecord | None:
    if not isinstance(entry, dict):
        return None
    session_id = entry.get(_FIELD_SESSION_ID)
    error = entry.get(_FIELD_ERROR)
    recorded_at = epoch_seconds(entry.get(_FIELD_RECORDED_AT))
    raw_resolved = entry.get(_FIELD_RESOLVED_AT)
    resolved_at = epoch_seconds(raw_resolved)
    if not isinstance(session_id, str) or not isinstance(error, str) or recorded_at is None:
        return None
    if raw_resolved is not None and resolved_at is None:
        return None
    return StopFailureRecord(
        session_id=session_id, error=error, recorded_at=recorded_at, resolved_at=resolved_at
    )


def read_records(path: Path) -> list[StopFailureRecord]:
    """Every well-formed record in ``path``; ``[]`` on a missing or corrupt file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("stop_failure_records: unreadable %s: %s", path, exc)
        return []
    entries = raw.get(_KEY_RECORDS) if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    return [record for record in map(_parse_entry, entries) if record is not None]


def _write(path: Path, records: list[StopFailureRecord]) -> bool:
    """Write ``records``; False (logged) when the file could not be written."""
    payload = {
        _KEY_RECORDS: [
            {
                _FIELD_SESSION_ID: record.session_id,
                _FIELD_ERROR: record.error,
                _FIELD_RECORDED_AT: record.recorded_at,
                _FIELD_RESOLVED_AT: record.resolved_at,
            }
            for record in records
        ]
    }
    try:
        write_json_atomically(path, payload)
    except OSError as exc:
        logger.warning("stop_failure_records: failed to write %s: %s", path, exc)
        return False
    return True


def record_failure(path: Path, record: StopFailureRecord) -> bool:
    """Append ``record``, keeping only the newest ``MAX_RECORDS``. False when not written."""
    with _WRITE_LOCK:
        kept = [*read_records(path), record][-MAX_RECORDS:]
        return _write(path, kept)


def resolve_session(path: Path, session_id: str, *, now: float) -> bool:
    """Mark this session's unresolved failures resolved at ``now``; write only on a change.

    Returns:
        False when a needed write failed; True when the file is current.
    """
    with _WRITE_LOCK:
        before = read_records(path)
        after = [
            (
                replace(r, resolved_at=now)
                if r.session_id == session_id and r.resolved_at is None
                else r
            )
            for r in before
        ]
        return after == before or _write(path, after)


def latest_unresolved(path: Path, session_id: str) -> StopFailureRecord | None:
    """The newest unresolved failure of ``session_id``, or None."""
    pending = [
        r for r in read_records(path) if r.session_id == session_id and r.resolved_at is None
    ]
    return max(pending, key=lambda r: r.recorded_at, default=None)
