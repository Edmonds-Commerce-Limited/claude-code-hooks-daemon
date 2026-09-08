"""The per-session automatic-model-downgrade signal: one file, two consumers.

Claude Code records its own safety-classifier model substitutions in the
session transcript. The `model_downgrade_recorder` PostToolUse handler copies
that record here, as one small JSON file per session, and two consumers read
it — both of which previously had to GUESS whether a family change was the
machine's doing:

- the `downgrade_indicator` status line, which used to infer it from a model
  high-water mark plus a marker the ccy supervisor wrote when it thought it had
  seen the human type `/model`;
- the ccy supervisor's model auto-restore, which used to infer it the same way
  and, on an allowance-exhausted account, typed `/model fable` at a human who
  had just picked Opus (Plan 00328's REPRODUCTION.md).

Path and field names live here so those two cannot drift apart. The supervisor
is a standalone script that cannot import this package, so it carries its own
reader (`load_model_downgrade_signal` in `.claude/ccy/claude-supervise.py`);
that duplication is inherent to the process boundary, and the two are pinned to
each other by `tests/unit/supervise/test_attributed_downgrade.py`.

The file deliberately carries no message content — only the two models, their
families, the refusal category and its scope. A refusal record sits next to
whatever provoked the refusal, and no consumer needs that.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: Written beside the context sidecar and the goal-intent signal, because the
#: supervisor already watches that directory — no new transport is introduced.
SIGNAL_SUBDIR: Final[str] = "context-sidecar"

#: Deliberately NOT ``.json``: the supervisor's sidecar reader globs that
#: extension and would otherwise take a downgrade signal for a context sidecar.
SIGNAL_SUFFIX: Final[str] = ".model-downgrade"

_SESSION_ID_FALLBACK: Final[str] = "unknown"
_UNSAFE_SESSION_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")

FIELD_TS: Final[str] = "ts"
FIELD_SESSION_ID: Final[str] = "session_id"
FIELD_ORIGINAL_MODEL: Final[str] = "original_model"
FIELD_FALLBACK_MODEL: Final[str] = "fallback_model"
FIELD_ORIGINAL_FAMILY: Final[str] = "original_family"
FIELD_FALLBACK_FAMILY: Final[str] = "fallback_family"
FIELD_CATEGORY: Final[str] = "category"
FIELD_SCOPE: Final[str] = "scope"
FIELD_RECORD_TS: Final[str] = "record_ts"

# Fields compared to decide whether a published signal still describes the
# current record. ``ts`` is excluded on purpose: it is the publish time, so
# including it would make every payload differ and defeat the rewrite guard.
_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    FIELD_ORIGINAL_MODEL,
    FIELD_FALLBACK_MODEL,
    FIELD_CATEGORY,
    FIELD_SCOPE,
    FIELD_RECORD_TS,
)


@dataclass(frozen=True, slots=True)
class DowngradeSignal:
    """One session's published automatic-downgrade record."""

    session_id: str
    original_model: str
    fallback_model: str
    original_family: str | None
    fallback_family: str | None
    category: str
    scope: str
    record_ts: str

    def attributes(self, *, from_family: str, to_family: str) -> bool:
        """Whether this record attributes a ``from_family`` → ``to_family`` drop.

        A family the recorder could not resolve is ``None`` and matches
        nothing: acting on it would aim a restore, or point a status-line
        badge, at a model nobody named.
        """
        return self.original_family == from_family and self.fallback_family == to_family

    def to_payload(self, *, now: float) -> dict[str, Any]:
        """Render the on-disk JSON payload, stamped with the publish time."""
        return {
            FIELD_TS: now,
            FIELD_SESSION_ID: self.session_id,
            FIELD_ORIGINAL_MODEL: self.original_model,
            FIELD_FALLBACK_MODEL: self.fallback_model,
            FIELD_ORIGINAL_FAMILY: self.original_family,
            FIELD_FALLBACK_FAMILY: self.fallback_family,
            FIELD_CATEGORY: self.category,
            FIELD_SCOPE: self.scope,
            FIELD_RECORD_TS: self.record_ts,
        }


def _session_stem(session_id: str) -> str:
    """A filesystem-safe stem for ``session_id``.

    The id arrives in a hook payload, so it is untrusted: separators and
    traversal dots are collapsed rather than allowed to steer the write out of
    the signal directory.
    """
    stem = _UNSAFE_SESSION_CHARS.sub("_", session_id.strip())
    return stem or _SESSION_ID_FALLBACK


def signal_path(daemon_untracked_dir: Path, session_id: str) -> Path:
    """The signal file path for ``session_id``."""
    return daemon_untracked_dir / SIGNAL_SUBDIR / f"{_session_stem(session_id)}{SIGNAL_SUFFIX}"


def _parse(payload: object) -> DowngradeSignal | None:
    """Build a signal from a parsed payload, or ``None`` if it is not one."""
    if not isinstance(payload, dict):
        return None
    session_id = payload.get(FIELD_SESSION_ID)
    if not isinstance(session_id, str) or not session_id:
        return None

    def _family(key: str) -> str | None:
        value = payload.get(key)
        return value if isinstance(value, str) and value else None

    def _text(key: str) -> str:
        value = payload.get(key)
        return value if isinstance(value, str) else ""

    return DowngradeSignal(
        session_id=session_id,
        original_model=_text(FIELD_ORIGINAL_MODEL),
        fallback_model=_text(FIELD_FALLBACK_MODEL),
        original_family=_family(FIELD_ORIGINAL_FAMILY),
        fallback_family=_family(FIELD_FALLBACK_FAMILY),
        category=_text(FIELD_CATEGORY),
        scope=_text(FIELD_SCOPE),
        record_ts=_text(FIELD_RECORD_TS),
    )


def read_downgrade_signal(daemon_untracked_dir: Path, session_id: str) -> DowngradeSignal | None:
    """Return the published signal for ``session_id``, or ``None``.

    Never raises. Both consumers are on hot paths — a status-line render about
    once a second, and a supervisor tick — so a missing, unreadable or corrupt
    signal is "no attribution", never an exception. Not time-windowed either:
    the record's own ``scope`` is ``session``, so it stays true until the
    session ends, and the supervisor's reaper removes the file afterwards.
    """
    path = signal_path(daemon_untracked_dir, session_id)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        logger.debug("model_downgrade_signal: malformed signal at %s", path)
        return None
    found = _parse(payload)
    if found is None or found.session_id != session_id:
        # The payload names the session too, so a file that landed under this
        # stem while naming a different session is not this session's signal.
        return None
    return found


def _describes_the_same_record(path: Path, payload: dict[str, Any]) -> bool:
    """Whether the signal already on disk names the same downgrade record."""
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(existing, dict):
        return False
    return all(existing.get(field) == payload.get(field) for field in _IDENTITY_FIELDS)


def write_downgrade_signal(
    daemon_untracked_dir: Path, signal: DowngradeSignal, *, now: float
) -> Path | None:
    """Atomically publish ``signal``, unless the same record is already there.

    Returns the path when written, ``None`` when the write was skipped or
    failed. Skipping an unchanged record is not an optimisation: the producer
    runs on every PostToolUse, and rewriting would churn the file's mtime so
    nothing downstream could tell a fresh downgrade from a long-standing one.

    Publishing is best-effort — an unwritable untracked directory is logged and
    swallowed, because the record is still in the transcript and the next tool
    call retries. The write itself is atomic (tmp + ``Path.replace``), so a
    failure can never leave a half-written signal for a consumer to read.
    """
    path = signal_path(daemon_untracked_dir, signal.session_id)
    payload = signal.to_payload(now=now)
    if path.exists() and _describes_the_same_record(path, payload):
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = unique_temp_path(path)
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        logger.warning("model_downgrade_signal: could not write %s: %s", path, exc)
        return None
    return path
