"""The routine QA sweep — Plan 00412 Task 2.4 (RED first).

Five checks, and every one exists because the failure it catches is SILENT.
That is the through-line: a recurring obligation that stops being met produces
no error, no failing test and no diff — just an absence, and an absence looks
exactly like everything being fine.

- ``routine-never-run`` — the dead-man's switch: nothing on record has covered
  anything. No record at all is not a state (D6), so something outside the
  records must notice — and neither is a pile of records that reviewed nothing.
- ``routine-overdue`` — period PLUS grace (D11), never period alone, measured
  from the last run that COVERED ground rather than the last row written.
- ``routine-run-gap`` — the interval algebra's whole purpose: commits nobody
  covered, found by arithmetic rather than judgement.
- ``routine-ledger-unreadable`` — a hand-edited row that cannot be read. Skip
  it quietly and a run vanishes from the coverage chain with nothing said.
- ``routine-not-configured`` — a scaffolded routine nobody finished declaring.
  Not one of the original four, and added because without it a typo in the
  Status or Trigger line silently removes a routine from every other check
  here. A check that a typo can switch off is worse than no check.

A retired routine is not overdue and never will be. Skipping it is not
leniency — reporting it for ever is how a sweep trains its reader to ignore it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.routines.intervals import Ancestry, RunInterval
from claude_code_hooks_daemon.routines.ledger import (
    LedgerEvent,
    RunEvent,
    append_event,
    ledger_path,
)
from claude_code_hooks_daemon.routines.qa import sweep

_TODAY = date(2026, 9, 15)


class _ListAncestry:
    """Ancestry over a known ordering, so tests need no git."""

    def __init__(self, order: list[str]) -> None:
        self._order = order

    def is_ancestor(self, earlier: str, later: str) -> bool:
        """True when ``earlier`` sits at or before ``later`` in the ordering."""
        if earlier not in self._order or later not in self._order:
            return False
        return self._order.index(earlier) <= self._order.index(later)


def _routine(
    project_root: Path,
    name: str = "00001-security-review",
    *,
    status: str = "Active",
    trigger: str = "schedule",
    period: str = "30 days",
    grace: str | None = "7 days",
) -> Path:
    """A routine folder with a declared header and an empty ``RUNS/``."""
    folder = project_root / "CLAUDE" / "Routine" / name
    (folder / "RUNS").mkdir(parents=True)
    lines = [f"# Routine {name}", "", f"**Status**: {status}", f"**Trigger**: {trigger}"]
    if period:
        lines.append(f"**Period**: {period}")
    if grace is not None:
        lines.append(f"**Grace**: {grace}")
    lines += ["", "## Procedure", "", "1. Review."]
    (folder / "ROUTINE.md").write_text("\n".join(lines) + "\n")
    return folder


def _completed_run(folder: Path, run_id: str, at: datetime, from_ref: str, to_ref: str) -> None:
    """Append a started/clean pair covering ``from_ref -> to_ref``."""
    append_event(folder, RunEvent(run_id=run_id, event=LedgerEvent.STARTED, at=at))
    append_event(
        folder,
        RunEvent(
            run_id=run_id,
            event=LedgerEvent.CLEAN,
            at=at,
            interval=RunInterval(from_ref=from_ref, to_ref=to_ref),
        ),
    )


def _skipped_run(folder: Path, run_id: str, at: datetime, reason: str) -> None:
    """Append a started/skipped pair, which covers nothing by definition."""
    append_event(folder, RunEvent(run_id=run_id, event=LedgerEvent.STARTED, at=at))
    append_event(
        folder,
        RunEvent(run_id=run_id, event=LedgerEvent.SKIPPED, at=at, note=reason),
    )


def _ids(project_root: Path, ancestry: Ancestry | None = None) -> list[str]:
    """The check ids the sweep reports, for terse assertions."""
    return sorted(
        finding.check_id for finding in sweep(project_root, today=_TODAY, ancestry=ancestry)
    )


class TestNeverRun:
    """Absence of a record is not observable from the records themselves."""

    def test_a_routine_with_no_runs_is_reported(self, tmp_path: Path) -> None:
        """D6's dead-man's switch: something outside the records must say so."""
        _routine(tmp_path)

        assert "routine-never-run" in _ids(tmp_path)

    def test_a_routine_with_a_run_is_not(self, tmp_path: Path) -> None:
        """The check must go quiet the moment it is satisfied."""
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 9, 14, tzinfo=UTC), "a", "b")

        assert "routine-never-run" not in _ids(tmp_path)

    def test_a_retired_routine_is_not_reported(self, tmp_path: Path) -> None:
        """Retired means the obligation ended, not that it is being shirked."""
        _routine(tmp_path, status="Retired")

        assert "routine-never-run" not in _ids(tmp_path)


class TestOverdue:
    """D11: period plus grace, so a monthly cadence does not nag on day 31."""

    def test_within_the_period_is_quiet(self, tmp_path: Path) -> None:
        """The healthy case reports nothing at all."""
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 9, 10, tzinfo=UTC), "a", "b")

        assert "routine-overdue" not in _ids(tmp_path)

    def test_inside_the_grace_window_is_quiet(self, tmp_path: Path) -> None:
        """Day 33 of a 30-day cadence is not yet a problem — that IS the grace.

        Without it the sweep cries wolf every single period, and a reader who
        has learned to ignore it will ignore the real one too.
        """
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 8, 13, tzinfo=UTC), "a", "b")

        assert "routine-overdue" not in _ids(tmp_path)

    def test_past_period_plus_grace_is_reported(self, tmp_path: Path) -> None:
        """Beyond the grace it is genuinely overdue, and must be loud."""
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 7, 1, tzinfo=UTC), "a", "b")

        assert "routine-overdue" in _ids(tmp_path)

    def test_a_session_start_routine_is_never_overdue(self, tmp_path: Path) -> None:
        """Not everything is on a clock (D9), so not everything can be late."""
        folder = _routine(tmp_path, trigger="session_start", period="", grace=None)
        _completed_run(folder, "2026-001", datetime(2025, 1, 1, tzinfo=UTC), "a", "b")

        assert "routine-overdue" not in _ids(tmp_path)

    def test_a_retired_routine_is_never_overdue(self, tmp_path: Path) -> None:
        """Otherwise every retired routine reports for ever."""
        folder = _routine(tmp_path, status="Retired")
        _completed_run(folder, "2026-001", datetime(2025, 1, 1, tzinfo=UTC), "a", "b")

        assert "routine-overdue" not in _ids(tmp_path)

    def test_an_unfinished_run_does_not_count_as_coverage(self, tmp_path: Path) -> None:
        """A run that started and never finished proves nothing was reviewed.

        Counting the START would let an abandoned run reset the clock — the
        pointer bug again: the obligation reads as met because someone began,
        not because anything was looked at.
        """
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-000", datetime(2026, 7, 1, tzinfo=UTC), "a", "b")
        append_event(
            folder,
            RunEvent(
                run_id="2026-001",
                event=LedgerEvent.STARTED,
                at=datetime(2026, 9, 14, tzinfo=UTC),
            ),
        )

        assert "routine-overdue" in _ids(tmp_path)


class TestGap:
    """Commits nobody covered, found by arithmetic rather than judgement."""

    def test_meeting_runs_are_quiet(self, tmp_path: Path) -> None:
        """Consecutive coverage composes cleanly and reports nothing."""
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 9, 1, tzinfo=UTC), "a", "b")
        _completed_run(folder, "2026-002", datetime(2026, 9, 14, tzinfo=UTC), "b", "c")

        assert "routine-run-gap" not in _ids(tmp_path, _ListAncestry(["a", "b", "c"]))

    def test_a_gap_is_reported(self, tmp_path: Path) -> None:
        """The finding the whole interval model exists to make visible."""
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 9, 1, tzinfo=UTC), "a", "b")
        _completed_run(folder, "2026-002", datetime(2026, 9, 14, tzinfo=UTC), "c", "d")

        assert "routine-run-gap" in _ids(tmp_path, _ListAncestry(["a", "b", "c", "d"]))

    def test_a_skipped_run_widens_rather_than_holing(self, tmp_path: Path) -> None:
        """D5: a missed run widens the next interval; it never leaves a hole."""
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 9, 1, tzinfo=UTC), "a", "b")
        _completed_run(folder, "2026-003", datetime(2026, 9, 14, tzinfo=UTC), "b", "z")

        assert "routine-run-gap" not in _ids(tmp_path, _ListAncestry(["a", "b", "z"]))

    def test_a_single_run_cannot_gap(self, tmp_path: Path) -> None:
        """Nothing to compose against, so nothing to report."""
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 9, 14, tzinfo=UTC), "a", "b")

        assert "routine-run-gap" not in _ids(tmp_path, _ListAncestry(["a", "b"]))


class TestUnreadableLedger:
    """A hand-edited row surfaces as a finding, never as a crash or a silence."""

    def test_a_bad_row_is_reported(self, tmp_path: Path) -> None:
        """Skipping it quietly loses a run from the chain with nothing said."""
        folder = _routine(tmp_path)
        ledger_path(folder, 2026).write_text(
            "| run | at | event | from | to | note |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 2026-001 | 2026-09-14T10:00:00+00:00 | clean | - | - | - |\n"
        )

        assert "routine-ledger-unreadable" in _ids(tmp_path)

    def test_the_sweep_survives_it(self, tmp_path: Path) -> None:
        """A sweep that raises reports nothing, which looks like success."""
        folder = _routine(tmp_path)
        ledger_path(folder, 2026).write_text(
            "| run | at | event | from | to | note |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 2026-001 | not-a-date | started | - | - | - |\n"
        )

        assert "routine-ledger-unreadable" in _ids(tmp_path)


class TestNotConfigured:
    """A check that a typo can switch off is worse than no check."""

    def test_a_scaffolded_routine_is_reported(self, tmp_path: Path) -> None:
        """Placeholders parse as 'not declared', which is the honest reading."""
        _routine(tmp_path, trigger="<!-- schedule | session_start -->", period="")

        assert "routine-not-configured" in _ids(tmp_path)

    def test_a_typo_in_status_is_reported(self, tmp_path: Path) -> None:
        """Without this, a misspelt Status silently exempts the routine.

        Every other check consults status, so an unrecognised one would remove
        the routine from all of them — a check disabled by a typo, which is
        exactly the silent failure this sweep exists to prevent.
        """
        _routine(tmp_path, status="Activ")

        assert "routine-not-configured" in _ids(tmp_path)

    def test_a_declared_routine_is_quiet(self, tmp_path: Path) -> None:
        """A fully declared routine must not be nagged about its header."""
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 9, 14, tzinfo=UTC), "a", "b")

        assert "routine-not-configured" not in _ids(tmp_path)

    def test_a_release_trigger_is_declared_not_unknown(self, tmp_path: Path) -> None:
        """Plan 00412 Task 3.1: a per-release sweep is a declared trigger.

        Left out of the closed set it parses as UNKNOWN, and the routine drops
        out of every other check here while still looking configured to a
        reader — so the value has to exist before the routine can.
        """
        folder = _routine(tmp_path, trigger="release", period="", grace=None)
        _completed_run(folder, "2026-001", datetime(2026, 9, 14, tzinfo=UTC), "a", "b")

        assert "routine-not-configured" not in _ids(tmp_path)

    def test_a_release_routine_is_never_overdue_by_the_clock(self, tmp_path: Path) -> None:
        """Its backstop is the full sweep beside it, not a calendar (D5)."""
        folder = _routine(tmp_path, trigger="release", period="30 days", grace="1 days")
        _completed_run(folder, "2026-001", datetime(2025, 1, 1, tzinfo=UTC), "a", "b")

        assert "routine-overdue" not in _ids(tmp_path)


class TestNonCoverageIsNotCoverage:
    """A record saying nothing was reviewed must never read as a review.

    ``skipped`` and an unfinished ``started`` are both records of NON-coverage:
    the ledger states that exist precisely so an absence can be written down.
    Counting either as coverage re-creates the mutable pointer this whole design
    replaced — the obligation reads as met because something was WRITTEN, not
    because anything was looked at.

    The gap check already honours this (a skip leaves no hole, D5). These pin the
    other two consumers, which did not.
    """

    def test_a_skip_does_not_reset_the_overdue_clock(self, tmp_path: Path) -> None:
        """Otherwise a routine can be skipped for ever and never report late.

        The failure is the quiet one: each skip buys another period plus grace
        of silence, so a routine nobody ever performs reads exactly like one
        performed on time.
        """
        folder = _routine(tmp_path)
        _completed_run(folder, "2026-001", datetime(2026, 7, 1, tzinfo=UTC), "a", "b")
        _skipped_run(folder, "2026-002", datetime(2026, 9, 14, tzinfo=UTC), "release frozen")

        assert "routine-overdue" in _ids(tmp_path)

    def test_a_routine_that_has_only_ever_been_skipped_is_reported(self, tmp_path: Path) -> None:
        """The hole between two checks: records exist, coverage does not.

        ``routine-never-run`` asks whether there are records and ``routine-overdue``
        asks how long since one — so a routine whose only records are skips
        answers yes to the first and gives the second no baseline, and both go
        quiet about an obligation that has never once been met.
        """
        folder = _routine(tmp_path)
        _skipped_run(folder, "2026-001", datetime(2026, 9, 14, tzinfo=UTC), "release frozen")

        assert _ids(tmp_path) != []

    def test_a_routine_with_only_an_unfinished_start_is_reported(self, tmp_path: Path) -> None:
        """The same hole reached by the other non-coverage state.

        ``test_an_unfinished_run_does_not_count_as_coverage`` proves a start does
        not reset the clock, but only because a completed run before it supplies
        the baseline. With no such run there is no baseline, and the start is the
        only record — so nothing reports at all.
        """
        folder = _routine(tmp_path)
        append_event(
            folder,
            RunEvent(
                run_id="2026-001", event=LedgerEvent.STARTED, at=datetime(2026, 9, 14, tzinfo=UTC)
            ),
        )

        assert _ids(tmp_path) != []

    def test_a_retired_routine_with_only_skips_stays_quiet(self, tmp_path: Path) -> None:
        """Retired means the obligation ended — reporting it for ever is noise."""
        folder = _routine(tmp_path, status="Retired")
        _skipped_run(folder, "2026-001", datetime(2026, 9, 14, tzinfo=UTC), "retired mid-cycle")

        assert _ids(tmp_path) == []


class TestSweepShape:
    """The sweep itself."""

    def test_no_tree_reports_nothing(self, tmp_path: Path) -> None:
        """A project with no routines has no obligations to be failing."""
        assert sweep(tmp_path, today=_TODAY) == []

    def test_findings_name_their_routine(self, tmp_path: Path) -> None:
        """A finding that cannot be traced to a routine is not actionable."""
        _routine(tmp_path)

        findings = sweep(tmp_path, today=_TODAY)
        assert findings
        assert all(finding.routine == "00001-security-review" for finding in findings)

    def test_every_finding_carries_a_remediation(self, tmp_path: Path) -> None:
        """Naming the problem without the fix is how a sweep gets ignored."""
        _routine(tmp_path)

        findings = sweep(tmp_path, today=_TODAY)
        assert findings
        assert all(finding.remediation.strip() for finding in findings)

    def test_ancestry_is_optional(self, tmp_path: Path) -> None:
        """A caller with no git still gets every check that needs no oracle."""
        _routine(tmp_path)

        assert "routine-never-run" in _ids(tmp_path)


def test_list_ancestry_is_a_valid_oracle() -> None:
    """The test double really does satisfy the protocol it stands in for."""
    ancestry: Ancestry = _ListAncestry(["a", "b"])

    assert ancestry.is_ancestor("a", "b") is True
    assert ancestry.is_ancestor("b", "a") is False


@pytest.mark.parametrize("status", ["Active", "active", "ACTIVE"])
def test_status_is_case_insensitive(tmp_path: Path, status: str) -> None:
    """Humans write headers, and a capital letter is not a configuration error."""
    _routine(tmp_path, status=status)

    assert "routine-not-configured" not in _ids(tmp_path)
