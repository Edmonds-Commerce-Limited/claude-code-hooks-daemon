"""The daemon's own record of when each session cron was created (Plan 00470 Task 2.1).

Recurring crons auto-expire after 7 days, and ``session_crons`` (the Stop
payload's list of live crons) carries no creation time. So the daemon cannot
read a job's age from the payload, and has to write it down itself: the
``cron_record_keeper`` PostToolUse handler records each ``CronCreate`` here and
forgets each ``CronDelete``, and ``cron_stop_enforcer`` reads the age back to
refresh a job before it dies.

**The record never holds the prompt.** A prompt is a long instruction, may name
private work, and is not needed: matching is by cron id, and the fingerprint
below is enough to tell two jobs apart when debugging the file.

**Pruning records of sessions that are gone.** The daemon keeps no registry of
live sessions, so liveness is read from the two signals it does have:

1. *Age.* A recurring cron cannot outlive ``CRON_EXPIRY_SECONDS``, so a record
   that old describes a cron that no longer exists whatever became of its
   session. Every write drops them, which bounds the file for sessions that
   ended without a trace (a killed container, a ``startup`` that replaced a
   session). A future-dated record is clock skew or corruption and is dropped
   too.
2. *The session's own report.* ``session_crons`` lists exactly the crons alive
   in a session, so a Stop that omits a recorded id proves it was deleted or has
   expired (``forget_missing``).

A session that ends and is never seen again leaves its records until signal 1
removes them, at most 7 days later. That is deliberate: there is no
"session ended" event this module could trust for a killed process, and the
leftover is a few hundred bytes.

**Writes fail open** like the blockage marker: a recorder that raised would take
a ``CronCreate`` hook down for the sake of bookkeeping. A lost record costs one
thing, a job stamped as first seen at its next Stop instead of at creation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.blockage_marker import write_json_atomically
from claude_code_hooks_daemon.utils.cron_enforcement import normalise_prompt

logger = logging.getLogger(__name__)

#: Placed under ``ProjectContext.daemon_untracked_dir()``, beside the cron pauses.
CRON_RECORDS_FILENAME: Final[str] = "cron-records.json"

_SECONDS_PER_DAY: Final[int] = 24 * 60 * 60
_CRON_EXPIRY_DAYS: Final[int] = 7

#: A recurring cron's lifetime. Platform fact recorded in
#: ``persistent_cron_assertor``'s docstring; a record this old is dead.
CRON_EXPIRY_SECONDS: Final[float] = float(_CRON_EXPIRY_DAYS * _SECONDS_PER_DAY)

#: Seconds in a day, for options expressed in days.
SECONDS_PER_DAY: Final[float] = float(_SECONDS_PER_DAY)

#: How old a declared cron may get before a Stop is denied until it is refreshed.
#: One day below the expiry, for two reasons that both need slack: the refresh
#: only lands on a Stop, and in an idle session a Stop is an hourly tick, so
#: the window must hold many ticks (24 a day) in case some are dropped while
#: the session waits on a human; and the platform documents the expiry only as
#: "7 days", without saying how it counts, so the margin absorbs the difference.
DEFAULT_REFRESH_AFTER_DAYS: Final[float] = 6.0

_KEY_RECORDS: Final[str] = "records"
_FIELD_SESSION_ID: Final[str] = "session_id"
_FIELD_CRON_ID: Final[str] = "cron_id"
_FIELD_SCHEDULE: Final[str] = "schedule"
_FIELD_PROMPT_HASH: Final[str] = "prompt_hash"
_FIELD_CREATED_AT: Final[str] = "created_at"

#: Hook events dispatch on concurrent threads of the one daemon process, and a
#: record is a read-modify-write of one file.
_WRITE_LOCK: Final[threading.Lock] = threading.Lock()


@dataclass(frozen=True)
class CronRecord:
    """One session cron and the moment it was created."""

    session_id: str
    cron_id: str
    schedule: str
    prompt_hash: str
    created_at: float

    @property
    def key(self) -> tuple[str, str]:
        """What identifies a record: a cron id is only unique within its session."""
        return (self.session_id, self.cron_id)


def prompt_fingerprint(prompt: str) -> str:
    """A hash of the prompt's words, stable across layout and the tick sentinel."""
    return hashlib.sha256(normalise_prompt(prompt).encode("utf-8")).hexdigest()


def default_records_path() -> Path | None:
    """The project's record file, or None when there is no project context."""
    if not ProjectContext.is_initialized():
        logger.debug("cron_records: no project context, so no records")
        return None
    return ProjectContext.daemon_untracked_dir() / CRON_RECORDS_FILENAME


def _parse_entry(entry: object) -> CronRecord | None:
    if not isinstance(entry, dict):
        return None
    session_id = entry.get(_FIELD_SESSION_ID)
    cron_id = entry.get(_FIELD_CRON_ID)
    schedule = entry.get(_FIELD_SCHEDULE)
    prompt_hash = entry.get(_FIELD_PROMPT_HASH)
    created_at = entry.get(_FIELD_CREATED_AT)
    if not all(isinstance(v, str) for v in (session_id, cron_id, schedule, prompt_hash)):
        return None
    if isinstance(created_at, bool) or not isinstance(created_at, (int, float)):
        return None
    return CronRecord(
        session_id=str(session_id),
        cron_id=str(cron_id),
        schedule=str(schedule),
        prompt_hash=str(prompt_hash),
        created_at=float(created_at),
    )


def read_records(path: Path) -> list[CronRecord]:
    """Every well-formed record in ``path``; ``[]`` on a missing or corrupt file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("cron_records: unreadable %s: %s", path, exc)
        return []
    entries = raw.get(_KEY_RECORDS) if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    return [record for record in map(_parse_entry, entries) if record is not None]


def _is_possible(record: CronRecord, now: float) -> bool:
    """Whether a cron created at ``record.created_at`` can still exist at ``now``."""
    return 0 <= now - record.created_at < CRON_EXPIRY_SECONDS


def _write(path: Path, records: list[CronRecord]) -> bool:
    """Write ``records``; False (logged) when the file could not be written."""
    payload = {
        _KEY_RECORDS: [
            {
                _FIELD_SESSION_ID: record.session_id,
                _FIELD_CRON_ID: record.cron_id,
                _FIELD_SCHEDULE: record.schedule,
                _FIELD_PROMPT_HASH: record.prompt_hash,
                _FIELD_CREATED_AT: record.created_at,
            }
            for record in records
        ]
    }
    try:
        write_json_atomically(path, payload)
    except OSError as exc:
        logger.warning("cron_records: failed to write %s: %s", path, exc)
        return False
    return True


def _rewrite(
    path: Path, now: float, *, drop: Collection[tuple[str, str]], add: CronRecord | None
) -> bool:
    """Prune impossible records, drop ``drop``, add ``add``, and write only on a change.

    Returns:
        False when a needed write failed; True when the file is current.
    """
    with _WRITE_LOCK:
        before = read_records(path)
        kept = [r for r in before if _is_possible(r, now) and r.key not in drop]
        if add is not None:
            kept = [r for r in kept if r.key != add.key]
            kept.append(add)
        return kept == before or _write(path, kept)


def record_cron(path: Path, record: CronRecord, *, now: float) -> bool:
    """Record ``record``, replacing any earlier record of the same cron; prune the dead."""
    return _rewrite(path, now, drop=(), add=record)


def forget_cron(path: Path, *, session_id: str, cron_id: str, now: float) -> bool:
    """Forget one cron (a ``CronDelete``); prune the dead. A no-op for an unknown cron."""
    return _rewrite(path, now, drop={(session_id, cron_id)}, add=None)


def forget_missing(path: Path, *, session_id: str, live_ids: Collection[str], now: float) -> bool:
    """Forget this session's records whose id its ``session_crons`` no longer lists."""
    stale = {
        record.key
        for record in read_records(path)
        if record.session_id == session_id and record.cron_id not in live_ids
    }
    return _rewrite(path, now, drop=stale, add=None)
