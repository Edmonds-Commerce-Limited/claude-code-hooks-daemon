# Unfinished work saved from the `worktree-n466-n252` worktree

That branch is merged into `main`, but its worktree held uncommitted work that
was never committed (branch head: `581ccadd3 2026-09-29 Ledger 00466 N252: scaling tests compare two sizes inside one regime`). It changes the `tests/scaling.py`
helper and adds a test for it, apparently toward ledger 00466 N222 (tests that
assert absolute wall-clock bounds). It is kept here verbatim so it can be
reviewed and finished on `main`, or dismissed.

## `git diff` of `tests/scaling.py`

````diff
diff --git a/tests/scaling.py b/tests/scaling.py
index 61981613a..bf8430dc1 100644
--- a/tests/scaling.py
+++ b/tests/scaling.py
@@ -3,7 +3,10 @@
 A wall-clock bound fails on a loaded host and says nothing about growth. These
 tests instead run the same work at size N and at ``SIZE_FACTOR`` x N and compare
 the two costs, measured in the calling thread's CPU time (``time.thread_time``),
-which other processes on the host do not inflate.
+which does not count the time other processes hold the CPU. Load still moves
+it: a core shared with a busy neighbour runs slower, and the clock itself can
+lag, so each cost is the least of several measurements that each span at least
+``MIN_MEASURED_SECONDS``.
 
 With an 8x larger input a linear cost grows about 8x and a quadratic one about
 64x. ``SUPERLINEAR_RATIO`` sits between them.
@@ -18,21 +21,48 @@ nothing measurable has a ratio near zero.
 
 from __future__ import annotations
 
+import functools
 import time
 from collections.abc import Callable
 from typing import Final
 
 SIZE_FACTOR: Final = 8
 SUPERLINEAR_RATIO: Final = 24
-# Each cost is the minimum over this many runs: noise only ever adds time.
+# Each cost is the minimum over this many measurements: contention only ever
+# adds time.
 REPEATS: Final = 3
 
+#: The least CPU time one measurement spans. Under host load the thread CPU
+#: clock can stop advancing for a couple of milliseconds and then catch up in
+#: one jump (00466 N252: ~5 us of work read zero 1,429 times in 200,000 runs,
+#: up to 461 in a row), so a single microsecond-scale call reads zero and the
+#: minimum picks it. Repeating the work until the clock has moved this far
+#: holds that error to a few percent.
+MIN_MEASURED_SECONDS: Final = 0.01
+
+#: Runs after which a clock that has not moved is broken, not lagging: at a
+#: microsecond per run, far past any lag seen.
+_MAX_RUNS_PER_MEASUREMENT: Final = 1_000_000
+
 
 def cpu_seconds(work: Callable[[], object]) -> float:
-    """CPU seconds the calling thread spends running ``work`` once."""
+    """CPU seconds the calling thread spends per run of ``work``, over as many
+    back-to-back runs as it takes the clock to move ``MIN_MEASURED_SECONDS``.
+
+    Raises:
+        RuntimeError: The clock did not move in ``_MAX_RUNS_PER_MEASUREMENT``
+            runs.
+    """
     start = time.thread_time()
-    work()
-    return time.thread_time() - start
+    for runs in range(1, _MAX_RUNS_PER_MEASUREMENT + 1):
+        work()
+        elapsed = time.thread_time() - start
+        if elapsed >= MIN_MEASURED_SECONDS:
+            return elapsed / runs
+    raise RuntimeError(
+        f"the thread CPU clock did not advance {MIN_MEASURED_SECONDS}s "
+        f"in {_MAX_RUNS_PER_MEASUREMENT} runs"
+    )
 
 
 def min_cpu_seconds(work: Callable[[], object], repeats: int = REPEATS) -> float:
@@ -47,6 +77,7 @@ def _visit_every_character(text: str) -> int:
     return count
 
 
+@functools.lru_cache(maxsize=16)
 def linear_baseline_seconds(text: str) -> float:
     """CPU time of one Python-level pass over every character of ``text``.
 
@@ -54,6 +85,9 @@ def linear_baseline_seconds(text: str) -> float:
     could do that still looks at its whole input. Below it, a cost is timer
     jitter (many handlers answer from a cache after the first call), and a
     ratio of two jitters says nothing about growth.
+
+    Cached per text: a sweep floors every handler's ratio with the same scan
+    of the same input, and it is a floor, not a measurement under test.
     """
     return min_cpu_seconds(lambda: _visit_every_character(text))
 
@@ -61,6 +95,10 @@ def linear_baseline_seconds(text: str) -> float:
 def scaling_ratio(work_at: Callable[[int], object], n: int, large_text: str) -> float:
     """Cost of ``work_at(SIZE_FACTOR * n)`` over the cost of ``work_at(n)``.
 
+    The denominator is never below the baseline scan of ``large_text``, so a
+    large cost at or under that baseline has a ratio of at most 1 whatever
+    the small size costs: that ratio is returned without measuring it.
+
     Args:
         work_at: Runs the work under test on an input of the given size.
         n: The small size.
@@ -70,9 +108,12 @@ def scaling_ratio(work_at: Callable[[int], object], n: int, large_text: str) ->
     Returns:
         The ratio; above ``SUPERLINEAR_RATIO`` means superlinear growth.
     """
-    small = min_cpu_seconds(lambda: work_at(n))
+    floor = linear_baseline_seconds(large_text)
     large = min_cpu_seconds(lambda: work_at(SIZE_FACTOR * n))
-    return large / max(small, linear_baseline_seconds(large_text))
+    if large <= floor:
+        return large / floor
+    small = min_cpu_seconds(lambda: work_at(n))
+    return large / max(small, floor)
 
 
 def counted_ratio(count_at: Callable[[int], int], n: int) -> float:
````

## New file `tests/unit/test_scaling.py`

````python
"""The growth-ratio harness itself (``tests/scaling.py``, Plan 00466 N252).

Under host load this container's per-thread CPU clock stops advancing for up
to a couple of milliseconds and then catches up in one jump: ~5 us of work
read as zero 1,429 times in 200,000 runs, in runs of up to 461 in a row. A
measurement of one microsecond-scale call then reads zero, the least of
three readings picks it, and a handler that grows linearly measured 50x, or
the ratio divided by zero. These tests drive the harness with a clock that
lags that way, so they are deterministic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import SimpleNamespace

import pytest

from tests import scaling
from tests.scaling import MIN_MEASURED_SECONDS, SIZE_FACTOR, cpu_seconds, scaling_ratio


#: What one reading of the clock itself costs, as a real reading does.
_READ_COST = 1e-6


class _LaggingClock:
    """A thread CPU clock that work advances, which can lag and catch up.

    ``run(cost)`` is work costing ``cost`` seconds, and every reading costs
    ``_READ_COST``. While ``lag_until`` is ahead of the true time the reading
    stays where it was, and the whole backlog shows up at the first reading
    after that.
    """

    def __init__(self) -> None:
        self.true_seconds = 0.0
        self.shown_seconds = 0.0
        self.lag_until = 0.0

    def thread_time(self) -> float:
        self.true_seconds += _READ_COST
        if self.true_seconds >= self.lag_until:
            self.shown_seconds = self.true_seconds
        return self.shown_seconds

    def run(self, cost: float) -> None:
        self.true_seconds += cost


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[_LaggingClock]:
    """The fake clock, with no baseline cached from a real one or left for one."""
    lagging = _LaggingClock()
    monkeypatch.setattr(scaling, "time", SimpleNamespace(thread_time=lagging.thread_time))
    scaling.linear_baseline_seconds.cache_clear()
    yield lagging
    scaling.linear_baseline_seconds.cache_clear()


def _counting(clock: _LaggingClock, cost: float) -> tuple[Callable[[], None], list[int]]:
    runs = [0]

    def work() -> None:
        runs[0] += 1
        clock.run(cost)

    return work, runs


class TestCpuSeconds:
    def test_repeats_short_work_until_the_clock_has_moved_the_minimum(
        self, clock: _LaggingClock
    ) -> None:
        per_run = MIN_MEASURED_SECONDS / 49.5
        work, runs = _counting(clock, per_run - _READ_COST)
        assert cpu_seconds(work) == pytest.approx(per_run)
        assert runs[0] == 50

    def test_runs_work_longer_than_the_minimum_once(self, clock: _LaggingClock) -> None:
        work, runs = _counting(clock, 3 * MIN_MEASURED_SECONDS)
        assert cpu_seconds(work) == pytest.approx(3 * MIN_MEASURED_SECONDS + _READ_COST)
        assert runs[0] == 1

    def test_a_clock_that_lags_and_catches_up_is_averaged_out(self, clock: _LaggingClock) -> None:
        """The failure itself: the clock shows nothing for the first 2 ms of
        20 us calls. Timed alone, the first hundred calls each read zero."""
        cost = 20e-6 - _READ_COST
        clock.lag_until = 2e-3
        work, _runs = _counting(clock, cost)
        assert cpu_seconds(work) == pytest.approx(20e-6, rel=1e-3)

    def test_a_clock_that_never_moves_raises(self, clock: _LaggingClock) -> None:
        """Fail fast rather than loop for ever on a clock that is broken."""
        clock.lag_until = float("inf")
        with pytest.raises(RuntimeError, match="did not advance"):
            cpu_seconds(lambda: None)


class TestScalingRatio:
    def test_linear_work_under_a_lagging_clock_measures_linear(
        self, clock: _LaggingClock
    ) -> None:
        """Timed one call at a time, the small size's three readings all fall
        inside the lag and read zero, and the ratio is the large cost over
        the baseline scan."""
        clock.lag_until = 2e-3

        def work_at(size: int) -> None:
            clock.run(size * 1e-6 - _READ_COST)

        ratio = scaling_ratio(work_at, 20, "x")
        assert ratio == pytest.approx(SIZE_FACTOR)

    def test_a_large_cost_under_the_baseline_skips_the_small_size(
        self, clock: _LaggingClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The denominator is at least the baseline, so the ratio is at most 1
        and the small size cannot change the verdict."""
        monkeypatch.setattr(
            scaling, "_visit_every_character", lambda text: clock.run(len(text) * 1e-7)
        )
        sizes: list[int] = []

        def work_at(size: int) -> None:
            sizes.append(size)

        assert scaling_ratio(work_at, 20, "x" * 1000) < 1
        assert set(sizes) == {SIZE_FACTOR * 20}

    def test_the_baseline_is_measured_once_per_text(self, clock: _LaggingClock) -> None:
        measured = clock.true_seconds
        first = scaling.linear_baseline_seconds("x" * 1000)
        spent = clock.true_seconds - measured
        assert scaling.linear_baseline_seconds("x" * 1000) == first
        assert clock.true_seconds - measured == spent
````
