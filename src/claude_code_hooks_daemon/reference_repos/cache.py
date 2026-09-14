"""The TTL cache that lets PreToolUse enforce without touching the network.

SessionStart fetches and writes what it found here; PreToolUse reads this and
nothing else. That split is the architecture (see :mod:`inspection` for the
timeout arithmetic that forces it), and this module exists to make one property
impossible to get wrong:

    **anything other than a valid, in-date entry reads as NOT VERIFIED.**

Missing, expired, truncated, hand-edited, written by an older schema, or stamped
with a future time — every one of those returns ``None``, never a reading. The
asymmetry is deliberate and worth stating, because the two errors are not
comparable: reporting a fresh repo as unverified costs one avoidable check,
while reporting a STALE repo as fresh is exactly the silent defect this whole
plan exists to prevent.

``None`` and ``{}`` are different answers and callers must keep them apart.
``None`` means nothing is known. ``{}`` means the sweep ran and this project
governs no repositories — which is the ordinary state of a project that has not
adopted the convention, and must not make an enforcing caller speak up.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from time import time
from typing import Any, Final

from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState
from claude_code_hooks_daemon.utils.ccy_supervisor import daemon_untracked_dir

logger = logging.getLogger(__name__)

#: Bumped whenever the on-disk shape changes. A reader that meets a different
#: version discards rather than interprets — a cache misread as a newer shape
#: would report confident nonsense, which is worse than reporting nothing.
CACHE_VERSION: Final[int] = 2

#: How long a reading stays trustworthy. Long enough that a normal session does
#: not re-sweep constantly, short enough that a long session cannot enforce all
#: day against what was true when it opened.
DEFAULT_TTL_SECONDS: Final[float] = 900.0

_CACHE_FILENAME: Final[str] = "reference-repos.json"

#: Every field a cached reading must carry. A payload missing any of these is
#: discarded rather than defaulted: a default reads as innocent (``behind=0``),
#: which would turn a truncated write into a silent "everything is fine".
_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "path",
    "checkability",
    "branch",
    "default_branch",
    "upstream",
    "behind",
    "ahead",
    "dirty",
    # Required, not defaulted, for exactly the reason above: False is the
    # innocent reading, so a v1 cache silently defaulted here would claim every
    # repo's refs had been confirmed against its remote.
    "fetch_failed",
)


def cache_path(project_root: Path) -> Path:
    """Where the cache lives — under the daemon's untracked dir, never tracked."""
    return daemon_untracked_dir(project_root) / _CACHE_FILENAME


def _encode(state: RepoState) -> dict[str, Any]:
    return {
        "path": str(state.path),
        "checkability": str(state.checkability),
        "branch": state.branch,
        "default_branch": state.default_branch,
        "upstream": state.upstream,
        "behind": state.behind,
        "ahead": state.ahead,
        "dirty": state.dirty,
        "fetch_failed": state.fetch_failed,
    }


def _decode(raw: object) -> RepoState | None:
    """Rebuild one reading, or ``None`` if the payload is not exactly right."""
    if not isinstance(raw, dict):
        return None
    if any(field not in raw for field in _REQUIRED_FIELDS):
        return None
    try:
        checkability = Checkability(raw["checkability"])
    except ValueError:
        # A value this build does not know about — most likely a newer schema.
        return None
    try:
        return RepoState(
            path=Path(str(raw["path"])),
            checkability=checkability,
            branch=raw["branch"],
            default_branch=raw["default_branch"],
            upstream=raw["upstream"],
            behind=int(raw["behind"]),
            ahead=int(raw["ahead"]),
            dirty=bool(raw["dirty"]),
            fetch_failed=bool(raw["fetch_failed"]),
        )
    except (TypeError, ValueError):
        return None


def write_cache(
    project_root: Path,
    states: Sequence[RepoState],
    *,
    now: float | None = None,
) -> None:
    """Record ``states`` as the current reading for ``project_root``.

    Replaces the file wholesale rather than merging, so a repository that has
    stopped being governed cannot linger as a stale entry nobody refreshes.

    Never raises. A cache that cannot be written simply means the next reader
    gets NOT VERIFIED, which is the safe answer — whereas an exception here
    would break SessionStart for every project on a full disk.
    """
    payload = {
        "version": CACHE_VERSION,
        "recorded_at": time() if now is None else now,
        "repos": [_encode(state) for state in states],
    }
    path = cache_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.debug("reference-repo cache not written (%s): %s", path, exc)


def cached_states(
    project_root: Path,
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> dict[Path, RepoState] | None:
    """Return the cached readings, or ``None`` when nothing can be trusted.

    Args:
        project_root: The project whose cache to read.
        ttl_seconds: How old a reading may be and still count. An age exactly
            equal to the TTL is still valid; older is not.
        now: Current time, injectable for tests.

    Returns:
        A mapping of repo path to reading, ``{}`` when the sweep ran and found
        no governed repos, or ``None`` when the cache is missing, expired, or
        unusable for any reason.
    """
    path = cache_path(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("version") != CACHE_VERSION:
        return None

    recorded_at = payload.get("recorded_at")
    if not isinstance(recorded_at, (int, float)):
        return None

    age = (time() if now is None else now) - float(recorded_at)
    # A NEGATIVE age means the entry is stamped in the future — clock skew, or
    # a file copied from another machine. Left to `age > ttl` alone it would
    # never expire, which is the one way a cache can pin a stale reading in
    # place permanently.
    if age < 0 or age > ttl_seconds:
        return None

    raw_repos = payload.get("repos")
    if not isinstance(raw_repos, list):
        return None

    states: dict[Path, RepoState] = {}
    for raw in raw_repos:
        state = _decode(raw)
        if state is None:
            # One unusable entry condemns the file. Returning the readable
            # remainder would silently drop a repo, and a dropped repo looks
            # identical to one that was never governed.
            return None
        states[state.path] = state
    return states
