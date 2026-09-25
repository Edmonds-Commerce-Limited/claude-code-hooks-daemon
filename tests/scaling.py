"""Scaling-ratio measurement for the hostile-input performance tests.

A wall-clock bound fails on a loaded host and says nothing about growth. These
tests instead run the same work at size N and at ``SIZE_FACTOR`` x N and compare
the two costs, measured in the calling thread's CPU time (``time.thread_time``),
which other processes on the host do not inflate.

With an 8x larger input a linear cost grows about 8x and a quadratic one about
64x. ``SUPERLINEAR_RATIO`` sits between them.

A near-zero cost at N would make any ratio meaningless (a few microseconds
against a few more). So the denominator is never smaller than a BASELINE: the
cost, in the same process and on the same large input, of a reference scan
that is linear by construction. A linear handler, whatever its constant
factor, then has a ratio of at most ``SIZE_FACTOR``; a handler that costs
nothing measurable has a ratio near zero.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

SIZE_FACTOR: Final = 8
SUPERLINEAR_RATIO: Final = 24
# Each cost is the minimum over this many runs: noise only ever adds time.
REPEATS: Final = 3


def cpu_seconds(work: Callable[[], object]) -> float:
    """CPU seconds the calling thread spends running ``work`` once."""
    start = time.thread_time()
    work()
    return time.thread_time() - start


def min_cpu_seconds(work: Callable[[], object], repeats: int = REPEATS) -> float:
    """The least CPU time ``work`` takes over ``repeats`` runs."""
    return min(cpu_seconds(work) for _ in range(repeats))


def _visit_every_character(text: str) -> int:
    count = 0
    for _character in text:
        count += 1
    return count


def linear_baseline_seconds(text: str) -> float:
    """CPU time of one Python-level pass over every character of ``text``.

    Linear by construction, and the cheapest work a handler written in Python
    could do that still looks at its whole input. Below it, a cost is timer
    jitter (many handlers answer from a cache after the first call), and a
    ratio of two jitters says nothing about growth.
    """
    return min_cpu_seconds(lambda: _visit_every_character(text))


def scaling_ratio(work_at: Callable[[int], object], n: int, large_text: str) -> float:
    """Cost of ``work_at(SIZE_FACTOR * n)`` over the cost of ``work_at(n)``.

    Args:
        work_at: Runs the work under test on an input of the given size.
        n: The small size.
        large_text: The input ``work_at(SIZE_FACTOR * n)`` builds, for the
            baseline scan that floors the denominator.

    Returns:
        The ratio; above ``SUPERLINEAR_RATIO`` means superlinear growth.
    """
    small = min_cpu_seconds(lambda: work_at(n))
    large = min_cpu_seconds(lambda: work_at(SIZE_FACTOR * n))
    return large / max(small, linear_baseline_seconds(large_text))
