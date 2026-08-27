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


def _parse_high_water(text: str) -> tuple[str, int] | None:
    """Parse one state file's text into ``(family, rank)``, or ``None``.

    Never raises: any malformed content is reported as "no prior state",
    matching this package's fail-silent render-path contract.
    """
    try:
        data: Any = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    family = data.get(_STATE_KEY_FAMILY)
    rank = data.get(_STATE_KEY_RANK)
    if not isinstance(family, str) or not isinstance(rank, int):
        return None
    return family, rank


# One process-wide cache, keyed internally by path (one entry per session file)
# — see `mtime_cache.py`. Re-parses only when a session's state file mtime
# moves, which happens only on a genuine new high-water write.
_HIGH_WATER_CACHE: MtimeCachedFile[tuple[str, int] | None] = MtimeCachedFile(
    _parse_high_water, None
)


def _session_state_path(dir_path: Path, session_id: str) -> Path:
    """Return the per-session state file path for ``session_id``."""
    return dir_path / f"{safe_session_stem(session_id)}.json"


def read_high_water(dir_path: Path, session_id: str) -> tuple[str, int] | None:
    """Read this session's stored high-water ``(family, rank)``, or ``None``.

    Fail-silent: a missing, unreadable, or malformed state file returns
    ``None`` exactly like "no prior state" — the status line render must
    never raise.
    """
    return _HIGH_WATER_CACHE.read(_session_state_path(dir_path, session_id))


def write_high_water(dir_path: Path, session_id: str, family: str, rank: int) -> None:
    """Atomically write this session's high-water ``(family, rank)``.

    Uses a private-then-replace write (tmp file + ``os.replace``, POSIX-atomic)
    so a concurrent reader — another render of the same session, or a peer
    session sharing the daemon (Plan 00127) — never observes a half-written
    file.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    stem = safe_session_stem(session_id)
    path = dir_path / f"{stem}.json"
    tmp_path = dir_path / f".{stem}.{os.getpid()}.tmp"
    payload: dict[str, Any] = {_STATE_KEY_FAMILY: family, _STATE_KEY_RANK: rank}
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(path)


def evaluate_downgrade(
    dir_path: Path,
    session_id: str,
    current_family: str,
    current_rank: int,
) -> tuple[str, str] | None:
    """Update this session's high-water state; report an active downgrade if any.

    Args:
        dir_path: Directory holding per-session state files.
        session_id: Owning session id (also the state-file key).
        current_family: Canonical family name for the model THIS render saw.
        current_rank: Rank for ``current_family``.

    Returns:
        ``(high_water_family, current_family)`` when ``current_rank`` is
        BELOW the stored high-water — an active downgrade. ``None`` on a
        first render (nothing stored yet), a new high (the render that set
        it), or an unchanged/equal rank — all of which report no downgrade.
        A downgrade render never rewrites the stored high-water, so the
        session's true peak survives a sustained downgrade and a later
        recovery is judged against it, not against the degraded value.
    """
    prior = read_high_water(dir_path, session_id)
    if prior is None or current_rank > prior[1]:
        write_high_water(dir_path, session_id, current_family, current_rank)
        return None
    if current_rank < prior[1]:
        return prior[0], current_family
    return None
