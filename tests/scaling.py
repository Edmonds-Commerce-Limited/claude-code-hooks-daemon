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

The CPU clock only advances in ticks, so a cost can read exactly 0.0. The
denominator is therefore also never smaller than one tick of that clock, which
keeps the ratio finite and meaningful: an unmeasurably cheap case is a pass.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Final

SIZE_FACTOR: Final = 8
SUPERLINEAR_RATIO: Final = 24
# Each cost is the minimum over this many runs: noise only ever adds time.
REPEATS: Final = 3
# Cheap work is sampled until this much CPU time has been spent on it, so that
# a microsecond-scale cost is the minimum of many runs, not of three.
SAMPLE_BUDGET_SECONDS: float = 0.01
# Most runs of any one measurement, however cheap the work.
MAX_REPEATS: Final = 40
# Longest the clock is spun while looking for its next tick.
_RESOLUTION_PROBE_SECONDS: float = 0.05
# One tick where the platform cannot report the clock's resolution (Windows
# advances its CPU clocks in about 15.6 ms steps).
FALLBACK_RESOLUTION_SECONDS: Final = 0.016


@functools.cache
def clock_resolution_seconds() -> float:
    """The granularity of ``time.thread_time``: one whole tick of it.

    Spins the calling thread across two consecutive advances of the clock, so
    the step is the one this host really exhibits (the first advance starts
    mid-tick and is discarded) rather than the nanosecond a coarse clock may
    claim. If the clock does not advance twice within the probe window, the
    platform's reported resolution is used, else ``FALLBACK_RESOLUTION_SECONDS``.
    """
    previous = time.thread_time()
    advanced_from: float | None = None
    deadline = time.perf_counter() + _RESOLUTION_PROBE_SECONDS
    while time.perf_counter() < deadline:
        now = time.thread_time()
        if now == previous:
            continue
        if advanced_from is not None:
            return now - advanced_from
        advanced_from = now
        previous = now
    clock_getres = getattr(time, "clock_getres", None)
    clock_id = getattr(time, "CLOCK_THREAD_CPUTIME_ID", None)
    if clock_getres is None or clock_id is None:
        return FALLBACK_RESOLUTION_SECONDS
    reported: float = clock_getres(clock_id)
    return reported if reported > 0.0 else FALLBACK_RESOLUTION_SECONDS


def cpu_seconds(work: Callable[[], object]) -> float:
    """CPU seconds the calling thread spends running ``work`` once."""
    start = time.thread_time()
    work()
    return time.thread_time() - start


def min_cpu_seconds(work: Callable[[], object], repeats: int = REPEATS) -> float:
    """The least CPU time ``work`` takes over at least ``repeats`` runs.

    Noise only ever adds time, so the minimum is the estimate. Work that costs
    microseconds is also the work a scheduler hiccup can swamp, and three
    samples of it are too few to be sure one escaped the hiccup: it keeps
    sampling, up to ``MAX_REPEATS`` runs, until it has spent
    ``SAMPLE_BUDGET_SECONDS`` of CPU. Work that costs more than a third of the
    budget per run stops at ``repeats`` runs, exactly as before.
    """
    best = cpu_seconds(work)
    spent = best
    runs = 1
    while runs < MAX_REPEATS and (runs < repeats or spent < SAMPLE_BUDGET_SECONDS):
        cost = cpu_seconds(work)
        best = min(best, cost)
        spent += cost
        runs += 1
    return best


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
    floor = max(linear_baseline_seconds(large_text), clock_resolution_seconds())
    return large / max(small, floor)


def counted_ratio(count_at: Callable[[int], int], n: int) -> float:
    """Cost of ``count_at(SIZE_FACTOR * n)`` over the cost of ``count_at(n)``,
    where "cost" is a caller-supplied unit count rather than elapsed time.

    Plan 00466 N24 review 3 MA5: ``scaling_ratio`` measures real handler
    dispatch, which has no operation count to read back, only elapsed CPU
    time -- inherently noisy under a loaded host. A test that exists purely
    to pin the RATIO ARITHMETIC (does an 8x/64x growth clear the same
    ``SUPERLINEAR_RATIO`` threshold) has no need for that noise: it can
    count exactly how much work its own linear/quadratic reference
    functions do and compare counts directly, with the same threshold and
    the same shape, deterministically on any host under any load.
    """
    small = count_at(n)
    large = count_at(SIZE_FACTOR * n)
    return large / max(small, 1)
