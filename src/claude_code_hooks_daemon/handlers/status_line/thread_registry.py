"""Pure helpers for the multithread-indicator thread registry (Plan 00158 Phase 6).

The daemon serves every Claude Code session that resolves the same
``(hostname, project root)`` — several agents in one container, or a host plus a
background agent sharing a bind-mounted ``untracked/`` — from ONE process
(CLAUDE.md "Parallel sessions share one daemon"). Agent View lets a human
background one thread and open another, so at any moment N independent sessions
may be alive behind the single daemon, each rendering its OWN bottom
``statusLine`` bar (Plan 00158 Truth #5).

There is no field in the Status payload that tells one plain thread apart from
another (Plan 00158 Truth #1), so the only way to show "you are looking at
thread Y of X" is a daemon-side registry the sessions share on disk. This module
is that registry, split out as pure functions so the count/rank logic is unit
-testable without a Handler or a live daemon:

  1. ``upsert_heartbeat`` — every Status render, a session writes/refreshes a
     per-session heartbeat file keyed by ``session_id`` (``first_seen`` is
     preserved across renders; ``last_seen`` advances to now).
  2. ``read_live_entries`` — read every heartbeat, dropping any whose
     ``last_seen`` is older than the freshness window (a closed thread stops
     pinging and ages out) or that fails to parse.
  3. ``compute_indicator`` — order the survivors by ``first_seen`` (stable, so a
     thread keeps the same number for its lifetime), and render ``🧵 Y/X`` — or
     "" when a session is alone, so single-thread users see nothing.

Per the Plan 00158 Truth #6 thread-safety audit, daemon dispatch runs handler
chains on a multi-threaded executor pool, so concurrent sessions DO touch this
registry in parallel. Every write is therefore atomic (``tmp`` + ``os.replace``)
and keyed by ``session_id`` — never routed through the shared global
``SessionState`` singleton — so a concurrent reader never sees a half-written
file and two sessions never clobber each other's heartbeat.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Subdirectory (under the daemon untracked dir) holding per-session heartbeat
# files. Distinct from context-sidecar/ so the two sensors never collide.
_REGISTRY_SUBDIR = "thread-registry"

# A heartbeat whose ``last_seen`` is older than this many seconds is treated as
# a dead thread and pruned. Sized as a comfortable multiple of the installed
# ``statusLine.refreshInterval`` (Plan 00158 Phase 3, seconds) so a thread that
# goes idle keeps pinging on the refresh timer and is never falsely pruned while
# still alive — yet a genuinely-closed thread ages out within one window.
_FRESH_WINDOW_S = 45.0

# Filename stem used when the Status payload carries no usable session id.
_SESSION_ID_FALLBACK = "unknown"

# Any character outside this safe set is replaced with '_' before a session id
# is used as a filename component. Session ids are normally UUIDs, but an
# external value is never trusted to be path-safe.
_UNSAFE_SESSION_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


def safe_session_stem(session_id: str) -> str:
    """Return a filesystem-safe filename stem for an untrusted session id."""
    if not session_id:
        return _SESSION_ID_FALLBACK
    return _UNSAFE_SESSION_CHARS.sub("_", session_id)


def upsert_heartbeat(
    registry_dir: Path,
    session_id: str,
    session_name: str | None,
    agent_type: str | None,
    now: float,
) -> None:
    """Atomically write/refresh this session's heartbeat, preserving first_seen.

    Args:
        registry_dir: Directory holding the per-session heartbeat files.
        session_id: Owning session id (also the filename stem).
        session_name: Human-facing session name from the payload, if any.
        agent_type: ``agent_type`` from the payload (``None`` for a plain
            thread; set only when the session was launched as a named agent).
        now: Current epoch time; becomes ``last_seen`` (and ``first_seen`` on
            the very first render).
    """
    registry_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_session_stem(session_id)
    path = registry_dir / f"{stem}.json"

    first_seen = now
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
        prior_first = prior.get("first_seen")
        if isinstance(prior_first, (int, float)):
            first_seen = float(prior_first)
    except (OSError, ValueError):
        # No prior heartbeat, or it was unreadable/garbled — this render becomes
        # first_seen. Not an error worth surfacing on the status hot path.
        first_seen = now

    entry: dict[str, Any] = {
        "session_id": session_id,
        "first_seen": first_seen,
        "last_seen": now,
        "session_name": session_name,
        "agent_type": agent_type,
    }
    tmp_path = registry_dir / f".{stem}.{os.getpid()}.tmp"
    tmp_path.write_text(json.dumps(entry), encoding="utf-8")
    os.replace(tmp_path, path)


def read_live_entries(
    registry_dir: Path,
    now: float,
    window_s: float = _FRESH_WINDOW_S,
) -> list[dict[str, Any]]:
    """Read every heartbeat, dropping stale (aged-out) or garbled entries.

    Args:
        registry_dir: Directory holding the per-session heartbeat files.
        now: Current epoch time, compared against each entry's ``last_seen``.
        window_s: Freshness window in seconds; entries older than this are
            pruned as dead threads.

    Returns:
        The live heartbeat entries (unordered).
    """
    if not registry_dir.is_dir():
        return []

    live: list[dict[str, Any]] = []
    for child in registry_dir.iterdir():
        if child.suffix != ".json":
            continue
        try:
            entry = json.loads(child.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            # A concurrent writer's tmp file or a corrupt entry — skip it rather
            # than fail the whole render. Logged (not silently swallowed) so a
            # persistently unreadable heartbeat is visible at debug level.
            logger.debug("Skipping unreadable heartbeat %s: %s", child, e)
            continue
        last_seen = entry.get("last_seen")
        if not isinstance(last_seen, (int, float)):
            continue
        if now - last_seen <= window_s:
            live.append(entry)
    return live


def compute_indicator(entries: list[dict[str, Any]], this_session_id: str) -> str:
    """Render ``🧵 Y/X`` for this session, or "" when it is alone.

    Args:
        entries: The live heartbeat entries (from ``read_live_entries``).
        this_session_id: The session id the status bar is rendering for.

    Returns:
        ``🧵 <rank>/<total>`` when two or more threads are live and this session
        is among them; otherwise an empty string (single-thread sessions and
        the defensive "this session was pruned in a race" case render nothing).
    """
    ordered = sorted(
        entries,
        key=lambda e: (e.get("first_seen", 0.0), str(e.get("session_id", ""))),
    )
    total = len(ordered)
    if total <= 1:
        return ""

    for rank, entry in enumerate(ordered, 1):
        if entry.get("session_id") == this_session_id:
            return f"🧵 {rank}/{total}"

    return ""
