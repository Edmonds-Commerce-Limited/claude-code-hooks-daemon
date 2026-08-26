"""Tests for the daemon-side goal ledger (Plan 00276).

The ledger records every goal emission from ``goal_injection``, detects when
a new goal displaces a still-live one, and retires entries whose plan has
reached a terminal status or left the active plan directory. All reads and
writes are fail-open: a missing or corrupt ledger never raises.
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.utils.goal_ledger import (
    LEDGER_FILENAME,
    GoalLedger,
)

_SESSION = "sess-1"
_OTHER_SESSION = "sess-2"
_PLAN_A = "00274"
_PLAN_B = "00275"
_GOAL_LINE = "work on the plan"

_STATUS_IN_PROGRESS = "In Progress"
_STATUS_COMPLETE = "Complete"


def _make_plan(plan_dir: Path, number: str, status: str) -> Path:
    folder = plan_dir / f"{number}-example-plan"
    folder.mkdir(parents=True, exist_ok=True)
    plan_md = folder / "PLAN.md"
    plan_md.write_text(
        f"# Plan {number}: example plan\n\n**Status**: {status}\n",
        encoding="utf-8",
    )
    return folder


class TestRecordEmission:
    def test_first_emission_records_entry_and_displaces_nothing(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        displaced = ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        assert displaced == []
        entries = ledger.entries()
        assert len(entries) == 1
        assert entries[0].plan_number == _PLAN_A
        assert entries[0].session_id == _SESSION
        assert entries[0].rendered_line == _GOAL_LINE
        assert entries[0].displaced_by is None
        assert entries[0].retired_at is None

    def test_second_plan_displaces_live_first(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        displaced = ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        assert displaced == [_PLAN_A]
        entry_a = next(e for e in ledger.entries() if e.plan_number == _PLAN_A)
        assert entry_a.displaced_by == _PLAN_B
        assert entry_a.displaced_at is not None

    def test_re_emission_same_plan_does_not_self_displace(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        displaced = ledger.record_emission(_OTHER_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        assert displaced == []
        # Re-fire refreshes the live entry rather than double-counting it.
        live = [e for e in ledger.entries() if e.plan_number == _PLAN_A and e.retired_at is None]
        assert len(live) == 1
        assert live[0].session_id == _OTHER_SESSION

    def test_completed_prior_plan_is_not_reported_as_displaced(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_COMPLETE)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        displaced = ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        assert displaced == []


class TestLivePlanNumbers:
    def test_lists_in_progress_ledgered_plans(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A, _PLAN_B]

    def test_displaced_but_in_progress_plan_stays_live(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        assert _PLAN_A in ledger.live_plan_numbers(plan_dir)

    def test_terminal_status_retires_entry(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        assert ledger.live_plan_numbers(plan_dir) == []
        entry = ledger.entries()[0]
        assert entry.retired_at is not None
        assert entry.retired_reason is not None

    def test_archive_move_retires_entry(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        archive = plan_dir / "Completed"
        archive.mkdir(parents=True, exist_ok=True)
        folder.rename(archive / folder.name)
        assert ledger.live_plan_numbers(plan_dir) == []
        assert ledger.entries()[0].retired_at is not None

    def test_retirement_persists_to_disk(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger_path = tmp_path / LEDGER_FILENAME
        GoalLedger(ledger_path).record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text("**Status**: Cancelled\n", encoding="utf-8")
        GoalLedger(ledger_path).live_plan_numbers(plan_dir)
        # A fresh instance sees the persisted retirement.
        fresh = GoalLedger(ledger_path)
        assert fresh.live_plan_numbers(plan_dir) == []
        assert fresh.entries()[0].retired_at is not None


class TestFailOpen:
    def test_missing_ledger_yields_no_live_plans(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        assert ledger.live_plan_numbers(tmp_path / "CLAUDE" / "Plan") == []
        assert ledger.entries() == []

    def test_corrupt_ledger_is_tolerated(self, tmp_path: Path) -> None:
        ledger_path = tmp_path / LEDGER_FILENAME
        ledger_path.write_text("{not json", encoding="utf-8")
        ledger = GoalLedger(ledger_path)
        assert ledger.entries() == []
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        # Recording over a corrupt file starts a fresh ledger.
        assert ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir) == []
        assert GoalLedger(ledger_path).entries()[0].plan_number == _PLAN_A

    def test_unwritable_directory_never_raises(self, tmp_path: Path) -> None:
        missing_parent = tmp_path / "no" / "such" / "dir"
        ledger = GoalLedger(missing_parent / LEDGER_FILENAME)
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        # Parent dirs are created on demand; this must simply not raise.
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)


class TestBoundedGrowth:
    def test_retired_entries_are_pruned_beyond_cap(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        ledger_path = tmp_path / LEDGER_FILENAME
        ledger = GoalLedger(ledger_path)
        # Emit far more plans than the cap, each immediately Complete.
        total = 150
        for i in range(total):
            number = f"{60000 + i:05d}"
            _make_plan(plan_dir, number, _STATUS_COMPLETE)
            ledger.record_emission(_SESSION, number, _GOAL_LINE, plan_dir)
        ledger.live_plan_numbers(plan_dir)
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert len(raw["entries"]) <= 100
