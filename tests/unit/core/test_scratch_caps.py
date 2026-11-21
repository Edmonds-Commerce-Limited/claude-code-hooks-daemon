"""Tests for the scratch cap evaluation (Plan 00627 DESIGN.md section 8, Task 5.3)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.config.models import ScratchCapsConfig
from claude_code_hooks_daemon.core.scratch_caps import (
    CapCounts,
    CapLevel,
    evaluate_caps,
)


def caps(**overrides: object) -> ScratchCapsConfig:
    base: dict[str, object] = {
        "directories": {"warn": 10, "block": 20},
        "bytes": {"warn": 100, "block": 200},
        "entries": {"warn": 3, "block": 5},
    }
    base.update(overrides)
    return ScratchCapsConfig.model_validate(base)


def counts(directories: int = 0, size: int = 0, entries: int = 0) -> CapCounts:
    return CapCounts(directories=directories, bytes=size, entries=entries)


class TestLevels:
    def test_under_every_warn_is_ok(self) -> None:
        report = evaluate_caps(counts(9, 99, 2), caps(), incomplete=False)
        assert report.level is CapLevel.OK
        assert report.at_or_above(CapLevel.WARN) == ()

    def test_reaching_warn_warns(self) -> None:
        report = evaluate_caps(counts(10, 0, 0), caps(), incomplete=False)
        assert report.level is CapLevel.WARN
        assert [c.key for c in report.at_or_above(CapLevel.WARN)] == ["directories"]

    def test_reaching_block_blocks_and_the_worst_key_decides(self) -> None:
        report = evaluate_caps(counts(10, 200, 0), caps(), incomplete=False)
        assert report.level is CapLevel.BLOCK
        assert {c.key: c.level for c in report.checks}["bytes"] is CapLevel.BLOCK

    def test_each_check_carries_its_figures(self) -> None:
        report = evaluate_caps(counts(entries=4), caps(), incomplete=False)
        check = {c.key: c for c in report.checks}["entries"]
        assert (check.count, check.warn, check.block, check.level) == (4, 3, 5, CapLevel.WARN)


class TestProjectDirectories:
    def test_not_evaluated_without_an_index_cap(self) -> None:
        report = evaluate_caps(counts(), caps(), incomplete=False)
        assert "project_directories" not in {c.key for c in report.checks}

    def test_percentages_of_the_index_cap(self) -> None:
        report = evaluate_caps(
            counts(), caps(), incomplete=False, index_directories=75, index_cap=100
        )
        check = {c.key: c for c in report.checks}["project_directories"]
        assert (check.warn, check.block, check.level) == (50, 75, CapLevel.BLOCK)


class TestIncompleteCanOnlyRaise:
    def test_an_incomplete_count_still_raises(self) -> None:
        report = evaluate_caps(counts(25), caps(), incomplete=True)
        assert report.level is CapLevel.BLOCK
        assert report.incomplete

    def test_an_incomplete_count_never_lowers_the_previous_level(self) -> None:
        report = evaluate_caps(counts(1), caps(), incomplete=True, previous=CapLevel.BLOCK)
        assert report.level is CapLevel.BLOCK

    def test_a_complete_count_may_lower_the_previous_level(self) -> None:
        report = evaluate_caps(counts(1), caps(), incomplete=False, previous=CapLevel.BLOCK)
        assert report.level is CapLevel.OK


class TestMode:
    def test_block_mode_enforces(self) -> None:
        assert evaluate_caps(counts(25), caps(), incomplete=False).enforce

    @pytest.mark.parametrize("mode", ["advise", "off"])
    def test_other_modes_never_enforce(self, mode: str) -> None:
        report = evaluate_caps(counts(25), caps(mode=mode), incomplete=False)
        assert not report.enforce

    def test_advise_keeps_the_level_for_the_report(self) -> None:
        assert evaluate_caps(counts(25), caps(mode="advise"), incomplete=False).level is (
            CapLevel.BLOCK
        )

    def test_off_reports_nothing(self) -> None:
        report = evaluate_caps(counts(25), caps(mode="off"), incomplete=True)
        assert report.level is CapLevel.OK
        assert report.checks == ()
