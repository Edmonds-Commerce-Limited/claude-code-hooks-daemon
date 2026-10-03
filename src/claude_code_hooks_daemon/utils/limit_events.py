"""The daemon's record of usage-limit resumes and limit-killed agents (Plan 00470 Task 3.2).

Two things happen around a usage limit that no hook can answer in the moment:

* A ``Notification`` hook cannot inject context (Claude Code discards its
  ``systemMessage``; ``remote-docs/code.claude.com/docs/en/hooks.md``,
  "Notification"). When the limit resets and Claude Code continues the task
  (``quota_auto_resume_fired``), waits for Enter (``quota_auto_resume_stale``)
  or gives up (``quota_auto_resume_disabled``), the only thing the daemon can do
  there is write it down. ``quota_resume_recorder`` does, and
  ``limit_rebrief`` delivers the re-brief at the session's next prompt.
* A background or teammate agent killed by a session or weekly limit reports
  its death as a prompt-borne notification, not as a tool result, so the
  foreground detectors never see it. ``limit_rebrief`` records the agent here
  when that notification arrives, so the re-brief after the resume can name it.

An event is *delivered* once a re-brief has listed it; the re-brief is the only
reader that clears it. This file is the recorded half of what Task 3.3's durable
work queue will hold in full (worktree, brief, last sha per agent): it names
WHO died and WHEN, nothing about their assignments.

**History is bounded by count** (``MAX_EVENTS``, oldest dropped first) and
**writes fail open**, like ``stop_failure_records``: bookkeeping must never take
a hook down.
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
from claude_code_hooks_daemon.utils.stop_failure_records import epoch_seconds

logger = logging.getLogger(__name__)

#: Placed under ``ProjectContext.daemon_untracked_dir()``, beside the stop-failure records.
LIMIT_EVENTS_FILENAME: Final[str] = "limit-events.json"

#: The ``notification_type`` values announcing how a usage-limit wait ended,
#: spelled as the hooks reference spells them.
RESUME_KINDS: Final[frozenset[str]] = frozenset(
    {"quota_auto_resume_fired", "quota_auto_resume_stale", "quota_auto_resume_disabled"}
)

#: Not a notification type: the daemon's own label for a background or teammate agent
#: whose death by a usage limit arrived as a prompt-borne notification.
KIND_AGENT_KILLED: Final[str] = "agent_killed"

#: Newest events kept; older ones are dropped on write.
MAX_EVENTS: Final[int] = 50

#: A detail is a short human label for the agent, not the notification's body.
MAX_DETAIL_CHARS: Final[int] = 240

_KEY_EVENTS: Final[str] = "events"
_FIELD_SESSION_ID: Final[str] = "session_id"
_FIELD_KIND: Final[str] = "kind"
_FIELD_RECORDED_AT: Final[str] = "recorded_at"
_FIELD_DETAIL: Final[str] = "detail"
_FIELD_DELIVERED_AT: Final[str] = "delivered_at"

#: Hook events dispatch on concurrent threads of the one daemon process, and a
#: record is a read-modify-write of one file.
_WRITE_LOCK: Final[threading.Lock] = threading.Lock()


@dataclass(frozen=True)
class LimitEvent:
    """One usage-limit resume, or one agent a limit killed, and whether it was re-briefed."""

    session_id: str
    kind: str
    recorded_at: float
    detail: str = ""
    delivered_at: float | None = None


def default_events_path() -> Path | None:
    """The project's event file, or None when there is no project context."""
    if not ProjectContext.is_initialized():
        logger.debug("limit_events: no project context, so no events")
        return None
    return ProjectContext.daemon_untracked_dir() / LIMIT_EVENTS_FILENAME


def _parse_entry(entry: object) -> LimitEvent | None:
    if not isinstance(entry, dict):
        return None
    session_id = entry.get(_FIELD_SESSION_ID)
    kind = entry.get(_FIELD_KIND)
    recorded_at = epoch_seconds(entry.get(_FIELD_RECORDED_AT))
    detail = entry.get(_FIELD_DETAIL, "")
    raw_delivered = entry.get(_FIELD_DELIVERED_AT)
    delivered_at = epoch_seconds(raw_delivered)
    if not isinstance(session_id, str) or not isinstance(kind, str) or recorded_at is None:
        return None
    if not isinstance(detail, str):
        return None
    if raw_delivered is not None and delivered_at is None:
        return None
    return LimitEvent(
        session_id=session_id,
        kind=kind,
        recorded_at=recorded_at,
        detail=detail,
        delivered_at=delivered_at,
    )


def read_events(path: Path) -> list[LimitEvent]:
    """Every well-formed event in ``path``; ``[]`` on a missing or corrupt file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("limit_events: unreadable %s: %s", path, exc)
        return []
    entries = raw.get(_KEY_EVENTS) if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    return [event for event in map(_parse_entry, entries) if event is not None]


def _write(path: Path, events: list[LimitEvent]) -> bool:
    """Write ``events``; False (logged) when the file could not be written."""
    payload = {
        _KEY_EVENTS: [
            {
                _FIELD_SESSION_ID: event.session_id,
                _FIELD_KIND: event.kind,
                _FIELD_RECORDED_AT: event.recorded_at,
                _FIELD_DETAIL: event.detail,
                _FIELD_DELIVERED_AT: event.delivered_at,
            }
            for event in events
        ]
    }
    try:
        write_json_atomically(path, payload)
    except OSError as exc:
        logger.warning("limit_events: failed to write %s: %s", path, exc)
        return False
    return True


def record_event(path: Path, event: LimitEvent) -> bool:
    """Append ``event``, keeping only the newest ``MAX_EVENTS``. False when not written.

    An undelivered event already recorded for the same session, kind and detail
    is not recorded again: a notification delivered twice is one death, and
    the re-brief should name it once.
    """
    event = replace(event, detail=event.detail[:MAX_DETAIL_CHARS])
    with _WRITE_LOCK:
        existing = read_events(path)
        if any(
            e.delivered_at is None
            and (e.session_id, e.kind, e.detail) == (event.session_id, event.kind, event.detail)
            for e in existing
        ):
            return True
        return _write(path, [*existing, event][-MAX_EVENTS:])


def pending_events(path: Path, session_id: str) -> list[LimitEvent]:
    """This session's undelivered events, oldest first."""
    pending = [
        e for e in read_events(path) if e.session_id == session_id and e.delivered_at is None
    ]
    return sorted(pending, key=lambda e: e.recorded_at)


def mark_delivered(path: Path, session_id: str, *, now: float) -> bool:
    """Mark this session's undelivered events delivered at ``now``; write only on a change.

    Returns:
        False when a needed write failed; True when the file is current.
    """
    with _WRITE_LOCK:
        before = read_events(path)
        after = [
            (
                replace(e, delivered_at=now)
                if e.session_id == session_id and e.delivered_at is None
                else e
            )
            for e in before
        ]
        return after == before or _write(path, after)
