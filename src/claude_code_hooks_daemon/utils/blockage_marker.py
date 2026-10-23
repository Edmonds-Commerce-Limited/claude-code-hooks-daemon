"""Human-input blockage marker (Plan 00298).

The shared primitive behind the failsafe-cron blockage-cadence feature: a
small JSON file recording that a session's most recent Stop was allowed
because the agent is blocked ONLY on human input (a narrow, daemon-matched
``STOPPING BECAUSE:`` shape -- see ``auto_continue_stop._HUMAN_BLOCKED_PATTERNS``).

The awaiting-human state itself now lives in the session-modes registry, so
nothing writes this marker any more. What remains here is:

- ``read_marker``, which ``session_mode_registry.import_legacy_blockage_marker``
  uses to import a marker an older daemon left on disk;
- ``marker_is_valid`` and ``write_json_atomically``, the expiry check and the
  owner-only atomic JSON write that ``cron_pause`` and other record files
  share.

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
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.permissions import FileMode
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

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


def write_json_atomically(path: Path, payload: object) -> None:
    """Write ``payload`` as JSON to ``path`` owner-only, via rename. Raises OSError.

    The marker's own write, shared with the session-scoped cron pause
    (``cron_pause``), which records its expiring marker the same way. Raising
    rather than swallowing is the caller's choice to make: the hook path above
    fails open, while a CLI verb must be able to say nothing was recorded.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # uuid suffix, not pid: hook events dispatch on concurrent threads of
    # the one daemon process (same rationale as goal_ledger._save).
    tmp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FileMode.PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
    tmp_path.replace(path)


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
        log_and_continue(
            logger,
            e,
            reason=f"an unreadable or corrupt marker {path} reads as no marker (None), so the cron tick is delivered rather than wrongly suppressed",
            level=logging.DEBUG,
        )
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
