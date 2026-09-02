"""Pure helpers for the downgrade-indicator per-session high-water state (Plan 00278).

Anthropic's safety classifier can silently substitute the session model
(`fable` -> `opus`, or any higher-ranked family down to a lower one) with no
on-screen sign that the session is now degraded. This module tracks, per
session, the HIGHEST-ranked model family seen so far (the "high-water mark")
so a later render on a LOWER-ranked family can be recognised as an active
downgrade rather than a fresh session simply starting on a modest model.

Split out as pure functions for the same reason `thread_registry.py` was: the
family-resolution and high-water read/write/evaluate logic is unit-testable
without a Handler or a live daemon.

State is one small JSON file per session under
``{daemon_untracked_dir}/downgrade-indicator/{session_id}.json`` — keyed by
session id so a genuinely-fresh session that starts on a high-ranked model
(e.g. opus) is never mislabelled a downgrade by another session's history.
Writes are atomic (``tmp`` + ``Path.replace()``, mirroring `thread_registry.py`)
so a concurrent reader — the daemon may serve several sessions at once
(CLAUDE.md "Parallel sessions share one daemon") — never observes a
half-written file.

Reads are routed through the shared `MtimeCachedFile` gate (`mtime_cache.py`)
rather than reading the file directly. Unlike the heartbeat-write pattern in
`thread_registry.py`, this module only rewrites the file on a genuine NEW
high-water render (rare); on every other render — including every render of a
sustained downgrade — the file's mtime is unchanged, so the mtime gate turns
what would otherwise be a read-and-parse on every status-line render (roughly
once a second, per this package's `CLAUDE.md`) into a single ``stat()``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.handlers.status_line.mtime_cache import MtimeCachedFile
from claude_code_hooks_daemon.handlers.status_line.thread_registry import safe_session_stem

logger = logging.getLogger(__name__)

# Subdirectory (under the daemon untracked dir) holding per-session high-water
# state files. Distinct from thread-registry/ and context-sidecar/ so the
# sensors sharing the untracked dir never collide.
_STATE_SUBDIR: Final[str] = "downgrade-indicator"

# Canonical model-family rank ladder (higher = more capable). `mythos` is a
# known alias that canonicalises to the `fable` family and rank.
_FAMILY_SUBSTRINGS: Final[tuple[tuple[str, str, int], ...]] = (
    ("haiku", "haiku", 0),
    ("sonnet", "sonnet", 1),
    ("opus", "opus", 2),
    ("fable", "fable", 3),
    ("mythos", "fable", 3),
)

# JSON keys for the per-session state file.
_STATE_KEY_FAMILY: Final[str] = "high_water_family"
_STATE_KEY_RANK: Final[str] = "high_water_rank"


def resolve_model_family(model_id: str) -> tuple[str, int] | None:
    """Resolve a model id to its canonical family name and rank.

    Args:
        model_id: Raw model id string (e.g. ``"claude-opus-4-6"``), matched by
            case-insensitive substring.

    Returns:
        ``(canonical_family, rank)``, or ``None`` if the id matches no known
        family. An unrecognised model id is "no opinion" — never treated as a
        downgrade, and never allowed to corrupt the stored high-water.
    """
    if not model_id:
        return None
    lowered = model_id.lower()
    for substring, family, rank in _FAMILY_SUBSTRINGS:
        if substring in lowered:
            return family, rank
    return None


def state_dir(daemon_untracked_dir: Path) -> Path:
    """Return the directory holding per-session high-water state files."""
    return daemon_untracked_dir / _STATE_SUBDIR


# Plan 00316 Task 1.3: the ccy supervisor's manual-model-change marker
# directory — written by `.claude/ccy/claude-supervise.py`'s
# `write_manual_model_marker` (host tier, on every user-typed `/model
# <family>`) under the SAME daemon untracked root this module's own state
# lives under. Kept as a plain read here (not cached via `MtimeCachedFile`)
# because a marker is consulted once per render and is deliberately
# short-lived (see `_MANUAL_MARKER_WINDOW_SECONDS`).
_MANUAL_MARKER_SUBDIR: Final[str] = "manual-model-changes"
# Mirrors the supervisor's `_MANUAL_MODEL_WINDOW_SECONDS` — kept as an
# independent constant (the two are separate deployables) rather than a
# shared import, so this stays generous enough to outlast the render/tick
# latency between the human's Enter and the daemon's next status-line render.
_MANUAL_MARKER_WINDOW_SECONDS: Final[float] = 120.0
_MARKER_KEY_FAMILY: Final[str] = "family"
_MARKER_KEY_TS: Final[str] = "ts"


def manual_model_change_dir(daemon_untracked_dir: Path) -> Path:
    """Return the directory holding per-session manual-model-change markers."""
    return daemon_untracked_dir / _MANUAL_MARKER_SUBDIR


def _parse_manual_marker(text: str) -> tuple[str, float] | None:
    """Parse one marker file's text into ``(family, ts)``, or ``None``.

    Never raises: matches this module's fail-silent render-path contract.
    """
    try:
        data: Any = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    family = data.get(_MARKER_KEY_FAMILY)
    ts = data.get(_MARKER_KEY_TS)
    if not isinstance(family, str):
        return None
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    return family, float(ts)


# Routed through the shared mtime gate (like `_STATE_CACHE` above) rather
# than a direct read on every render — the supervisor rewrites a session's
# marker at most once per typed `/model` command, far rarer than the render
# rate.
_MANUAL_MARKER_CACHE: MtimeCachedFile[tuple[str, float] | None] = MtimeCachedFile(
    _parse_manual_marker, None
)


def is_manual_model_change(
    dir_path: Path, session_id: str, current_family: str, *, now: float
) -> bool:
    """True when a recent human-typed `/model <current_family>` marker exists.

    Fail-silent: a missing, unreadable, or malformed marker file, or one for
    a DIFFERENT family, or one outside the validity window, all read as "not
    manual" — this must never raise on the render path.
    """
    path = dir_path / f"{safe_session_stem(session_id)}.json"
    parsed = _MANUAL_MARKER_CACHE.read(path)
    if parsed is None:
        return False
    family, ts = parsed
    if family != current_family:
        return False
    return (now - ts) <= _MANUAL_MARKER_WINDOW_SECONDS


# JSON keys for the episode tallies added on top of the high-water fields
# (Plan 00278 continuation). Absent from files written before this feature —
# `_parse_state` defaults them, so a legacy file reads back as zero counts.
_STATE_KEY_DOWNGRADE_COUNT: Final[str] = "downgrade_count"
_STATE_KEY_RECOVERY_COUNT: Final[str] = "recovery_count"
_STATE_KEY_ACTIVE: Final[str] = "downgraded"


@dataclass(frozen=True)
class DowngradeRecord:
    """One session's persisted downgrade state.

    ``family``/``rank`` are the high-water mark; ``downgrade_count`` and
    ``recovery_count`` tally EPISODES (transitions, not renders); ``active``
    is whether a downgrade episode is currently open, so the next render can
    tell an ongoing downgrade (no new count) from a fresh one.
    """

    family: str
    rank: int
    downgrade_count: int = 0
    recovery_count: int = 0
    active: bool = False


def _parse_state(text: str) -> DowngradeRecord | None:
    """Parse one state file's text into a ``DowngradeRecord``, or ``None``.

    Never raises: any malformed content is reported as "no prior state",
    matching this package's fail-silent render-path contract. The count and
    ``active`` fields default when absent, so a file written before this
    feature (family/rank only) parses cleanly as zero counts.
    """
    try:
        data: Any = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    family = data.get(_STATE_KEY_FAMILY)
    rank = data.get(_STATE_KEY_RANK)
    # ``bool`` is an ``int`` subclass; exclude it so a stray ``true`` rank is
    # rejected rather than silently read as 1.
    if not isinstance(family, str) or not isinstance(rank, int) or isinstance(rank, bool):
        return None
    return DowngradeRecord(
        family=family,
        rank=rank,
        downgrade_count=_coerce_count(data.get(_STATE_KEY_DOWNGRADE_COUNT)),
        recovery_count=_coerce_count(data.get(_STATE_KEY_RECOVERY_COUNT)),
        active=bool(data.get(_STATE_KEY_ACTIVE, False)),
    )


def _coerce_count(value: Any) -> int:
    """Return a non-negative int count, defaulting anything malformed to 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value >= 0 else 0


# One process-wide cache, keyed internally by path (one entry per session file)
# — see `mtime_cache.py`. Re-parses only when a session's state file mtime
# moves, which happens only on a genuine state write (new high-water, or an
# episode transition that bumps a count).
_STATE_CACHE: MtimeCachedFile[DowngradeRecord | None] = MtimeCachedFile(_parse_state, None)


def _session_state_path(dir_path: Path, session_id: str) -> Path:
    """Return the per-session state file path for ``session_id``."""
    return dir_path / f"{safe_session_stem(session_id)}.json"


def read_state(dir_path: Path, session_id: str) -> DowngradeRecord | None:
    """Read this session's full ``DowngradeRecord``, or ``None`` if unset.

    Fail-silent: a missing, unreadable, or malformed state file returns
    ``None`` exactly like "no prior state" — the status line render must
    never raise.
    """
    return _STATE_CACHE.read(_session_state_path(dir_path, session_id))


def read_high_water(dir_path: Path, session_id: str) -> tuple[str, int] | None:
    """Read this session's stored high-water ``(family, rank)``, or ``None``.

    Thin projection of :func:`read_state`, kept as the stable public accessor
    the downgrade evaluation and its tests already use.
    """
    record = read_state(dir_path, session_id)
    return (record.family, record.rank) if record is not None else None


def read_downgrade_counts(dir_path: Path, session_id: str) -> tuple[int, int]:
    """Read this session's ``(downgrade_count, recovery_count)`` tally.

    Returns ``(0, 0)`` when there is no state yet or the file predates the
    tally fields — never raises, matching the render-path contract.
    """
    record = read_state(dir_path, session_id)
    if record is None:
        return (0, 0)
    return (record.downgrade_count, record.recovery_count)


def _atomic_write(dir_path: Path, session_id: str, payload: dict[str, Any]) -> None:
    """Atomically replace this session's state file with ``payload``.

    Private-then-replace (tmp file + ``os.replace``, POSIX-atomic) so a
    concurrent reader — another render of the same session, or a peer session
    sharing the daemon (Plan 00127) — never observes a half-written file.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    stem = safe_session_stem(session_id)
    path = dir_path / f"{stem}.json"
    tmp_path = dir_path / f".{stem}.{os.getpid()}.tmp"
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(path)


def write_high_water(dir_path: Path, session_id: str, family: str, rank: int) -> None:
    """Atomically write this session's high-water ``(family, rank)``.

    Writes the MINIMAL record (no tally fields) — used to seed state and kept
    for backward compatibility. Episode tallies are maintained by
    :func:`evaluate_downgrade` via :func:`write_state`.
    """
    _atomic_write(dir_path, session_id, {_STATE_KEY_FAMILY: family, _STATE_KEY_RANK: rank})


def write_state(dir_path: Path, session_id: str, record: DowngradeRecord) -> None:
    """Atomically persist a full ``DowngradeRecord`` (high-water + tallies)."""
    _atomic_write(
        dir_path,
        session_id,
        {
            _STATE_KEY_FAMILY: record.family,
            _STATE_KEY_RANK: record.rank,
            _STATE_KEY_DOWNGRADE_COUNT: record.downgrade_count,
            _STATE_KEY_RECOVERY_COUNT: record.recovery_count,
            _STATE_KEY_ACTIVE: record.active,
        },
    )


def evaluate_downgrade(
    dir_path: Path,
    session_id: str,
    current_family: str,
    current_rank: int,
    *,
    manual: bool = False,
) -> tuple[str, str] | None:
    """Update this session's high-water state; report an active downgrade if any.

    Args:
        dir_path: Directory holding per-session state files.
        session_id: Owning session id (also the state-file key).
        current_family: Canonical family name for the model THIS render saw.
        current_rank: Rank for ``current_family``.
        manual: True when the ccy supervisor's manual-model-change marker
            (Plan 00316) shows THIS drop matches a command the human just
            typed. A manual drop is never reported as a downgrade — the
            high-water resets to the chosen family/rank instead, exactly
            like a fresh session starting there, so a further genuine SILENT
            substitution below it is still caught.

    Returns:
        ``(high_water_family, current_family)`` when ``current_rank`` is
        BELOW the stored high-water — an active downgrade. ``None`` on a
        first render (nothing stored yet), a new high (the render that set
        it), a manual drop, or an unchanged/equal rank — all of which report
        no downgrade. A downgrade render never rewrites the stored
        high-water, so the session's true peak survives a sustained
        downgrade and a later recovery is judged against it, not against the
        degraded value.

    Side effect: maintains the per-session EPISODE tallies (see
    :func:`read_downgrade_counts`). A downgrade increments ``downgrade_count``
    exactly once — on the render that OPENS the episode, not on every
    sustained render — and a return to (or above) the high-water increments
    ``recovery_count`` once and closes the episode. The state file is written
    only on these transitions and on a new high-water, so a sustained
    downgrade or a steady healthy session still costs a single ``stat()``.
    """
    prior = read_state(dir_path, session_id)

    # First render for this session — seed the high-water, no episode yet.
    if prior is None:
        write_state(dir_path, session_id, DowngradeRecord(current_family, current_rank))
        return None

    down, recovery, active = prior.downgrade_count, prior.recovery_count, prior.active

    # New high-water. If a downgrade episode was open, climbing to a new peak
    # is itself a recovery — count it and close the episode.
    if current_rank > prior.rank:
        if active:
            recovery += 1
        write_state(
            dir_path,
            session_id,
            DowngradeRecord(current_family, current_rank, down, recovery, active=False),
        )
        return None

    # Back at the high-water rank. If an episode was open, this closes it.
    if current_rank == prior.rank:
        if active:
            write_state(
                dir_path,
                session_id,
                DowngradeRecord(prior.family, prior.rank, down, recovery + 1, active=False),
            )
        return None

    # Plan 00316: a drop matching a recently-typed human `/model` command is
    # never a downgrade — reset the high-water to the manual choice (closing
    # any open episode as a recovery), exactly like a fresh session starting
    # there, so a LATER genuine silent substitution below it is still caught.
    if manual:
        if active:
            recovery += 1
        write_state(
            dir_path,
            session_id,
            DowngradeRecord(current_family, current_rank, down, recovery, active=False),
        )
        return None

    # Below the high-water — an active downgrade. Count it once, when the
    # episode opens; a sustained downgrade writes nothing further.
    if not active:
        write_state(
            dir_path,
            session_id,
            DowngradeRecord(prior.family, prior.rank, down + 1, recovery, active=True),
        )
    return prior.family, current_family
