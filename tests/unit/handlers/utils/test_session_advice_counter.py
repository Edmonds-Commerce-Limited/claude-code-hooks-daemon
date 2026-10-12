"""The shared per-session advice counter (Plan 00437, ledger 00422 N5 row (c)).

Two handlers carried the same eight lines of rate-limit bookkeeping, each with
its own unlocked eviction:

    if len(self._session_counts) >= _MAX_TRACKED_SESSIONS:
        del self._session_counts[next(iter(self._session_counts))]

Two threads reaching a full map can pick the same key, and the second ``del``
raises ``KeyError``; ``next(iter(...))`` can also raise ``RuntimeError`` when
the dict changes size mid-iteration.

**The threads are real.** The daemon is asyncio and owns no thread pool, but
``server.py`` dispatches via ``loop.run_in_executor(None, controller.dispatch,
...)`` and the default executor is a ``ThreadPoolExecutor`` — so two concurrent
requests run handler code, which is a daemon-lifetime singleton, on two worker
threads.
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.thread_contention import hammer

from claude_code_hooks_daemon.handlers.utils.session_advice_counter import (
    SessionAdviceCounter,
)

_INTERVAL: Final[int] = 10


class TestConstructorValidation:
    """Invalid arguments must fail fast at construction, not corrupt behaviour later."""

    def test_zero_interval_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="interval"):
            SessionAdviceCounter(interval=0, max_sessions=256)

    def test_negative_interval_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="interval"):
            SessionAdviceCounter(interval=-1, max_sessions=256)

    def test_zero_max_sessions_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="max_sessions"):
            SessionAdviceCounter(interval=_INTERVAL, max_sessions=0)

    def test_negative_max_sessions_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="max_sessions"):
            SessionAdviceCounter(interval=_INTERVAL, max_sessions=-1)


class TestRateLimit:
    """The behaviour both handlers had before the extraction, unchanged."""

    def test_the_first_event_for_a_session_advises(self) -> None:
        counter = SessionAdviceCounter(interval=_INTERVAL, max_sessions=256)
        assert counter.should_advise("s1") is True

    def test_the_next_events_stay_silent_until_the_interval(self) -> None:
        counter = SessionAdviceCounter(interval=_INTERVAL, max_sessions=256)
        results = [counter.should_advise("s1") for _ in range(_INTERVAL + 1)]
        assert results[0] is True
        assert not any(results[1:_INTERVAL])
        assert results[_INTERVAL] is True

    def test_sessions_are_counted_independently(self) -> None:
        counter = SessionAdviceCounter(interval=_INTERVAL, max_sessions=256)
        assert counter.should_advise("s1") is True
        assert counter.should_advise("s2") is True
        assert counter.should_advise("s1") is False


class TestBounding:
    def test_the_map_never_exceeds_its_cap(self) -> None:
        counter = SessionAdviceCounter(interval=_INTERVAL, max_sessions=4)
        for index in range(40):
            counter.should_advise(f"s{index}")
        assert counter.tracked_sessions() <= 4

    def test_eviction_is_fifo_not_lifo(self) -> None:
        """Filling the map past its cap must drop the OLDEST entry.

        ``dict.popitem()`` evicts the NEWEST (LIFO), which turns the newest
        slot into a revolving door: a session that arrives right after the
        cap is hit gets evicted on the very next new session, and its counter
        resets, so it re-advises from event 1 instead of staying silent.
        """
        counter = SessionAdviceCounter(interval=_INTERVAL, max_sessions=4)
        for index in range(4):
            counter.should_advise(f"s{index}")

        # s0 is the oldest entry; a new session must evict it, not s3.
        counter.should_advise("s4")

        # s3 (most recently inserted before s4) must still be tracked, so its
        # next event continues counting instead of restarting at 1.
        assert counter.should_advise("s3") is False

        # s0 was evicted, so it restarts at event 1 and advises again.
        assert counter.should_advise("s0") is True


class TestConcurrentCallersNeverRaise:
    """The defect: an unlocked read-modify-write on a shared singleton.

    Drives a map that is already AT its cap from many threads, so every call
    takes the eviction branch — the narrow window where two threads select the
    same victim key.
    """

    def test_no_exception_escapes_under_concurrent_eviction(self) -> None:
        cap = 8
        counter = SessionAdviceCounter(interval=_INTERVAL, max_sessions=cap)
        for index in range(cap):
            counter.should_advise(f"seed{index}")

        errors = hammer(lambda worker, call: counter.should_advise(f"w{worker}-{call}"))

        assert not errors, f"concurrent callers raised: {errors[:3]}"
        assert counter.tracked_sessions() <= cap
