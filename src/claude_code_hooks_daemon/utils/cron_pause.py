"""Session-scoped pause for a declared persistent cron (ledger 00422 N4).

``cron_stop_enforcer`` refuses a stop while a job declared under
``persistent_crons`` is missing from ``session_crons``, and it is right to. But
a session told to cancel such a job for now had no legal move: obeying failed
the enforcer, and satisfying the enforcer disobeyed the instruction. The only
knob was the config itself, which stops the job for every session on every
branch until someone puts it back.

A pause is the spelling for "cancelled for now" (00422 DECISIONS.md, decision
2). It is deliberately narrow:

- **Set only by the CLI** (``hooks-daemon cron-pause <job> --reason ...``),
  which names one declared job and requires a reason.
- **Scoped to one session.** Keyed by ``CLAUDE_CODE_SESSION_ID``; the next
  session has a new id, so the declaration re-asserts itself there.
- **Expires on its own** within ``PAUSE_TTL_SECONDS``, through the same
  validity rule as the "blocked only on human input" marker
  (``blockage_marker.marker_is_valid``): a missing, foreign, future-dated or
  expired entry is no pause.
- **Never silent.** The enforcers name the job, the reason and the expiry.

``persistent_crons`` stays the only permanent switch. Reading fails OPEN in the
enforcing direction -- an unreadable file is "no pauses", so the enforcer keeps
enforcing -- while writing raises, so the CLI can say a pause was not recorded.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.blockage_marker import (
    BlockageMarker,
    marker_is_valid,
    write_json_atomically,
)

logger = logging.getLogger(__name__)

#: Placed under ``ProjectContext.daemon_untracked_dir()``, beside the
#: human-input blockage marker.
CRON_PAUSES_FILENAME: Final[str] = "cron-pauses.json"

_SECONDS_PER_MINUTE: Final[int] = 60
_SECONDS_PER_HOUR: Final[int] = 60 * _SECONDS_PER_MINUTE
_PAUSE_TTL_HOURS: Final[int] = 24

#: How long a pause lasts. The owner's ruling caps it at 24 hours.
PAUSE_TTL_SECONDS: Final[float] = float(_PAUSE_TTL_HOURS * _SECONDS_PER_HOUR)

#: A Stop ALLOW that carries context costs the session a turn, so the pause note
#: speaks on the first qualifying stop and then every Nth -- the same interval
#: as ``teammate_reap_advisor``, for the same reason.
PAUSE_ADVISE_INTERVAL: Final[int] = 10

_KEY_PAUSES: Final[str] = "pauses"
_FIELD_JOB_ID: Final[str] = "job_id"
_FIELD_SESSION_ID: Final[str] = "session_id"
_FIELD_REASON: Final[str] = "reason"
_FIELD_RECORDED_AT: Final[str] = "recorded_at"


@dataclass(frozen=True)
class CronPause:
    """One declared job paused for one session."""

    job_id: str
    session_id: str
    reason: str
    recorded_at: float

    @property
    def expires_at(self) -> float:
        """When the pause stops applying, in epoch seconds."""
        return self.recorded_at + PAUSE_TTL_SECONDS

    def is_live(self, *, session_id: str, now: float) -> bool:
        """Whether this pause applies to ``session_id`` at ``now``.

        Delegates to the blockage marker's rule, so the two expiring markers
        cannot disagree about what "valid" means. An empty session id matches
        nothing: a pause recorded without a session is no pause.
        """
        if not session_id:
            return False
        marker = BlockageMarker(session_id=self.session_id, recorded_at=self.recorded_at)
        return marker_is_valid(marker, session_id, now, PAUSE_TTL_SECONDS)


def default_pauses_path() -> Path | None:
    """The project's pause file, or None when there is no project context.

    None means "no pauses" to every caller -- the enforcing direction.
    """
    if not ProjectContext.is_initialized():
        logger.debug("cron_pause: no project context, so no pauses")
        return None
    return ProjectContext.daemon_untracked_dir() / CRON_PAUSES_FILENAME


def _parse_entry(entry: object) -> CronPause | None:
    if not isinstance(entry, dict):
        return None
    job_id = entry.get(_FIELD_JOB_ID)
    session_id = entry.get(_FIELD_SESSION_ID)
    reason = entry.get(_FIELD_REASON)
    recorded_at = entry.get(_FIELD_RECORDED_AT)
    if not isinstance(job_id, str) or not isinstance(session_id, str):
        return None
    if not isinstance(reason, str):
        return None
    if isinstance(recorded_at, bool) or not isinstance(recorded_at, (int, float)):
        return None
    return CronPause(
        job_id=job_id, session_id=session_id, reason=reason, recorded_at=float(recorded_at)
    )


def read_pauses(path: Path) -> list[CronPause]:
    """Every well-formed pause in ``path``; ``[]`` on a missing or corrupt file.

    A malformed entry is skipped rather than failing the whole read, so one bad
    entry cannot hide another session's genuine pause.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("cron_pause: unreadable %s: %s", path, exc)
        return []
    entries = raw.get(_KEY_PAUSES) if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    return [pause for pause in map(_parse_entry, entries) if pause is not None]


def _write_pauses(path: Path, pauses: list[CronPause]) -> None:
    payload = {
        _KEY_PAUSES: [
            {
                _FIELD_JOB_ID: pause.job_id,
                _FIELD_SESSION_ID: pause.session_id,
                _FIELD_REASON: pause.reason,
                _FIELD_RECORDED_AT: pause.recorded_at,
            }
            for pause in pauses
        ]
    }
    write_json_atomically(path, payload)


def _unexpired(pauses: list[CronPause], now: float) -> list[CronPause]:
    return [pause for pause in pauses if pause.is_live(session_id=pause.session_id, now=now)]


def record_pause(path: Path, pause: CronPause, *, now: float) -> None:
    """Add ``pause``, replacing any earlier pause of the same job in the same session.

    Expired entries of every session are pruned on the way, so the file never
    grows past the pauses that could still apply.

    Raises:
        OSError: The pause was not recorded.
    """
    kept = [
        existing
        for existing in _unexpired(read_pauses(path), now)
        if (existing.session_id, existing.job_id) != (pause.session_id, pause.job_id)
    ]
    kept.append(pause)
    _write_pauses(path, kept)


def remove_pause(path: Path, *, job_id: str, session_id: str, now: float) -> CronPause | None:
    """Remove this session's pause of ``job_id``; return it, or None if none was live.

    Raises:
        OSError: A live pause existed but the file could not be rewritten.
    """
    pauses = _unexpired(read_pauses(path), now)
    removed = next(
        (p for p in pauses if p.job_id == job_id and p.is_live(session_id=session_id, now=now)),
        None,
    )
    if removed is None:
        return None
    _write_pauses(path, [pause for pause in pauses if pause is not removed])
    return removed


def live_pauses(pauses: list[CronPause], *, session_id: str, now: float) -> dict[str, CronPause]:
    """The pauses that apply to ``session_id`` at ``now``, keyed by job id."""
    return {
        pause.job_id: pause for pause in pauses if pause.is_live(session_id=session_id, now=now)
    }


def load_live_pauses(path: Path | None, *, session_id: str, now: float) -> dict[str, CronPause]:
    """``live_pauses`` read from ``path``; empty for no path or no session."""
    if path is None or not session_id:
        return {}
    return live_pauses(read_pauses(path), session_id=session_id, now=now)


def format_expiry(pause: CronPause, *, now: float) -> str:
    """``2026-09-25 10:00 UTC (in 23h 59m)`` -- absolute AND relative."""
    stamp = datetime.fromtimestamp(pause.expires_at, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    remaining = max(0, int(pause.expires_at - now))
    hours, rest = divmod(remaining, _SECONDS_PER_HOUR)
    return f"{stamp} (in {hours}h {rest // _SECONDS_PER_MINUTE}m)"


def render_paused_note(pauses: list[CronPause], *, now: float) -> str:
    """Name every paused job, its reason and its expiry, and how to undo it.

    Args:
        pauses: The live pauses for the missing declared jobs. Non-empty.
        now: The current wall-clock time, for the relative expiry.
    """
    lines = [
        "⏸️ DECLARED CRON PAUSED FOR THIS SESSION — accepted as missing until the pause "
        "expires or is resumed:",
    ]
    for pause in pauses:
        lines.append(f"  • {pause.job_id} — reason: {pause.reason}")
        lines.append(f"    expires: {format_expiry(pause, now=now)}")
        lines.append(f"    resume now: hooks-daemon cron-resume {pause.job_id}")
    lines.append(
        "The declaration in `persistent_crons` is untouched, so the next session is asked "
        "to create the job again; editing that config is the only permanent switch."
    )
    return "\n".join(lines)
