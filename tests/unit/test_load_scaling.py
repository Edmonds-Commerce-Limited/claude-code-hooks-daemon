"""Tests for ``tests.load_scaling``: the host-load multiplier for subprocess timeouts."""

from __future__ import annotations

import pytest

from tests import load_scaling
from tests.load_scaling import MAX_LOAD_FACTOR, load_factor, scaled_seconds


class TestLoadFactor:
    def test_an_idle_host_scales_by_one(self) -> None:
        assert load_factor(load_averages=(0.2, 0.3, 0.4), cpu_count=8) == 1.0

    def test_a_load_equal_to_the_cpu_count_scales_by_one(self) -> None:
        assert load_factor(load_averages=(8.0, 8.0, 8.0), cpu_count=8) == 1.0

    def test_an_oversubscribed_host_scales_by_the_oversubscription(self) -> None:
        assert load_factor(load_averages=(24.0, 10.0, 5.0), cpu_count=8) == pytest.approx(3.0)

    def test_the_slower_moving_average_counts_when_it_is_higher(self) -> None:
        # A spike that has just ended still leaves the host slow to schedule.
        assert load_factor(load_averages=(1.0, 16.0, 2.0), cpu_count=8) == pytest.approx(2.0)

    def test_the_fifteen_minute_average_is_ignored(self) -> None:
        assert load_factor(load_averages=(1.0, 1.0, 400.0), cpu_count=8) == 1.0

    def test_the_factor_is_capped(self) -> None:
        assert load_factor(load_averages=(5000.0, 5000.0, 5000.0), cpu_count=8) == MAX_LOAD_FACTOR

    def test_an_unknown_cpu_count_counts_as_one_cpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(load_scaling.os, "cpu_count", lambda: None)

        assert load_factor(load_averages=(3.0, 3.0, 3.0)) == pytest.approx(3.0)

    def test_the_host_is_read_when_nothing_is_passed(self) -> None:
        assert 1.0 <= load_factor() <= MAX_LOAD_FACTOR

    def test_a_host_without_load_averages_scales_by_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unsupported() -> tuple[float, float, float]:
            raise OSError("getloadavg is unavailable")

        monkeypatch.setattr(load_scaling.os, "getloadavg", unsupported)

        assert load_factor() == 1.0


class TestScaledSeconds:
    def test_the_base_is_a_floor(self) -> None:
        assert scaled_seconds(60, load_averages=(0.0, 0.0, 0.0), cpu_count=8) == 60

    def test_the_base_is_multiplied_by_the_factor(self) -> None:
        assert scaled_seconds(60, load_averages=(24.0, 24.0, 0.0), cpu_count=8) == pytest.approx(
            180
        )

    def test_the_result_never_exceeds_base_times_the_cap(self) -> None:
        got = scaled_seconds(60, load_averages=(1e6, 1e6, 1e6), cpu_count=1)
        assert got == 60 * MAX_LOAD_FACTOR

    def test_a_non_positive_base_is_refused(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            scaled_seconds(0)
