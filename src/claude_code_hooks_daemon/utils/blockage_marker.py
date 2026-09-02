"""Human-input blockage marker (Plan 00298).

The shared primitive behind the failsafe-cron blockage-cadence feature: a
small JSON file recording that a session's most recent Stop was allowed
because the agent is blocked ONLY on human input (a narrow, daemon-matched
``STOPPING BECAUSE:`` shape -- see ``auto_continue_stop._HUMAN_BLOCKED_PATTERNS``).

Two callers, one marker:

- ``auto_continue_stop.AutoContinueStopHandler`` writes it on a matching
  Branch 2 ALLOW.
- ``failsafe_cron_blockage_suppressor.FailsafeCronBlockageSuppressorHandler``
  reads it to short-circuit a delivered failsafe-cron tick before the model
  ever sees it, and any genuine (non-cron) user prompt clears it.

**Fail-open everywhere, deliberately minimal (owner ruling: "sounds complex
and brittle to me" -- build the minimal version).** One marker file, one
session-scoped validity check, no fallback chains. Every public function here
degrades to "no marker" / "no-op" on any I/O or parse failure rather than
raising -- an unreadable, corrupt, or unwritable marker must never prevent a
Stop or a cron tick from proceeding normally.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.permissions import FileMode

logger = logging.getLogger(__name__)

# Placed under ProjectContext.daemon_untracked_dir() by callers -- same
# directory convention as goal-ledger.json and stop-events.jsonl.
MARKER_FILENAME: Final[str] = "human-input-blockage-marker.json"

_FIELD_SESSION_ID: Final[str] = "session_id"
_FIELD_RECORDED_AT: Final[str] = "recorded_at"


@dataclass(frozen=True)
class BlockageMarker:
    """One recorded 'blocked only on human input' moment."""

    session_id: str
    recorded_at: float


def write_marker(path: Path, session_id: str, *, now: float | None = None) -> bool:
    """Atomically (over)write the marker. Fail-open: logs, never raises.

    Args:
        path: Full path to the marker file.
        session_id: The session this marker applies to.
        now: Injectable clock for tests; defaults to ``time.time()``.

    Returns:
        True if the marker was written, False if an OSError was swallowed
        (e.g. an unwritable parent directory) -- Plan 00314 field
        observability: callers that log an outcome (e.g. ``stop-events.jsonl``
        ``marker_written``) need this to tell "matched but not armed" apart
        from "matched and armed" after the fact.
    """
    payload = {
        _FIELD_SESSION_ID: session_id,
        _FIELD_RECORDED_AT: now if now is not None else time.time(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # uuid suffix, not pid: hook events dispatch on concurrent threads of
        # the one daemon process (same rationale as goal_ledger._save).
        tmp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FileMode.PRIVATE_FILE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload))
        tmp_path.replace(path)
        return True
    except OSError as e:
        logger.warning("blockage_marker: failed to write %s: %s", path, e)
        return False


def read_marker(path: Path) -> BlockageMarker | None:
    """Read the marker. Fail-open: missing/corrupt/malformed -> None.

    Args:
        path: Full path to the marker file.

    Returns:
        The parsed marker, or None if it does not exist or cannot be trusted.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("blockage_marker: unreadable %s: %s", path, e)
        return None
    if not isinstance(raw, dict):
        return None
    session_id = raw.get(_FIELD_SESSION_ID)
    recorded_at = raw.get(_FIELD_RECORDED_AT)
    if not isinstance(session_id, str) or isinstance(recorded_at, bool):
        return None
    if not isinstance(recorded_at, (int, float)):
        return None
    return BlockageMarker(session_id=session_id, recorded_at=float(recorded_at))


def clear_marker(path: Path) -> None:
    """Remove the marker if present. Fail-open: never raises.

    Args:
        path: Full path to the marker file.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as e:
        logger.debug("blockage_marker: failed to clear %s: %s", path, e)


def marker_is_valid(
    marker: BlockageMarker | None, session_id: str, now: float, expiry_seconds: float
) -> bool:
    """Whether ``marker`` currently suppresses cron ticks for ``session_id``.

    Fails open (returns False, i.e. "do not suppress") on a missing marker, a
    different session, an expired marker, or a marker whose timestamp is in
    the future (clock skew / corruption) -- suppression is only ever a
    positive assertion made under conditions that are all individually
    verified, never the default.

    Args:
        marker: The parsed marker, or None.
        session_id: The current session's id.
        now: The current wall-clock time (seconds).
        expiry_seconds: How long a marker stays valid without re-confirmation.

    Returns:
        True only when the marker is present, matches this session, and its
        age is within ``[0, expiry_seconds]``.
    """
    if marker is None:
        return False
    if marker.session_id != session_id:
        return False
    age = now - marker.recorded_at
    if age < 0:
        return False
    return age <= expiry_seconds
