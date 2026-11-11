"""Tests for the host-load scaling of subprocess budgets."""

from __future__ import annotations

import os

import pytest

from claude_code_hooks_daemon.utils.load_scaling import (
    describe_load,
    load_factor,
    scaled_timeout,
)


class TestLoadFactor:
    def test_idle_host_is_one(self) -> None:
        assert load_factor(load_averages=(0.5, 0.5, 0.5), cpu_count=8) == 1.0

    def test_oversubscribed_host_scales_by_load_per_cpu(self) -> None:
        assert load_factor(load_averages=(24.0, 1.0, 1.0), cpu_count=8) == pytest.approx(3.0)

    def test_the_five_minute_average_counts_when_higher(self) -> None:
        assert load_factor(load_averages=(1.0, 16.0, 1.0), cpu_count=8) == pytest.approx(2.0)

    def test_fifteen_minute_average_is_ignored(self) -> None:
        assert load_factor(load_averages=(1.0, 1.0, 900.0), cpu_count=8) == 1.0

    def test_unknown_cpu_count_is_one_cpu(self) -> None:
        assert load_factor(load_averages=(3.0, 0.0, 0.0), cpu_count=None) >= 1.0

    def test_unreadable_load_counts_as_idle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken() -> tuple[float, float, float]:
            raise OSError("no loadavg")

        monkeypatch.setattr(os, "getloadavg", broken)
        assert load_factor() == 1.0


class TestScaledTimeout:
    def test_idle_host_gets_the_base(self) -> None:
        assert scaled_timeout(30, 120, load_averages=(1.0, 1.0, 1.0), cpu_count=8) == 30

    def test_load_lengthens_the_base(self) -> None:
        assert scaled_timeout(30, 120, load_averages=(16.0, 1.0, 1.0), cpu_count=8) == 60

    def test_the_ceiling_bounds_the_result(self) -> None:
        assert scaled_timeout(30, 120, load_averages=(700.0, 700.0, 700.0), cpu_count=8) == 120

    def test_a_ceiling_below_the_base_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="ceiling"):
            scaled_timeout(30, 10)

    def test_a_non_positive_base_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="base"):
            scaled_timeout(0, 10)


class TestDescribeLoad:
    def test_names_the_averages_and_cpus(self) -> None:
        text = describe_load(load_averages=(70.1, 40.0, 20.0), cpu_count=8)
        assert "70.1" in text
        assert "8 CPUs" in text

    def test_unreadable_load_is_said_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken() -> tuple[float, float, float]:
            raise OSError("no loadavg")

        monkeypatch.setattr(os, "getloadavg", broken)
        assert "unavailable" in describe_load()
