"""One-shot human approval markers (Plan 00367).

A human who opts into a daemon gate (closing a plan, merging a parent
worktree into main) records an approval for ONE key -- a plan number, a
branch name -- and the first gated action with that key consumes it. The
marker lives under the daemon's untracked directory so it can never be
committed, and it is one-shot so an approval is for one action, not a
standing waiver.

Pydantic-free and git-free: the handlers and the CLI both call it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

#: Marker filename suffix; the stem is the normalised key.
MARKER_SUFFIX: Final[str] = ".approved"

#: Anything that is not a safe filename character becomes ``_``, so a key
#: like ``feature/x`` or ``../etc`` can neither collide by accident with a
#: plain name nor leave the store's directory.
_UNSAFE_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]")
_PARENT_DIR: Final[str] = ".."


def _normalise_key(key: str) -> str:
    safe = _UNSAFE_CHARS.sub("_", key.strip())
    return safe.replace(_PARENT_DIR, "__")


class OneShotApprovalStore:
    """Markers for one gate, in one sub-directory of the untracked dir."""

    def __init__(self, subdir: str) -> None:
        self._subdir = subdir

    def path(self, untracked_dir: Path, key: str) -> Path:
        """Where the approval for ``key`` lives."""
        return untracked_dir / self._subdir / f"{_normalise_key(key)}{MARKER_SUFFIX}"

    def record(self, untracked_dir: Path, key: str) -> Path:
        """Write the marker (creating its directory) and return its path."""
        marker = self.path(untracked_dir, key)
        marker.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        marker.write_text(f"{key} approved at {stamp}\n", encoding="utf-8")
        return marker

    def consume(self, untracked_dir: Path, key: str) -> bool:
        """Remove the marker for ``key``; True if there was one to consume."""
        try:
            self.path(untracked_dir, key).unlink()
        except FileNotFoundError:
            return False
        return True
