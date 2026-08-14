"""Shared mtime-gated file cache for status-line handlers (Plan 00238).

The status line re-renders roughly once a second for the life of the daemon, so
a handler that reads a small file on every render performs thousands of I/O
operations an hour for a value that has almost certainly not changed. Four
handlers were doing exactly that — measured at ~9,000-12,500 avoidable file
operations/hour across the enabled set.

The fix is one cheap ``stat()`` in place of a read + parse: re-parse only when
the file's mtime moves. ``settings_reader.py`` already implemented that for
``~/.claude/settings.json``; this module is that gate extracted so the other
handlers reuse it rather than growing three more copies. One implementation
means a bug in it is one fix, not four.

Follows the concurrency rules in this directory's ``CLAUDE.md``: reads are
fail-silent (a missing, unreadable or malformed file yields the caller's
default, never an exception, because a broken status line is worse than a
missing element), and the cache is per-process with one entry per path so it
stays bounded in a long-running daemon.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class MtimeCachedFile(Generic[T]):
    """Parse a file at most once per change to its mtime.

    Args:
        parse: Turns the file's text into the value the caller wants. May raise;
            a failure is reported as ``default`` and is NOT cached.
        default: Returned whenever the file is absent, unreadable, or unparseable.
    """

    def __init__(self, parse: Callable[[str], T], default: T) -> None:
        self._parse = parse
        self._default = default
        # path string -> (mtime_ns, parsed value). One entry per distinct path.
        self._cache: dict[str, tuple[int, T]] = {}

    def clear(self) -> None:
        """Empty the cache (used by tests for isolation)."""
        self._cache.clear()

    def read(self, path: Path) -> T:
        """Return the parsed value for ``path``, re-parsing only on mtime change."""
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            logger.debug("mtime_cache: not accessible: %s", path)
            return self._default

        path_key = str(path)
        cached = self._cache.get(path_key)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]

        try:
            value = self._parse(path.read_text())
        except Exception as exc:
            # Deliberately NOT cached. These files are written by other
            # processes (the ccy supervisor among them), so a failure here is
            # often a half-written file. Caching it would keep showing nothing
            # until the mtime happened to move again.
            logger.debug("mtime_cache: cannot parse %s: %s", path, exc)
            return self._default

        self._cache[path_key] = (mtime_ns, value)
        return value
