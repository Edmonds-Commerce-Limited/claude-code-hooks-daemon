"""Failsafe-cron cadence state (Plan 00337 Phase 4).

Plan 00298 gave the failsafe cron an all-or-nothing switch: a session that
DECLARES it is blocked only on human input has its ticks suppressed, and every
other session pays a full model turn per hour forever. Phase 4 adds the
middle -- a session that is producing nothing, but has not declared anything,
gets ticks less often rather than either always or never.

The state cannot live in ``blockage_marker``. That marker is cleared on any
real prompt and is ABSENT exactly in the case this backoff exists for
("nothing owed, nothing declared"), so sharing it would erase the counter
precisely when it is needed.

**Fail-open, like every path in this subsystem.** An unreadable or corrupt
state file reads as "no state", which allows the tick. A cadence bug that
denied everything would silently disable session recovery, and its symptom is
nothing happening -- strictly worse than a wasted turn, which is at least
visible.

**Backed off, never silent.** ``MAX_CADENCE_HOURS`` caps the doubling, because
the cron's whole purpose is recovering a session interrupted by a rate limit,
and a later tick genuinely helps once the limit lifts.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.permissions import FileMode

logger = logging.getLogger(__name__)

# Placed under ProjectContext.daemon_untracked_dir() by callers -- same
# directory convention as goal-ledger.json, stop-events.jsonl and the
# human-input blockage marker.
CADENCE_FILENAME: Final[str] = "failsafe-cron-cadence.json"

# The ceiling on doubling. Four hours is the point at which a further halving
# of cost buys almost nothing while the recovery delay starts to matter.
MAX_CADENCE_HOURS: Final[int] = 4

_INITIAL_CADENCE_HOURS: Final[int] = 1

_FIELD_SESSION_ID: Final[str] = "session_id"
_FIELD_DROPPED: Final[str] = "dropped_since_allowed"
_FIELD_CADENCE_HOURS: Final[str] = "cadence_hours"


@dataclass(frozen=True)
class CadenceState:
    """How sparse this session's failsafe-cron ticks currently are."""

    session_id: str
    dropped_since_allowed: int
    cadence_hours: int


def write_cadence(path: Path, state: CadenceState) -> bool:
    """Atomically (over)write the cadence state. Fail-open: never raises.

    Args:
        path: Full path to the cadence state file.
        state: The state to persist.

    Returns:
        True if written, False if an OSError was swallowed.
    """
    payload = {
        _FIELD_SESSION_ID: state.session_id,
        _FIELD_DROPPED: state.dropped_since_allowed,
        _FIELD_CADENCE_HOURS: state.cadence_hours,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # uuid suffix, not pid: hook events dispatch on concurrent threads of
        # the one daemon process (same rationale as blockage_marker.write).
        tmp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FileMode.PRIVATE_FILE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload))
        tmp_path.replace(path)
        return True
    except OSError as e:
        logger.warning("cron_cadence: failed to write %s: %s", path, e)
        return False


def read_cadence(path: Path) -> CadenceState | None:
    """Read the cadence state. Fail-open: missing/corrupt/malformed -> None.

    Args:
        path: Full path to the cadence state file.

    Returns:
        The parsed state, or None if it does not exist or cannot be trusted.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("cron_cadence: unreadable %s: %s", path, e)
        return None
    if not isinstance(raw, dict):
        return None
    session_id = raw.get(_FIELD_SESSION_ID)
    dropped = raw.get(_FIELD_DROPPED)
    cadence_hours = raw.get(_FIELD_CADENCE_HOURS)
    if not isinstance(session_id, str):
        return None
    # bool subclasses int, so a JSON `true` here would silently become 1. A
    # file we did not write is one we cannot trust -- reject, do not coerce.
    if isinstance(dropped, bool) or isinstance(cadence_hours, bool):
        return None
    if not isinstance(dropped, int) or not isinstance(cadence_hours, int):
        return None
    if dropped < 0 or cadence_hours < 1:
        return None
    # Clamped, so a state file written by a future version with a higher cap
    # cannot make THIS version sparser than its own ceiling allows.
    return CadenceState(session_id, dropped, min(cadence_hours, MAX_CADENCE_HOURS))


def reset_cadence(path: Path) -> None:
    """Remove the cadence state if present. Fail-open: never raises.

    Args:
        path: Full path to the cadence state file.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as e:
        logger.debug("cron_cadence: failed to clear %s: %s", path, e)


def next_tick_decision(state: CadenceState | None, *, session_id: str) -> tuple[bool, CadenceState]:
    """Decide whether to deliver this tick, and return the state to persist.

    Pure arithmetic, deliberately free of hook input, marker files and project
    context, so Phase 4's truth table can be tested without any of them.

    A state belonging to a DIFFERENT session is discarded rather than trusted:
    the daemon outlives any one session, and inheriting a stale backoff would
    withdraw the safety net from a session that never earned it.

    Args:
        state: The persisted state, or None if there is none yet.
        session_id: The current session. REQUIRED rather than optional -- an
            earlier draft defaulted it to None and fell back to an empty
            string, which would have quietly bucketed every session with no id
            together and let one session's backoff suppress another's.

    Returns:
        ``(deliver, next_state)`` -- ``deliver`` False means DROP this tick.
    """
    if state is None or state.session_id != session_id:
        state = CadenceState(session_id, 0, _INITIAL_CADENCE_HOURS)

    if state.dropped_since_allowed + 1 < state.cadence_hours:
        return False, CadenceState(
            state.session_id,
            state.dropped_since_allowed + 1,
            state.cadence_hours,
        )
    return True, CadenceState(
        state.session_id,
        0,
        min(state.cadence_hours * 2, MAX_CADENCE_HOURS),
    )
