"""The per-year run ledger — Plan 00412 Task 2.3 (RED first).

D10's five run states are the spec, and the one that shapes this module is
``failed``: "started and did not finish". Nothing can WRITE that row — if a run
dies, whatever would have written it died too. So ``failed`` is DERIVED from a
start with no terminal event, which is why the ledger records one row per
EVENT rather than one row per run.

That also keeps the file genuinely append-only. A row-per-run ledger would have
to go back and edit the row when the run finished, and an append-only file that
is edited in place is just a file.

``no record`` stays outside this module for the same reason it stays outside
:mod:`routines.intervals`: a routine that never ran has nothing here to read,
and something that knows the routine EXISTS has to assert the absence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.routines.intervals import RunInterval
from claude_code_hooks_daemon.routines.ledger import (
    LedgerEvent,
    RunEvent,
    RunState,
    append_event,
    ledger_path,
    malformed_rows,
    next_run_id,
    read_events,
    run_states,
)

_NOW = datetime(2026, 9, 15, 20, 31, 0, tzinfo=UTC)
_LATER = datetime(2026, 9, 15, 21, 2, 0, tzinfo=UTC)


@pytest.fixture
def routine_dir(tmp_path: Path) -> Path:
    """A scaffolded routine folder with an empty ``RUNS/``."""
    target = tmp_path / "00001-security-review"
    (target / "RUNS").mkdir(parents=True)
    return target


class TestLedgerPath:
    """One file per year, named for the year and nothing else."""

    def test_is_named_for_the_year(self, routine_dir: Path) -> None:
        """A reader should be able to guess the filename from a date."""
        assert ledger_path(routine_dir, 2026).name == "2026.md"

    def test_lives_under_runs(self, routine_dir: Path) -> None:
        """``RUNS/`` is the only place a run record belongs."""
        assert ledger_path(routine_dir, 2026).parent == routine_dir / "RUNS"


class TestAppendEvent:
    """Appending never rewrites what is already there."""

    def test_creates_the_year_file_with_a_header(self, routine_dir: Path) -> None:
        """The first append seeds the table, so the file reads on its own."""
        append_event(
            routine_dir,
            RunEvent(run_id="2026-001", event=LedgerEvent.STARTED, at=_NOW),
        )

        body = ledger_path(routine_dir, 2026).read_text()
        assert "| run |" in body
        assert "2026-001" in body

    def test_appends_without_touching_earlier_rows(self, routine_dir: Path) -> None:
        """The whole point of the shape: earlier bytes are never rewritten."""
        append_event(
            routine_dir,
            RunEvent(run_id="2026-001", event=LedgerEvent.STARTED, at=_NOW),
        )
        first = ledger_path(routine_dir, 2026).read_text()

        append_event(
            routine_dir,
            RunEvent(
                run_id="2026-001",
                event=LedgerEvent.CLEAN,
                at=_LATER,
                interval=RunInterval(from_ref="abc123", to_ref="def456"),
            ),
        )
        second = ledger_path(routine_dir, 2026).read_text()

        assert second.startswith(first)

    def test_files_the_event_under_its_own_year(self, routine_dir: Path) -> None:
        """A run that straddles new year appends each event where it happened.

        Filing both under the start year would make the year file a poor index
        of itself; filing both under the end year would rewrite history.
        """
        append_event(
            routine_dir,
            RunEvent(run_id="2026-009", event=LedgerEvent.STARTED, at=_NOW),
        )
        append_event(
            routine_dir,
            RunEvent(
                run_id="2026-009",
                event=LedgerEvent.CLEAN,
                at=datetime(2027, 1, 2, 9, 0, tzinfo=UTC),
                interval=RunInterval(from_ref="abc123", to_ref="def456"),
            ),
        )

        assert ledger_path(routine_dir, 2026).is_file()
        assert ledger_path(routine_dir, 2027).is_file()

    def test_refuses_a_terminal_event_without_an_interval(self, routine_dir: Path) -> None:
        """A finished run with no interval covers nothing and composes wrongly.

        Refused where it is built rather than reasoned about downstream —
        an interval-less terminal row would silently break gap detection,
        which is the single property the whole design rests on.
        """
        with pytest.raises(ValueError, match="interval"):
            append_event(
                routine_dir,
                RunEvent(run_id="2026-001", event=LedgerEvent.CLEAN, at=_LATER),
            )

    def test_allows_a_skipped_event_without_an_interval(self, routine_dir: Path) -> None:
        """``skipped-with-reason`` covered nothing, honestly and on purpose."""
        append_event(
            routine_dir,
            RunEvent(
                run_id="2026-001",
                event=LedgerEvent.SKIPPED,
                at=_LATER,
                note="release freeze",
            ),
        )

        assert "skipped" in ledger_path(routine_dir, 2026).read_text()

    def test_refuses_a_skipped_event_with_no_reason(self, routine_dir: Path) -> None:
        """The reason IS the state. Without it this is an unexplained absence."""
        with pytest.raises(ValueError, match="reason"):
            append_event(
                routine_dir,
                RunEvent(run_id="2026-001", event=LedgerEvent.SKIPPED, at=_LATER),
            )


class TestReadEvents:
    """Reading back what was written, across years, in order."""

    def test_empty_runs_directory_reads_as_no_events(self, routine_dir: Path) -> None:
        """Never ran is not an error, and is not zero rows in one file."""
        assert read_events(routine_dir) == []

    def test_round_trips_an_event(self, routine_dir: Path) -> None:
        """Every field written is a field read back."""
        append_event(
            routine_dir,
            RunEvent(
                run_id="2026-001",
                event=LedgerEvent.FINDINGS,
                at=_LATER,
                interval=RunInterval(from_ref="abc123", to_ref="def456"),
                note="two findings, both filed as plans",
            ),
        )

        (event,) = read_events(routine_dir)
        assert event.run_id == "2026-001"
        assert event.event is LedgerEvent.FINDINGS
        assert event.at == _LATER
        assert event.interval == RunInterval(from_ref="abc123", to_ref="def456")
        assert event.note == "two findings, both filed as plans"

    def test_orders_across_year_files(self, routine_dir: Path) -> None:
        """Year files are read oldest first, not in directory order."""
        append_event(
            routine_dir,
            RunEvent(
                run_id="2027-001",
                event=LedgerEvent.STARTED,
                at=datetime(2027, 3, 1, tzinfo=UTC),
            ),
        )
        append_event(
            routine_dir,
            RunEvent(run_id="2026-001", event=LedgerEvent.STARTED, at=_NOW),
        )

        assert [event.run_id for event in read_events(routine_dir)] == [
            "2026-001",
            "2027-001",
        ]

    def test_tolerates_the_table_being_reformatted(self, routine_dir: Path) -> None:
        """Cell padding is not data.

        This project auto-aligns markdown tables on edit, so a ledger a human
        has opened comes back with different whitespace. A parser that treated
        that as corruption would fail on a file nobody meant to change.
        """
        append_event(
            routine_dir,
            RunEvent(
                run_id="2026-001",
                event=LedgerEvent.CLEAN,
                at=_LATER,
                interval=RunInterval(from_ref="abc123", to_ref="def456"),
            ),
        )
        path = ledger_path(routine_dir, 2026)
        path.write_text(path.read_text().replace("|", "   |   "))

        (event,) = read_events(routine_dir)
        assert event.run_id == "2026-001"


class TestMalformedRows:
    """A hand-edited ledger must be REPORTABLE, never fatal.

    The write-time guards refuse to create a terminal row with no interval,
    and they should. But nothing stops a human editing the file afterwards,
    and a reader that raises on what it finds takes the whole QA sweep with
    it — and a sweep that reports nothing looks exactly like a sweep that
    found nothing. Same reasoning as the ancestry oracle returning False for
    a ref git cannot resolve: surface it as a finding, not as a crash.
    """

    def _write_rows(self, routine_dir: Path, *rows: str) -> None:
        """Put a hand-authored ledger on disk, header included."""
        ledger_path(routine_dir, 2026).write_text(
            "| run | at | event | from | to | note |\n"
            "| --- | --- | --- | --- | --- | --- |\n" + "".join(f"{row}\n" for row in rows)
        )

    def test_reading_does_not_raise(self, routine_dir: Path) -> None:
        """The defect this class exists for: the reader used to explode."""
        self._write_rows(
            routine_dir, "| 2026-001 | 2026-09-15T20:00:00+00:00 | clean | - | - | - |"
        )

        assert read_events(routine_dir) == []

    def test_a_good_row_beside_a_bad_one_still_reads(self, routine_dir: Path) -> None:
        """One corrupt row must not erase the runs recorded around it."""
        self._write_rows(
            routine_dir,
            "| 2026-001 | 2026-09-15T20:00:00+00:00 | clean | - | - | - |",
            "| 2026-002 | 2026-09-15T21:00:00+00:00 | clean | abc123 | def456 | - |",
        )

        assert [event.run_id for event in read_events(routine_dir)] == ["2026-002"]

    def test_the_bad_row_is_reported(self, routine_dir: Path) -> None:
        """Skipping quietly would trade a crash for a silent omission."""
        self._write_rows(
            routine_dir, "| 2026-001 | 2026-09-15T20:00:00+00:00 | clean | - | - | - |"
        )

        (problem,) = malformed_rows(routine_dir)
        assert "2026.md" in problem
        assert "2026-001" in problem

    def test_an_unparseable_timestamp_is_reported(self, routine_dir: Path) -> None:
        """Not only the interval rule — anything that cannot become an event."""
        self._write_rows(routine_dir, "| 2026-001 | yesterday | started | - | - | - |")

        assert len(malformed_rows(routine_dir)) == 1
        assert read_events(routine_dir) == []

    def test_an_unknown_event_kind_is_reported(self, routine_dir: Path) -> None:
        """A row naming an outcome the vocabulary does not have."""
        self._write_rows(
            routine_dir, "| 2026-001 | 2026-09-15T20:00:00+00:00 | finished | - | - | - |"
        )

        assert len(malformed_rows(routine_dir)) == 1

    def test_a_healthy_ledger_reports_nothing(self, routine_dir: Path) -> None:
        """The check must be quiet when there is nothing wrong."""
        append_event(
            routine_dir,
            RunEvent(run_id="2026-001", event=LedgerEvent.STARTED, at=_NOW),
        )

        assert malformed_rows(routine_dir) == []


class TestRunStates:
    """D10's vocabulary, derived from the event stream."""

    def test_a_start_with_no_terminal_event_is_failed(self, routine_dir: Path) -> None:
        """The state nothing can write, which is why it is derived.

        If a run dies, whatever would have recorded the failure died with it.
        A ledger that only recorded what a run chose to say about itself could
        never report this, and an abandoned run would read as though it had
        never been attempted.
        """
        append_event(
            routine_dir,
            RunEvent(run_id="2026-001", event=LedgerEvent.STARTED, at=_NOW),
        )

        assert run_states(read_events(routine_dir)) == {"2026-001": RunState.FAILED}

    def test_a_started_then_clean_run_is_clean(self, routine_dir: Path) -> None:
        """The ordinary case: the terminal event wins."""
        append_event(
            routine_dir,
            RunEvent(run_id="2026-001", event=LedgerEvent.STARTED, at=_NOW),
        )
        append_event(
            routine_dir,
            RunEvent(
                run_id="2026-001",
                event=LedgerEvent.CLEAN,
                at=_LATER,
                interval=RunInterval(from_ref="abc123", to_ref="def456"),
            ),
        )

        assert run_states(read_events(routine_dir)) == {"2026-001": RunState.CLEAN}

    def test_clean_is_a_recorded_outcome_not_an_absence(self, routine_dir: Path) -> None:
        """A run that found nothing is as present as one that found something.

        The distinction the whole design turns on: ``clean`` and ``no record``
        must never be the same answer.
        """
        append_event(
            routine_dir,
            RunEvent(run_id="2026-001", event=LedgerEvent.STARTED, at=_NOW),
        )
        append_event(
            routine_dir,
            RunEvent(
                run_id="2026-001",
                event=LedgerEvent.CLEAN,
                at=_LATER,
                interval=RunInterval(from_ref="abc123", to_ref="def456"),
            ),
        )

        states = run_states(read_events(routine_dir))
        assert states["2026-001"] is RunState.CLEAN
        # The other half of the distinction, and the one a state map can get
        # wrong: a routine nobody ran must not acquire a state by default.
        assert "2026-002" not in states

    def test_no_events_yields_no_states(self, routine_dir: Path) -> None:
        """ "Never ran" is the absence of a key, never a state in the map."""
        assert run_states([]) == {}


class TestNextRunId:
    """Run ids are readable and ordered, not opaque."""

    def test_starts_at_one_for_a_fresh_year(self, routine_dir: Path) -> None:
        """A new year restarts the sequence, which the id's prefix disambiguates."""
        assert next_run_id(read_events(routine_dir), _NOW) == "2026-001"

    def test_counts_only_starts_in_the_same_year(self, routine_dir: Path) -> None:
        """A terminal event is not a second run, and last year's runs are not this year's."""
        append_event(
            routine_dir,
            RunEvent(run_id="2026-001", event=LedgerEvent.STARTED, at=_NOW),
        )
        append_event(
            routine_dir,
            RunEvent(
                run_id="2026-001",
                event=LedgerEvent.CLEAN,
                at=_LATER,
                interval=RunInterval(from_ref="abc123", to_ref="def456"),
            ),
        )

        assert next_run_id(read_events(routine_dir), _LATER) == "2026-002"
