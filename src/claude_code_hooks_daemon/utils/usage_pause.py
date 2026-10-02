"""The ``<session>.usage-paused`` record: daemon -> supervisor (Plan 00479 Task 4.5).

When a session crosses its usage ceiling the daemon PAUSES it (it does not end
it): every cron is replaced by one resume cron at the window reset. This record
tells the standalone ccy supervisor that the session is paused and until when,
so the supervisor can compact once and then stay quiet instead of nudging the
session awake with ``continue`` or ``/goal``.

Same shape as the other supervisor channels (``operator_signal``,
``model_downgrade_signal``, the ``compaction_signal`` handler): one small JSON
file per session in the shared ``context-sidecar`` directory, written
atomically. The READER is ``load_usage_pause`` in ``.claude/ccy/claude-supervise.py``;
that script is stdlib-only and cannot import this package, so field names and
the validity rule live here and are pinned to the supervisor's copies by
``tests/unit/supervise/test_usage_pause.py``.

Relation to ``cron_pause`` (ledger 00422 N4): a deliberately SEPARATE record.
``cron_pause`` is a CLI-set, 24-hour, one-file-for-all-sessions exemption that
the cron enforcers read inside the daemon. This one is written by the usage
gate, is per-session so the supervisor can glob it like every other signal, and
expires at the window reset (``resume_at``) rather than after a fixed TTL.
What they share is the validity discipline: a record is live only for its own
session, never future-dated, and never past its end -- here ``resume_at`` plus
:data:`PAUSE_GRACE_SECONDS`, so a record left behind by a gate that crashed
cannot hold a session silent for ever. Reads fail OPEN (an unreadable record is
"no pause", and the supervisor behaves as it always has); writes and clears
raise, so the gate can say a pause was not recorded.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: Beside the context sidecar and the other signals the supervisor watches.
SIGNAL_SUBDIR: Final[str] = "context-sidecar"

#: Deliberately NOT ``.json``: the supervisor's sidecar reader globs that
#: extension and would otherwise mistake this record for a context sidecar.
SIGNAL_SUFFIX: Final[str] = ".usage-paused"

_SESSION_ID_FALLBACK: Final[str] = "unknown"
_UNSAFE_SESSION_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")

FIELD_SESSION_ID: Final[str] = "session_id"
FIELD_PAUSED_AT: Final[str] = "paused_at"
FIELD_RESUME_AT: Final[str] = "resume_at"
FIELD_WINDOW: Final[str] = "window"
FIELD_USED_PERCENTAGE: Final[str] = "used_percentage"
FIELD_CEILING: Final[str] = "ceiling"
FIELD_REASON: Final[str] = "reason"

#: The closed set of usage windows a pause can be waiting on.
WINDOW_FIVE_HOUR: Final[str] = "five_hour"
WINDOW_SEVEN_DAY: Final[str] = "seven_day"
WINDOWS: Final[frozenset[str]] = frozenset({WINDOW_FIVE_HOUR, WINDOW_SEVEN_DAY})

#: How long past ``resume_at`` a record still counts. The resume cron fires at
#: ``resume_at`` and the gate then lifts (clears) the pause; the grace covers a
#: late tick, and its end is the backstop for a gate that never got to clear.
PAUSE_GRACE_SECONDS: Final[float] = 3600.0

#: The longest a record may pause a session: ``resume_at - paused_at``. The
#: longest real wait is the 7-day window plus the resume margin, so a record
#: asking for more is corrupt or hand-edited and reads as no pause rather than
#: silencing a session (and the supervisor) for years.
MAX_PAUSE_SPAN_SECONDS: Final[float] = 8 * 86400.0


@dataclass(frozen=True)
class UsagePause:
    """One session paused on a usage ceiling.

    ``paused_at`` and ``resume_at`` are epoch seconds. ``used_percentage`` and
    ``ceiling`` are the window's reading and the configured limit it crossed.
    ``reason`` is short human-readable text for logs and the status line.
    """

    session_id: str
    paused_at: float
    resume_at: float
    window: str
    used_percentage: float
    ceiling: float
    reason: str

    @property
    def expires_at(self) -> float:
        """When the record stops applying even if nothing cleared it."""
        return self.resume_at + PAUSE_GRACE_SECONDS

    def is_live(self, *, session_id: str, now: float) -> bool:
        """Whether this record pauses ``session_id`` at ``now``.

        False for an empty or different session, a record dated in the future
        (clock skew or corruption), or one past :attr:`expires_at`. Pausing is
        only ever a positive assertion made under conditions that are each
        verified, never the default.
        """
        if not session_id or session_id != self.session_id:
            return False
        return self.paused_at <= now <= self.expires_at


def _session_stem(session_id: str) -> str:
    """A filesystem-safe stem: separators and traversal dots cannot leave the directory."""
    stem = _UNSAFE_SESSION_CHARS.sub("_", session_id.strip())
    return stem or _SESSION_ID_FALLBACK


def pause_path(daemon_untracked_dir: Path, session_id: str) -> Path:
    """The record's path for ``session_id``."""
    return daemon_untracked_dir / SIGNAL_SUBDIR / f"{_session_stem(session_id)}{SIGNAL_SUFFIX}"


def _as_number(value: object) -> float | None:
    """``value`` as a float when it is a finite int or float (never a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _validation_error(pause: UsagePause) -> str | None:
    """Why the supervisor's reader would reject ``pause``, or None when it is sound."""
    if not pause.session_id.strip():
        return "a usage pause needs a session id"
    if pause.window not in WINDOWS:
        return f"unknown usage window {pause.window!r}; expected one of {sorted(WINDOWS)}"
    for name, value in (
        (FIELD_PAUSED_AT, pause.paused_at),
        (FIELD_RESUME_AT, pause.resume_at),
        (FIELD_USED_PERCENTAGE, pause.used_percentage),
        (FIELD_CEILING, pause.ceiling),
    ):
        if _as_number(value) is None:
            return f"{name} must be a finite number, got {value!r}"
    if pause.resume_at <= pause.paused_at:
        return "resume_at must be after paused_at"
    if pause.resume_at - pause.paused_at > MAX_PAUSE_SPAN_SECONDS:
        return f"resume_at must be within {MAX_PAUSE_SPAN_SECONDS:g} s of paused_at"
    if not pause.reason.strip():
        return "a usage pause needs a reason"
    return None


def _validate(pause: UsagePause) -> None:
    """Refuse a record the supervisor's reader would reject. Raises ``ValueError``."""
    error = _validation_error(pause)
    if error is not None:
        raise ValueError(error)


def write_usage_pause(daemon_untracked_dir: Path, pause: UsagePause) -> Path:
    """Atomically write ``pause``, replacing any earlier record for the session.

    Raises:
        ValueError: the record is one the supervisor would reject.
        OSError: the write failed (propagates, so the caller can report that
            no pause was recorded).
    """
    _validate(pause)
    final_path = pause_path(daemon_untracked_dir, pause.session_id)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        FIELD_SESSION_ID: pause.session_id,
        FIELD_PAUSED_AT: pause.paused_at,
        FIELD_RESUME_AT: pause.resume_at,
        FIELD_WINDOW: pause.window,
        FIELD_USED_PERCENTAGE: pause.used_percentage,
        FIELD_CEILING: pause.ceiling,
        FIELD_REASON: pause.reason,
    }
    tmp_path = unique_temp_path(final_path)
    try:
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(final_path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise
    return final_path


def _parse(data: object) -> UsagePause | None:
    """A validated record from untyped JSON, or None."""
    if not isinstance(data, dict):
        return None
    session_id = data.get(FIELD_SESSION_ID)
    window = data.get(FIELD_WINDOW)
    reason = data.get(FIELD_REASON)
    paused_at = _as_number(data.get(FIELD_PAUSED_AT))
    resume_at = _as_number(data.get(FIELD_RESUME_AT))
    used = _as_number(data.get(FIELD_USED_PERCENTAGE))
    ceiling = _as_number(data.get(FIELD_CEILING))
    if not (isinstance(session_id, str) and isinstance(window, str) and isinstance(reason, str)):
        return None
    if paused_at is None or resume_at is None or used is None or ceiling is None:
        return None
    pause = UsagePause(session_id, paused_at, resume_at, window, used, ceiling, reason)
    return pause if _validation_error(pause) is None else None


def read_usage_pause(
    daemon_untracked_dir: Path, session_id: str, *, now: float
) -> UsagePause | None:
    """The live pause for ``session_id`` at ``now``, or None.

    Fails open: a missing, unreadable, malformed, foreign-session, future-dated
    or expired record is no pause. A present-but-unreadable record is logged,
    since that is a fault someone should hear about; a missing one is normal.
    """
    if not session_id:
        return None
    records = _read_records(pause_path(daemon_untracked_dir, session_id))
    return next((p for p in records if p.is_live(session_id=session_id, now=now)), None)


def _read_records(path: Path) -> list[UsagePause]:
    """The record in ``path`` as a one-item list; ``[]`` when missing or unusable.

    A missing file is normal and silent. One that is present but unreadable or
    malformed is logged, since that is a fault someone should hear about.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        logger.warning("usage_pause: unreadable record %s: %s", path, exc)
        return []
    pause = _parse(raw)
    if pause is None:
        logger.warning("usage_pause: malformed record %s ignored", path)
        return []
    return [pause]


#: The owner's override marker (``hooks-daemon usage-pause clear``): while it is valid no gate
#: starts a pause for the session. Its own suffix, so the supervisor's reader of
#: :data:`SIGNAL_SUFFIX` files never sees it.
OVERRIDE_SUFFIX: Final[str] = ".usage-override"
FIELD_UNTIL: Final[str] = "until"


def override_path(daemon_untracked_dir: Path, session_id: str) -> Path:
    """The override marker's path for ``session_id``."""
    return daemon_untracked_dir / SIGNAL_SUBDIR / f"{_session_stem(session_id)}{OVERRIDE_SUFFIX}"


def write_usage_override(
    daemon_untracked_dir: Path, session_id: str, *, until: float, now: float
) -> float:
    """Record that the owner overrode the pause for ``session_id`` until ``until``.

    ``until`` is capped at ``now + MAX_PAUSE_SPAN_SECONDS``, like a pause.

    Returns:
        The end time actually recorded.

    Raises:
        ValueError: no session id, a non-finite time, or ``until`` not after ``now``.
        OSError: the write failed.
    """
    if not session_id.strip():
        raise ValueError("a usage override needs a session id")
    if _as_number(until) is None or _as_number(now) is None or until <= now:
        raise ValueError(f"an override must end after now ({now!r}), got {until!r}")
    capped = min(until, now + MAX_PAUSE_SPAN_SECONDS)
    final_path = override_path(daemon_untracked_dir, session_id)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {FIELD_SESSION_ID: session_id, FIELD_UNTIL: capped}
    tmp_path = unique_temp_path(final_path)
    try:
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(final_path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise
    return capped


def usage_override_active(daemon_untracked_dir: Path, session_id: str, *, now: float) -> bool:
    """Whether the owner's override covers ``session_id`` at ``now``.

    Fails toward NOT pausing: a marker that exists but cannot be read counts as an
    override (a warning says so), because the alternative is pausing a session the
    owner just released. A malformed marker is ignored.
    """
    if not session_id:
        return False
    path = override_path(daemon_untracked_dir, session_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("usage_pause: unreadable override %s, treating it as active: %s", path, exc)
        return True
    except ValueError as exc:
        logger.warning("usage_pause: malformed override %s ignored: %s", path, exc)
        return False
    if not isinstance(raw, dict) or raw.get(FIELD_SESSION_ID) != session_id:
        return False
    until = _as_number(raw.get(FIELD_UNTIL))
    return until is not None and now < until


def clear_usage_pause(daemon_untracked_dir: Path, session_id: str) -> bool:
    """Remove the record for ``session_id``; True if one was removed.

    Raises:
        OSError: a record existed but could not be removed.
    """
    path = pause_path(daemon_untracked_dir, session_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True
