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
missing element), and the cache is per-process with one entry per path. A
FIXED-path caller (settings.json, the account conf) is trivially bounded --
one entry, forever. A PER-SESSION caller (one file per session id) is bounded
only in combination with whatever reaps the session's file on disk: a
``stat()`` failure evicts the corresponding cache entry rather than leaving it
in place, so once a session's file is gone the cache converges to match --
see ``daemon/paths.py``'s ``cleanup_stale_session_dirs`` for the reaper side.
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
            # Plan 00319 F7: evict rather than leave a stale entry in place. A
            # single-fixed-path caller (settings.json, the account conf) never
            # hits this branch for real, but a PER-SESSION caller does the
            # moment its file is reaped -- and never reads that exact path
            # again once the session is dead, so a stale entry left here would
            # sit in memory for the rest of the daemon process's life. Combined
            # with the per-session subdir reaper (daemon/paths.py), this keeps
            # the cache bounded by currently-live sessions rather than every
            # session the daemon has ever rendered a line for.
            self._cache.pop(str(path), None)
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
