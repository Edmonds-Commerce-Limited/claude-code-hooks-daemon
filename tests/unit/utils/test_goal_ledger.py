"""Tests for the daemon-side goal ledger (Plan 00276).

The ledger records every goal emission from ``goal_injection``, detects when
a new goal displaces a still-live one, and retires entries whose plan has
reached a terminal status or left the active plan directory. All reads and
writes are fail-open: a missing or corrupt ledger never raises.
"""

import json
import os
import threading
from pathlib import Path

import pytest

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

    def test_failed_write_never_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)

        real_os_open = os.open

        def _failing_tmp_open(path: str | Path, flags: int, mode: int = 0o777) -> int:
            # Fail only the private tmp-file open in _save; the sibling lock
            # file must keep working so the OSError branch (not the lock's
            # fail-open) is what this test exercises.
            if ".tmp" in str(path):
                raise OSError("disk full")
            return real_os_open(path, flags, mode)

        # All setup writes are done; every subsequent tmp write fails, so the
        # OSError branch in _save must be exercised and swallowed (logged).
        monkeypatch.setattr(os, "open", _failing_tmp_open)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        assert not (tmp_path / LEDGER_FILENAME).exists()

    def test_nonexistent_plan_dir_never_retires(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        # A misresolved/nonexistent plan dir must NOT retire the entry —
        # retirement is persisted, so a wrong path would wipe the ledger.
        wrong_dir = tmp_path / "not" / "a" / "plan" / "dir"
        assert ledger.live_plan_numbers(wrong_dir) == []
        assert ledger.entries()[0].retired_at is None
        # The entry is still live against the real plan dir.
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A]


class TestLivePlanRefs:
    """Plan 00299: resolved (folder, PLAN.md text) per live plan, for the
    combined-goal renderer."""

    def test_resolves_folder_and_text_for_each_live_plan(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        refs = ledger.live_plan_refs(plan_dir)
        assert [r.plan_number for r in refs] == [_PLAN_A, _PLAN_B]
        assert refs[0].plan_folder == f"{_PLAN_A}-example-plan"
        assert f"**Status**: {_STATUS_IN_PROGRESS}" in refs[0].plan_text

    def test_excludes_terminal_plans(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        _make_plan(plan_dir, _PLAN_B, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        ledger.record_emission(_SESSION, _PLAN_B, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            f"# Plan {_PLAN_A}: example plan\n\n**Status**: Complete\n", encoding="utf-8"
        )
        refs = ledger.live_plan_refs(plan_dir)
        assert [r.plan_number for r in refs] == [_PLAN_B]

    def test_empty_ledger_yields_no_refs(self, tmp_path: Path) -> None:
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        assert ledger.live_plan_refs(tmp_path / "CLAUDE" / "Plan") == []


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


class TestStatusParsing:
    """The ledger delegates to PlanDoc.parse — the tested plan-QA parser."""

    def test_terminal_status_with_date_qualifier_retires(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text("**Status**: Complete (2026-05-01)\n", encoding="utf-8")
        assert ledger.live_plan_numbers(plan_dir) == []

    def test_in_progress_with_trailing_icon_stays_live(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text("**Status**: In Progress 🔄\n", encoding="utf-8")
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A]

    def test_status_line_inside_fenced_block_is_ignored(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        folder = _make_plan(plan_dir, _PLAN_A, _STATUS_IN_PROGRESS)
        ledger = GoalLedger(tmp_path / LEDGER_FILENAME)
        ledger.record_emission(_SESSION, _PLAN_A, _GOAL_LINE, plan_dir)
        (folder / "PLAN.md").write_text(
            "**Status**: In Progress\n\n" "```markdown\n**Status**: Complete\n```\n",
            encoding="utf-8",
        )
        # The fenced Complete must not falsely retire the plan.
        assert ledger.live_plan_numbers(plan_dir) == [_PLAN_A]
        assert ledger.entries()[0].retired_at is None


class TestConcurrentWriters:
    def test_concurrent_emissions_all_recorded(self, tmp_path: Path) -> None:
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        ledger_path = tmp_path / LEDGER_FILENAME
        total = 20
        numbers = [f"{70000 + i:05d}" for i in range(total)]
        for number in numbers:
            _make_plan(plan_dir, number, _STATUS_IN_PROGRESS)

        errors: list[BaseException] = []

        def _emit(number: str) -> None:
            try:
                GoalLedger(ledger_path).record_emission(_SESSION, number, _GOAL_LINE, plan_dir)
            except BaseException as exc:  # capture for the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=_emit, args=(n,)) for n in numbers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        recorded = {e.plan_number for e in GoalLedger(ledger_path).entries()}
        # The flock around each read-modify-write means no emission is lost.
        assert recorded == set(numbers)
