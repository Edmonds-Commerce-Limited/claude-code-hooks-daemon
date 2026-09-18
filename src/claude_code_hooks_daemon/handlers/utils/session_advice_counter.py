"""Per-session advice rate limiting, shared and atomic (Plan 00437).

A default-on advisory registered on a high-frequency event (Stop, PostToolUse)
would speak on every single event without this: it advises on the FIRST
qualifying event for a session and then every ``interval``-th.

Two handlers grew their own copy of the same eight lines —
``teammate_reap_advisor`` and ``background_process_tracker``, each with its own
``_MAX_TRACKED_SESSIONS`` and ``_COUNT_START`` beside it (ledger 00422 N5 row
(c)). Both copies evicted without a lock:

    if len(counts) >= max_sessions:
        del counts[next(iter(counts))]

**Handlers are daemon-lifetime singletons and dispatch really is threaded**, so
two concurrent requests can run that branch at once: ``server.py`` dispatches
through ``loop.run_in_executor(None, controller.dispatch, ...)`` and the default
executor is a ``ThreadPoolExecutor``. Two threads selecting the same victim key
make the second ``del`` raise ``KeyError``, and ``next(iter(...))`` can raise
``RuntimeError`` if the dict changes size mid-iteration.

The window is narrow — at CPython's default 5ms switch interval the unlocked
version survives heavy hammering untouched, and it took driving the interval to
its floor to reproduce it. Narrow is not absent: the cost is an exception out of
a Stop handler, and the lock costs nothing measurable on a path that already
crosses a socket.
"""

from __future__ import annotations

import threading

#: The first qualifying event for a session is event number 1, and it advises.
_COUNT_START: int = 1


class SessionAdviceCounter:
    """Bounded, thread-safe "is it this session's turn to be advised?" counter.

    Args:
        interval: Advise on the first qualifying event, then every ``interval``-th.
        max_sessions: Cap on tracked sessions. On reaching it, an arbitrary
            existing entry is evicted — the map is a rate-limit hint, not a
            ledger, so WHICH entry goes does not matter, only that the map
            stays bounded on a process that never restarts.
    """

    def __init__(self, *, interval: int, max_sessions: int) -> None:
        self._interval = interval
        self._max_sessions = max_sessions
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def should_advise(self, session_id: str) -> bool:
        """Record one qualifying event for ``session_id``; say whether to speak.

        The whole read-modify-write happens under the lock, which is the point:
        splitting it is what let two threads agree on a victim key and race to
        delete it.
        """
        with self._lock:
            count = self._counts.get(session_id)
            if count is None:
                if len(self._counts) >= self._max_sessions:
                    # popitem() rather than `del counts[next(iter(counts))]`:
                    # one atomic operation instead of a select-then-delete pair,
                    # so even a future caller that forgets the lock cannot hit
                    # the KeyError this class exists to remove.
                    self._counts.popitem()
                count = _COUNT_START
            else:
                count += 1
            self._counts[session_id] = count
            return (count - _COUNT_START) % self._interval == 0

    def tracked_sessions(self) -> int:
        """How many sessions the map currently holds (for tests and reports)."""
        with self._lock:
            return len(self._counts)
