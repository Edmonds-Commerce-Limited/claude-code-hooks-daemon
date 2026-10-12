"""``hammer`` never lets a worker die unseen, and never hangs the run (N428).

CPython 3.11 raises ``RuntimeError: Cannot install a trace function while
another trace function is being installed`` from ``Thread._bootstrap_inner``
when two threads call ``sys.settrace`` at the same moment — which is exactly
what coverage does for every thread it sees, and what 32 workers started
back to back at a 1e-9 switch interval make likely. The error escapes OUTSIDE
``Thread.run``, so the worker dies before its first line: it never reaches the
start barrier, the other 31 wait for it for ever, and the Python 3.11 CI job
sat on one test until its 150-minute timeout.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, ClassVar, Final

import pytest

from tests import thread_contention
from tests.thread_contention import hammer

#: How long a released worker may take to finish once the barrier is aborted.
_RELEASED_WORKER_JOIN_SECONDS: Final[float] = 5.0


class _RecordingThread(threading.Thread):
    """Notes the switch interval and arrival count each time a worker is started."""

    started_at_interval: ClassVar[list[float]] = []
    arrivals_at_start: ClassVar[list[int]] = []
    arrived: ClassVar[list[int]] = []

    def run(self) -> None:
        self.arrived.append(1)
        super().run()

    def start(self) -> None:
        self.started_at_interval.append(sys.getswitchinterval())
        self.arrivals_at_start.append(len(self.arrived))
        super().start()


class _StillbornThread(threading.Thread):
    """The worker N428 lost: ``start`` returns and the thread never runs a line."""

    def start(self) -> None:
        return None


class _SecondWorkerStillborn(threading.Thread):
    """The first worker is real and parks at the barrier; every later one is lost."""

    first: ClassVar[list[threading.Thread]] = []

    def start(self) -> None:
        if self.first:
            return
        self.first.append(self)
        super().start()


class TestHammerStartsWorkersSafely:
    def test_workers_start_one_at_a_time_at_the_default_interval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No two threads can be inside ``settrace`` together, and none is
        created while the interval is at its floor."""
        _RecordingThread.started_at_interval.clear()
        _RecordingThread.arrivals_at_start.clear()
        _RecordingThread.arrived.clear()
        monkeypatch.setattr(threading, "Thread", _RecordingThread)
        default = sys.getswitchinterval()

        assert hammer(lambda worker, index: None, workers=6, calls_per_worker=1) == []

        assert _RecordingThread.started_at_interval == [default] * 6
        assert _RecordingThread.arrivals_at_start == [0, 1, 2, 3, 4, 5]

    def test_the_interval_is_restored_afterwards(self) -> None:
        before = sys.getswitchinterval()

        hammer(lambda worker, index: None, workers=4, calls_per_worker=1)

        assert sys.getswitchinterval() == before


class TestHammerFailsFastWhenAWorkerNeverRuns:
    def test_a_stillborn_worker_is_reported_instead_of_hanging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(thread_contention, "_ARRIVAL_TIMEOUT", 0.5)
        monkeypatch.setattr(threading, "Thread", _StillbornThread)

        with pytest.raises(AssertionError, match="worker 0 never started running"):
            hammer(lambda worker, index: None, workers=4, calls_per_worker=1)

    def test_workers_already_parked_are_released_when_a_later_one_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The healthy workers must not be left waiting on the barrier."""
        _SecondWorkerStillborn.first.clear()
        monkeypatch.setattr(thread_contention, "_ARRIVAL_TIMEOUT", 0.5)
        monkeypatch.setattr(threading, "Thread", _SecondWorkerStillborn)

        with pytest.raises(AssertionError, match="worker 1 never started running"):
            hammer(lambda worker, index: None, workers=4, calls_per_worker=1)

        parked = _SecondWorkerStillborn.first[0]
        parked.join(timeout=_RELEASED_WORKER_JOIN_SECONDS)
        assert not parked.is_alive()

    def test_a_worker_exception_is_still_collected(self) -> None:
        def boom(worker: int, index: int) -> Any:
            raise KeyError(worker)

        errors = hammer(boom, workers=3, calls_per_worker=2)

        assert len(errors) == 3
        assert all(isinstance(error, KeyError) for error in errors)
