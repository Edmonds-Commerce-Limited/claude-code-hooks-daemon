"""Drive a callable from many threads at CPython's minimum switch interval.

Plan 00437 measured why this is needed: at the DEFAULT 5ms switch interval an
unlocked select-then-delete on a shared dict survived 16 threads of 200 calls
with zero errors, because the whole read-modify-write is a handful of bytecodes
and preemption almost never lands inside it. Driving the interval to its floor
reproduced the ``KeyError`` on the first round. A concurrency test that cannot
be observed failing is not evidence of anything, so every eviction-race test
uses these numbers.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Final

WORKERS: Final[int] = 32
CALLS_PER_WORKER: Final[int] = 2000
_MIN_SWITCH_INTERVAL: Final[float] = 1e-9
# Generous for a loaded runner, and still finite: a worker that can never
# arrive fails the test by name instead of holding the job until its timeout.
_ARRIVAL_TIMEOUT: Final[float] = 60.0


@contextmanager
def aggressive_preemption() -> Iterator[None]:
    """Make the interpreter switch threads as often as it is allowed to."""
    previous = sys.getswitchinterval()
    sys.setswitchinterval(_MIN_SWITCH_INTERVAL)
    try:
        yield
    finally:
        sys.setswitchinterval(previous)


def hammer(
    call: Callable[[int, int], object],
    *,
    workers: int = WORKERS,
    calls_per_worker: int = CALLS_PER_WORKER,
) -> list[BaseException]:
    """Run ``call(worker, index)`` from ``workers`` threads released together.

    Returns every exception a worker raised. They are collected rather than
    re-raised because an exception on a worker thread is invisible to pytest,
    so the caller's assertion on this list IS the report. Each worker stops at
    its first exception: one is proof enough, and a worker that keeps going
    only piles up copies of the same failure.

    Workers are started one at a time, each confirmed to be running before the
    next is created, and only parked at a barrier until every one has arrived;
    the interval drops to its floor afterwards. CPython 3.11 raises
    ``RuntimeError`` from ``Thread._bootstrap_inner`` when two threads call
    ``sys.settrace`` together — which coverage does for every new thread — and
    a worker that dies there never reaches the barrier, so the rest wait for it
    for ever (N428). Starting them serially at the default interval means no
    two are ever inside ``settrace`` at once. Any worker that still cannot
    arrive within ``_ARRIVAL_TIMEOUT`` fails the call with its number.

    Raises:
        AssertionError: a worker never started running, or never reached the barrier.
    """
    errors: list[BaseException] = []
    start = threading.Barrier(workers + 1)

    def run(worker: int, running: threading.Event) -> None:
        running.set()
        try:
            start.wait(timeout=_ARRIVAL_TIMEOUT)
            for index in range(calls_per_worker):
                call(worker, index)
        except Exception as exc:
            errors.append(exc)

    threads: list[threading.Thread] = []
    try:
        for worker in range(workers):
            running = threading.Event()
            thread = threading.Thread(target=run, args=(worker, running))
            threads.append(thread)
            thread.start()
            if not running.wait(timeout=_ARRIVAL_TIMEOUT):
                raise AssertionError(f"worker {worker} never started running")
        with aggressive_preemption():
            start.wait(timeout=_ARRIVAL_TIMEOUT)
            for thread in threads:
                thread.join()
    except threading.BrokenBarrierError as exc:
        raise AssertionError("a worker never reached the start barrier") from exc
    finally:
        start.abort()
        for thread in threads:
            if thread.ident is not None:
                thread.join()
    return errors
