"""Parsing a ROUTINE.md header — Plan 00412 Task 2.4 (RED first).

The QA checks need three facts a routine states about itself: whether it is
still active, what triggers it, and — for a scheduled one — how often, so
"overdue" can mean something.

**Period alone is not enough** (D11). A monthly routine with no grace is
overdue on day 31, every month, for ever; the nag arrives reliably and is
reliably ignored, which is how a recurring obligation stops being one. So the
header carries a grace as well, and an undeclared grace gets a default rather
than zero — zero is the value that produces the failure D11 names.

Trigger kinds are a closed set, deliberately. A free-text cadence would have to
be interpreted, and a misread cadence produces an overdue date that is wrong
without being detectably wrong.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.routines.model import (
    RoutineDoc,
    RoutineStatus,
    Trigger,
    parse_routine,
)


def _write(tmp_path: Path, body: str) -> Path:
    """A routine folder whose ROUTINE.md holds ``body``."""
    routine = tmp_path / "00001-security-review"
    routine.mkdir()
    (routine / "ROUTINE.md").write_text(body)
    return routine


_SCHEDULED = """# Routine 00001: security review

**Status**: Active
**Trigger**: schedule
**Period**: 30 days
**Grace**: 7 days

## Procedure

1. Review.
"""


class TestParsing:
    """The three facts a routine states about itself."""

    def test_reads_status(self, tmp_path: Path) -> None:
        """A retired routine must not be reported as overdue for ever."""
        doc = parse_routine(_write(tmp_path, _SCHEDULED))

        assert doc.status is RoutineStatus.ACTIVE

    def test_reads_trigger_and_period(self, tmp_path: Path) -> None:
        """Period is what makes 'overdue' computable at all."""
        doc = parse_routine(_write(tmp_path, _SCHEDULED))

        assert doc.trigger is Trigger.SCHEDULE
        assert doc.period_days == 30
        assert doc.grace_days == 7

    def test_reads_a_session_start_trigger(self, tmp_path: Path) -> None:
        """Not every routine is on a clock — D9's first-class second trigger."""
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00002: docs sweep\n\n"
                "**Status**: Active\n**Trigger**: session_start\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.trigger is Trigger.SESSION_START
        assert doc.period_days is None

    def test_reads_a_retired_routine(self, tmp_path: Path) -> None:
        """Retired is a real state, and the reason overdue must consult status."""
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00003: old\n\n**Status**: Retired\n"
                "**Trigger**: schedule\n**Period**: 30 days\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.status is RoutineStatus.RETIRED


class TestGraceDefault:
    """D11: grace is what stops a monthly cadence nagging on day 31."""

    def test_defaults_when_undeclared(self, tmp_path: Path) -> None:
        """An undeclared grace is a fifth of the period, never zero.

        Zero is the value that produces exactly the failure D11 names, so it
        is the one thing an omission must not mean. A fifth is a CHOSEN
        default, not a derived one — it is overridable precisely because it is
        a judgement rather than a fact.
        """
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00001: r\n\n**Status**: Active\n"
                "**Trigger**: schedule\n**Period**: 30 days\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.grace_days == 6

    def test_a_short_period_still_gets_a_day(self, tmp_path: Path) -> None:
        """Integer division must not quietly reintroduce a zero grace."""
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00001: r\n\n**Status**: Active\n"
                "**Trigger**: schedule\n**Period**: 2 days\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.grace_days == 1

    def test_an_explicit_zero_grace_is_honoured(self, tmp_path: Path) -> None:
        """A declared zero is a decision; only an OMISSION gets the default."""
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00001: r\n\n**Status**: Active\n**Trigger**: schedule\n"
                "**Period**: 30 days\n**Grace**: 0 days\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.grace_days == 0


class TestDueAfter:
    """When a scheduled routine becomes overdue."""

    def test_is_period_plus_grace(self, tmp_path: Path) -> None:
        """Both, never just the period."""
        doc = parse_routine(_write(tmp_path, _SCHEDULED))

        assert doc.due_after_days == 37

    def test_is_none_without_a_schedule(self, tmp_path: Path) -> None:
        """A session-start routine is never 'overdue' by the clock."""
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00002: r\n\n**Status**: Active\n"
                "**Trigger**: session_start\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.due_after_days is None


class TestMalformedHeaders:
    """What an unreadable header means, and why it is not a default."""

    def test_unknown_status_is_unknown_not_active(self, tmp_path: Path) -> None:
        """Defaulting to ACTIVE would invent an obligation nobody declared.

        Defaulting to RETIRED would silently switch one off. UNKNOWN is the
        only answer that neither invents nor suppresses, and lets a check
        report the header itself as the problem.
        """
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00001: r\n\n**Status**: Bananas\n"
                "**Trigger**: schedule\n**Period**: 30 days\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.status is RoutineStatus.UNKNOWN

    def test_a_schedule_with_no_period_has_no_due_date(self, tmp_path: Path) -> None:
        """Guessing a period would produce an overdue date that is wrong quietly."""
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00001: r\n\n**Status**: Active\n"
                "**Trigger**: schedule\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.period_days is None
        assert doc.due_after_days is None

    def test_a_missing_document_is_an_error(self, tmp_path: Path) -> None:
        """A folder with no ROUTINE.md is not a routine to reason about."""
        routine = tmp_path / "00001-security-review"
        routine.mkdir()

        with pytest.raises(FileNotFoundError):
            parse_routine(routine)

    def test_tolerates_a_header_without_bold_markers(self, tmp_path: Path) -> None:
        """Markdown formatters and human editors both touch these lines."""
        doc = parse_routine(
            _write(
                tmp_path,
                "# Routine 00001: r\n\nStatus: Active\nTrigger: schedule\n"
                "Period: 30 days\n\n## Procedure\n\n1. Go.\n",
            )
        )

        assert doc.status is RoutineStatus.ACTIVE
        assert doc.period_days == 30


class TestValueSemantics:
    """Small guards on the value object itself."""

    def test_folder_is_carried(self, tmp_path: Path) -> None:
        """Findings name the routine, so the doc has to know where it came from."""
        routine = _write(tmp_path, _SCHEDULED)

        assert parse_routine(routine).folder == routine

    def test_is_a_frozen_value(self, tmp_path: Path) -> None:
        """Parsed facts are read by several checks and mutated by none."""
        doc = parse_routine(_write(tmp_path, _SCHEDULED))
        mutable: Any = doc

        with pytest.raises(AttributeError):
            mutable.period_days = 1


def test_routine_doc_is_constructible_directly() -> None:
    """Checks build one in their own tests without touching a filesystem."""
    doc = RoutineDoc(
        folder=Path("00001-r"),
        status=RoutineStatus.ACTIVE,
        trigger=Trigger.SCHEDULE,
        period_days=30,
        grace_days=7,
    )

    assert doc.due_after_days == 37
