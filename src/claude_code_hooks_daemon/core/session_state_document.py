"""The ``session-state`` document: one session's state, read from the daemon's records (Plan 00601).

Read-only and fail-open: a record that is missing or unreadable is ``null`` in
the document, never an error, and nothing here writes. The document is the CLI
contract described by the shipped ``session-state`` schema
(:mod:`claude_code_hooks_daemon.core.state_schemas`); the files it is built from
are internal and may change layout without a schema change.

**Why ``limit_reset`` is a join, not a record** (FINDINGS.md, Plan 00601 Task 1.1):
a ``rate_limit`` StopFailure is stored with no reset time, and usage is
account-wide, so the reset time lives only in the usage snapshot. An unresolved
``rate_limit`` stop is joined to the snapshot window that is at its limit.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.core.state_schemas import KEY_SCHEMA_VERSION, SCHEMA_VERSION
from claude_code_hooks_daemon.core.usage_snapshot import (
    FIVE_HOUR_KEY,
    SEVEN_DAY_KEY,
    UsageSnapshot,
    UsageTracker,
    UsageWindow,
    usage_state_file,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.stop_failure_records import (
    STOP_FAILURE_RECORDS_FILENAME,
    StopFailureRecord,
    read_records,
)
from claude_code_hooks_daemon.utils.usage_pause import read_usage_pause

logger = logging.getLogger(__name__)

#: Written by ``auto_continue_stop``; one JSON line per Stop, bounded to 2 MiB.
STOP_EVENTS_FILENAME: Final[str] = "stop-events.jsonl"

#: Only the end of the stop-events log is read: the newest line of a session is near it.
_STOP_EVENTS_TAIL_BYTES: Final[int] = 256 * 1024

#: A usage window counts as the one a rate_limit stop waits on at or above this share.
LIMIT_JOIN_MIN_PERCENT: Final[float] = 95.0

_RATE_LIMIT_ERROR: Final[str] = "rate_limit"

KEY_OBSERVED_AT: Final[str] = "observed_at"
KEY_CHANGED: Final[str] = "changed"
KEY_STATE: Final[str] = "state"

#: Document fields that are not state: they change on every build.
_NOT_STATE: Final[frozenset[str]] = frozenset({KEY_SCHEMA_VERSION, KEY_OBSERVED_AT})

_Document = dict[str, Any]


def _read_tail(path: Path) -> str:
    """The last ``_STOP_EVENTS_TAIL_BYTES`` of ``path``; empty when absent or unreadable."""
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - _STOP_EVENTS_TAIL_BYTES))
            return handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable {path} reads as no recorded stop (empty text), so last_turn_edge is null rather than failing the state read",
            level=logging.DEBUG,
        )
        return ""


def _stop_time_of(line: str, session_id: str) -> float | None:
    """The epoch time of one stop-events line, or None when it is another session's.

    Raises ValueError, KeyError, TypeError or AttributeError for a torn line;
    the caller skips it.
    """
    entry = json.loads(line)
    if entry.get("session_id") != session_id:
        return None
    return datetime.fromisoformat(entry["timestamp"]).timestamp()


def _last_stop_at(untracked_dir: Path, session_id: str) -> float | None:
    """Epoch seconds of this session's newest recorded Stop, or None."""
    tail = _read_tail(untracked_dir / STOP_EVENTS_FILENAME)
    for line in reversed(tail.splitlines()):
        try:
            at = _stop_time_of(line, session_id)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a torn stop-events line is not a stop; the scan goes on to the previous line",
                level=logging.DEBUG,
            )
            continue
        if at is not None:
            return at
    return None


def _newest_failure(untracked_dir: Path, session_id: str) -> StopFailureRecord | None:
    records = [
        r
        for r in read_records(untracked_dir / STOP_FAILURE_RECORDS_FILENAME)
        if r.session_id == session_id
    ]
    return max(records, key=lambda r: r.recorded_at, default=None)


def _last_turn_edge(
    untracked_dir: Path, session_id: str, failure: StopFailureRecord | None
) -> dict[str, Any] | None:
    """The newest of: a Stop, a StopFailure, and the prompt that resolved a failure."""
    edges: list[dict[str, Any]] = []
    stop_at = _last_stop_at(untracked_dir, session_id)
    if stop_at is not None:
        edges.append({"kind": "stop", "at": stop_at})
    if failure is not None:
        edges.append(
            {
                "kind": "stop_failure",
                "at": failure.recorded_at,
                "error": failure.error,
                "resolved_at": failure.resolved_at,
            }
        )
        if failure.resolved_at is not None:
            edges.append({"kind": "start", "at": failure.resolved_at})
    return max(edges, key=lambda edge: edge["at"], default=None)


def _window_json(window: UsageWindow | None) -> dict[str, float | int] | None:
    if window is None:
        return None
    return {
        "used_percentage": window.used_percentage,
        "resets_at": window.resets_at,
        "observed_at": window.observed_at,
    }


def _usage(snapshot: UsageSnapshot | None) -> dict[str, Any]:
    five = snapshot.five_hour if snapshot else None
    seven = snapshot.seven_day if snapshot else None
    seen = [w.observed_at for w in (five, seven) if w is not None]
    return {
        FIVE_HOUR_KEY: _window_json(five),
        SEVEN_DAY_KEY: _window_json(seven),
        KEY_OBSERVED_AT: max(seen, default=None),
    }


def _limit_reset(
    failure: StopFailureRecord | None, snapshot: UsageSnapshot | None
) -> dict[str, Any] | None:
    """The reset of the window an unresolved rate_limit stop waits on, else None.

    The stop does not say which window it hit, so the windows at their limit are
    the candidates; when both are, the session waits for the later reset. No live
    snapshot, or no window near its limit, is None: the reset time is not guessed.
    """
    if failure is None or failure.resolved_at is not None or failure.error != _RATE_LIMIT_ERROR:
        return None
    if snapshot is None:
        return None
    full = [
        (name, window)
        for name, window in (
            (FIVE_HOUR_KEY, snapshot.five_hour),
            (SEVEN_DAY_KEY, snapshot.seven_day),
        )
        if window is not None and window.used_percentage >= LIMIT_JOIN_MIN_PERCENT
    ]
    if not full:
        return None
    name, window = max(full, key=lambda pair: pair[1].resets_at)
    return {"window": name, "resets_at": window.resets_at}


def build_session_state(
    session_id: str, *, modes: list[dict[str, Any]], untracked_dir: Path, now: float
) -> _Document:
    """The session-state document for ``session_id`` at ``now``.

    Args:
        session_id: The session asked about; an unknown one yields nulls.
        modes: The session's live modes, in the ``mode-history`` entry shape.
        untracked_dir: The daemon's untracked directory the records live in.
        now: Epoch seconds; expiry of usage windows and the pause is judged against it.
    """
    failure = _newest_failure(untracked_dir, session_id)
    snapshot = UsageTracker().latest(now=now, state_file=usage_state_file(untracked_dir))
    pause = read_usage_pause(untracked_dir, session_id, now=now)
    return {
        KEY_SCHEMA_VERSION: SCHEMA_VERSION,
        "session_id": session_id,
        KEY_OBSERVED_AT: now,
        "modes": modes,
        "last_turn_edge": _last_turn_edge(untracked_dir, session_id, failure),
        "usage": _usage(snapshot),
        "limit_reset": _limit_reset(failure, snapshot),
        "usage_pause": (
            None
            if pause is None
            else {
                "paused_at": pause.paused_at,
                "resume_at": pause.resume_at,
                "window": pause.window,
                "used_percentage": pause.used_percentage,
                "ceiling": pause.ceiling,
                "reason": pause.reason,
            }
        ),
    }


def _stable(value: object) -> object:
    """``value`` without any ``observed_at`` key: a usage heartbeat is not a change."""
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k != KEY_OBSERVED_AT}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def changed_fields(before: _Document, after: _Document) -> list[str]:
    """Sorted names of the state fields that differ, ignoring build and heartbeat times."""
    names = (set(before) | set(after)) - _NOT_STATE
    return sorted(name for name in names if _stable(before.get(name)) != _stable(after.get(name)))


def watch_lines(
    fetch: Callable[[], _Document | None],
    *,
    interval: float,
    sleep: Callable[[float], None],
    max_polls: int | None = None,
) -> Iterator[_Document]:
    """One ``session-state-watch`` line per change of the state ``fetch`` returns.

    The first poll always yields, naming every field; later polls yield only when
    a field changed. ``max_polls`` bounds the loop (None runs until the caller stops);
    a ``fetch`` that returns None ends the stream.
    """
    previous: _Document | None = None
    polls = 0
    while max_polls is None or polls < max_polls:
        if polls:
            sleep(interval)
        polls += 1
        state = fetch()
        if state is None:
            return
        changed = (
            sorted(set(state) - _NOT_STATE) if previous is None else changed_fields(previous, state)
        )
        if changed:
            yield {KEY_SCHEMA_VERSION: SCHEMA_VERSION, KEY_CHANGED: changed, KEY_STATE: state}
        previous = state
