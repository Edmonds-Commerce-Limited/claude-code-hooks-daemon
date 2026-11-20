"""Tests for the shared "did the walk finish" result type (Plan 00623)."""

from __future__ import annotations

import dataclasses

import pytest

from claude_code_hooks_daemon.utils.bounded_walk import Bounded, finished, stopped
from claude_code_hooks_daemon.utils.resolution_failure import (
    IncompleteScanError,
    ResolutionFailedError,
)


class TestFinished:
    def test_a_finished_walk_is_complete_with_no_reason(self) -> None:
        result = finished([1, 2])
        assert result.complete
        assert result.value == [1, 2]
        assert result.reason == ""

    def test_required_returns_the_value(self) -> None:
        assert finished("x").required() == "x"


class TestStopped:
    def test_a_stopped_walk_keeps_what_it_found_and_why(self) -> None:
        result = stopped(["a"], "past the cap")
        assert not result.complete
        assert result.value == ["a"]
        assert result.reason == "past the cap"

    def test_required_raises_an_incomplete_scan_error_naming_the_reason(self) -> None:
        with pytest.raises(IncompleteScanError, match="past the cap"):
            stopped([], "past the cap").required()

    def test_the_raise_is_a_resolution_failure_so_every_guard_denies_it(self) -> None:
        with pytest.raises(ResolutionFailedError):
            stopped(None, "deadline").required()

    def test_a_stop_needs_a_reason(self) -> None:
        with pytest.raises(ValueError):
            stopped([], "")


class TestBoundedIsAValue:
    def test_it_is_frozen(self) -> None:
        result = finished(1)
        field_name = "complete"
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(result, field_name, False)

    def test_a_finished_result_cannot_carry_a_reason(self) -> None:
        with pytest.raises(ValueError):
            Bounded(value=1, complete=True, reason="why")

    def test_a_stopped_result_built_directly_needs_a_reason(self) -> None:
        with pytest.raises(ValueError):
            Bounded(value=1, complete=False, reason="")
