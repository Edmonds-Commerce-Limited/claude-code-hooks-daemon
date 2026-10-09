"""The scaling-ratio harness must never raise on a CPU clock too coarse for the work."""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from tests import scaling

_TICK = 0.004


def _install_clock(
    monkeypatch: pytest.MonkeyPatch,
    thread_time: Callable[[], float],
    resolution: float = _TICK,
) -> None:
    """Replace the harness's CPU clock and its measured resolution."""
    monkeypatch.setattr(
        scaling,
        "time",
        SimpleNamespace(thread_time=thread_time, perf_counter=time.perf_counter),
    )
    monkeypatch.setattr(scaling, "clock_resolution_seconds", lambda: resolution)
    # These tests script exactly ``REPEATS`` readings per measurement.
    monkeypatch.setattr(scaling, "SAMPLE_BUDGET_SECONDS", 0.0)
    # These tests script exactly ``REPEATS`` readings per measurement.
    monkeypatch.setattr(scaling, "SAMPLE_BUDGET_SECONDS", 0.0)


def _noop(_size: int) -> None:
    return None


class TestScalingRatioOnZeroReadings:
    """A clock that reads 0.0 CPU seconds for every run."""

    def test_all_zero_readings_do_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_clock(monkeypatch, lambda: 0.0)

        ratio = scaling.scaling_ratio(_noop, 10, "x" * 80)

        assert ratio == 0.0

    def test_zero_small_and_baseline_with_measurable_large_is_floored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only the large run advances the clock, by two ticks."""
        readings = iter([0.0, 0.0] * scaling.REPEATS + [0.0, 2 * _TICK] * scaling.REPEATS)
        readings_after = itertools.chain(readings, itertools.repeat(0.0))
        _install_clock(monkeypatch, lambda: next(readings_after))

        ratio = scaling.scaling_ratio(_noop, 10, "x" * 80)

        assert ratio == pytest.approx(2.0)
        assert ratio < scaling.SUPERLINEAR_RATIO

    def test_ratio_is_unchanged_when_denominator_is_measurable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Small costs 0.01s, the baseline 0.002s, large 0.16s: ratio is 16."""
        small_cost = 0.01
        large_cost = 0.16
        readings = iter(
            [0.0, small_cost] * scaling.REPEATS
            + [0.0, large_cost] * scaling.REPEATS
            + [0.0, 0.002] * scaling.REPEATS
        )
        _install_clock(monkeypatch, lambda: next(readings))

        ratio = scaling.scaling_ratio(_noop, 10, "x" * 80)

        assert ratio == pytest.approx(16.0)

    def test_baseline_still_floors_a_tiny_small_cost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A measurable baseline above the tick keeps its role as the floor."""
        readings = iter(
            [0.0, 0.001] * scaling.REPEATS
            + [0.0, 0.08] * scaling.REPEATS
            + [0.0, 0.01] * scaling.REPEATS
        )
        _install_clock(monkeypatch, lambda: next(readings), resolution=1e-6)

        ratio = scaling.scaling_ratio(_noop, 10, "x" * 80)

        assert ratio == pytest.approx(8.0)


class _CountedWork:
    """Work that counts its runs, on a clock whose successive runs cost ``costs``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, costs: list[float], budget: float) -> None:
        ticks = iter([t for cost in costs for t in (0.0, cost)])
        monkeypatch.setattr(scaling, "time", SimpleNamespace(thread_time=lambda: next(ticks, 0.0)))
        monkeypatch.setattr(scaling, "SAMPLE_BUDGET_SECONDS", budget)
        self.runs = 0

    def __call__(self) -> None:
        self.runs += 1


class TestMinCpuSecondsSampling:
    """Cheap work is sampled past ``REPEATS`` so one hiccup cannot set its cost."""

    def test_a_late_fast_run_is_found_beyond_the_first_repeats(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three slow runs (a hiccup) then a fast one: the minimum is the fast one."""
        costs = [0.005] * scaling.REPEATS + [0.0001] + [0.005] * 40
        work = _CountedWork(monkeypatch, costs, budget=0.05)

        assert scaling.min_cpu_seconds(work) == pytest.approx(0.0001)

    def test_expensive_work_stops_at_the_repeats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        work = _CountedWork(monkeypatch, [1.0] * 40, budget=0.02)

        scaling.min_cpu_seconds(work)

        assert work.runs == scaling.REPEATS

    def test_sampling_is_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        work = _CountedWork(monkeypatch, [0.0] * 100, budget=1.0)

        scaling.min_cpu_seconds(work)

        assert work.runs == scaling.MAX_REPEATS


class TestClockResolutionSeconds:
    """The measured granularity of the CPU clock the harness reads."""

    def test_reports_the_smallest_observed_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        steps = itertools.chain(
            [0.0, 0.0, _TICK / 2, _TICK / 2, _TICK / 2 + _TICK], itertools.repeat(2 * _TICK)
        )
        monkeypatch.setattr(
            scaling,
            "time",
            SimpleNamespace(
                thread_time=lambda: next(steps),
                perf_counter=time.perf_counter,
                clock_getres=lambda _clock: 1e-9,
                CLOCK_THREAD_CPUTIME_ID=3,
            ),
        )

        assert scaling.clock_resolution_seconds.__wrapped__() == pytest.approx(_TICK)

    def test_stuck_clock_falls_back_to_the_reported_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(scaling, "_RESOLUTION_PROBE_SECONDS", 0.01)
        monkeypatch.setattr(
            scaling,
            "time",
            SimpleNamespace(
                thread_time=lambda: 0.0,
                perf_counter=time.perf_counter,
                clock_getres=lambda _clock: 0.002,
                CLOCK_THREAD_CPUTIME_ID=3,
            ),
        )

        assert scaling.clock_resolution_seconds.__wrapped__() == pytest.approx(0.002)

    def test_stuck_clock_without_clock_getres_uses_the_constant_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(scaling, "_RESOLUTION_PROBE_SECONDS", 0.01)
        monkeypatch.setattr(
            scaling,
            "time",
            SimpleNamespace(thread_time=lambda: 0.0, perf_counter=time.perf_counter),
        )

        assert scaling.clock_resolution_seconds.__wrapped__() == scaling.FALLBACK_RESOLUTION_SECONDS

    def test_real_clock_resolution_is_positive(self) -> None:
        assert scaling.clock_resolution_seconds() > 0.0


class TestCountedRatio:
    def test_zero_count_does_not_raise(self) -> None:
        assert scaling.counted_ratio(lambda _n: 0, 5) == 0.0
