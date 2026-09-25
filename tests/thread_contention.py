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
    """
    errors: list[BaseException] = []
    start = threading.Barrier(workers)

    def run(worker: int) -> None:
        start.wait()
        try:
            for index in range(calls_per_worker):
                call(worker, index)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(worker,)) for worker in range(workers)]
    with aggressive_preemption():
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    return errors
