"""Naming for the per-session signal files beside the context sidecar.

The directory the ccy supervisor watches and the stem rule that keeps an
untrusted session id inside it. Writers of per-session signal files name their
files through :func:`session_stem` so the rule has one home.
"""

from __future__ import annotations

import re
from typing import Final

#: Beside the context sidecar and the other signals the supervisor watches.
SIGNAL_SUBDIR: Final[str] = "context-sidecar"

#: The stem used when a session id is blank.
SESSION_ID_FALLBACK: Final[str] = "unknown"

_UNSAFE_SESSION_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")


def session_stem(session_id: str) -> str:
    """A filesystem-safe stem: separators and traversal dots cannot leave the directory."""
    stem = _UNSAFE_SESSION_CHARS.sub("_", session_id.strip())
    return stem or SESSION_ID_FALLBACK
