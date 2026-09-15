"""The facts a routine states about itself (Plan 00412 Task 2.4).

A ROUTINE.md header declares three things the QA checks need: whether the
routine is still active, what triggers it, and — for a scheduled one — how
often, so that "overdue" can mean something.

**Period alone is not enough** (D11). A monthly routine with no grace is
overdue on day 31, every month, for ever. That nag arrives reliably and is
ignored just as reliably, which is how a recurring obligation quietly stops
being one. So an undeclared grace takes a DEFAULT rather than zero: zero is
precisely the value that produces the failure D11 names.

Trigger kinds are a closed set. A free-text cadence ("monthly-ish", "each
release") would have to be interpreted, and a misread cadence yields an overdue
date that is wrong without being detectably wrong — the same silent-wrongness
the interval model exists to keep out of this system.

Every unreadable field resolves to an UNKNOWN or a None rather than to a
plausible default. Defaulting a missing status to ACTIVE invents an obligation
nobody declared; defaulting it to RETIRED switches one off. Neither is a thing
a parser should decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

#: The definition document inside a routine folder.
ROUTINE_DOC: Final[str] = "ROUTINE.md"

#: Divisor for an undeclared grace. A CHOSEN default, not a derived one --
#: which is why it is overridable per routine. The only property that matters
#: is that it is not zero.
_GRACE_DIVISOR: Final[int] = 5

#: Floor for a defaulted grace, so integer division on a short period cannot
#: quietly reintroduce the zero this default exists to avoid.
_MIN_DEFAULT_GRACE_DAYS: Final[int] = 1


class RoutineStatus(StrEnum):
    """Whether the routine is still an obligation."""

    ACTIVE = "active"
    RETIRED = "retired"
    #: The header did not say, or said something unrecognised. Deliberately
    #: neither of the above — a check can report the HEADER as the problem
    #: instead of acting on an invented answer.
    UNKNOWN = "unknown"


class Trigger(StrEnum):
    """What prompts a run. A closed set, never free text."""

    #: On a clock. Needs a period for "overdue" to be computable.
    SCHEDULE = "schedule"
    #: At session start (D9) — the trigger the daemon actually executes,
    #: rather than one it can only hope fired.
    SESSION_START = "session_start"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RoutineDoc:
    """One routine's declared facts.

    Frozen: several checks read the same parsed document and none of them
    should be able to change what another sees.
    """

    folder: Path
    status: RoutineStatus
    trigger: Trigger
    period_days: int | None = None
    grace_days: int | None = None

    @property
    def due_after_days(self) -> int | None:
        """Days after the last run before this routine is overdue.

        Returns:
            ``period + grace``, or None when the routine is not on a clock or
            declared no period — in which case nothing here may guess one.
        """
        if self.trigger is not Trigger.SCHEDULE or self.period_days is None:
            return None
        grace = self.grace_days if self.grace_days is not None else default_grace(self.period_days)
        return self.period_days + grace


def default_grace(period_days: int) -> int:
    """The grace to use when a scheduled routine declares none.

    Args:
        period_days: The declared period.

    Returns:
        A fifth of the period, never less than a day.
    """
    return max(_MIN_DEFAULT_GRACE_DAYS, period_days // _GRACE_DIVISOR)


def parse_routine(folder: Path) -> RoutineDoc:
    """Read ``folder``'s ROUTINE.md header.

    Args:
        folder: A routine folder.

    Returns:
        The declared facts, with anything unreadable left UNKNOWN or None.

    Raises:
        FileNotFoundError: The folder holds no ROUTINE.md.
    """
    document = folder / ROUTINE_DOC
    if not document.is_file():
        raise FileNotFoundError(f"{folder} has no {ROUTINE_DOC}")

    fields = _header_fields(document.read_text(encoding="utf-8"))
    period = _days(fields.get("period"))
    declared_grace = _days(fields.get("grace"))
    return RoutineDoc(
        folder=folder,
        status=_status(fields.get("status")),
        trigger=_trigger(fields.get("trigger")),
        period_days=period,
        grace_days=_effective_grace(declared_grace, period),
    )


def _effective_grace(declared: int | None, period_days: int | None) -> int | None:
    """The grace actually in force.

    Resolved here rather than left for each consumer, because every consumer
    wants the effective value and a second place to apply the default is a
    second place for it to be applied differently.

    A DECLARED zero survives: it is a decision, and only an OMISSION takes the
    default. The distinction the module cares about is preserved in the value
    itself, since a declared 0 and a defaulted fifth are never equal.

    Args:
        declared: The ``Grace:`` field, or None when absent.
        period_days: The declared period, or None.

    Returns:
        The grace in days, or None when there is no period to derive one from.
    """
    if declared is not None:
        return declared
    return None if period_days is None else default_grace(period_days)


#: ``**Name**: value`` or ``Name: value``. Bold markers are optional because
#: markdown formatters and human editors both touch these lines, and a header
#: that stopped parsing after a reformat would report every routine as broken.
_HEADER_LINE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:\*\*)?(?P<name>[A-Za-z][A-Za-z ]*?)(?:\*\*)?\s*:\s*(?P<value>.+?)\s*$"
)

#: A leading integer, so "30 days" and "30" both read as 30.
_LEADING_INT: Final[re.Pattern[str]] = re.compile(r"^\s*(\d+)\b")


def _header_fields(document: str) -> dict[str, str]:
    """The ``Name: value`` lines above the first ``##`` section.

    Scanning stops at the first section heading so a colon inside the
    procedure cannot be mistaken for a declaration.
    """
    fields: dict[str, str] = {}
    for line in document.splitlines():
        if line.startswith("##"):
            break
        match = _HEADER_LINE.match(line)
        if match:
            fields[match.group("name").strip().lower()] = match.group("value").strip()
    return fields


def _status(value: str | None) -> RoutineStatus:
    """A declared status, or UNKNOWN when it is absent or unrecognised."""
    if value is None:
        return RoutineStatus.UNKNOWN
    try:
        return RoutineStatus(value.strip().lower())
    except ValueError:
        return RoutineStatus.UNKNOWN


def _trigger(value: str | None) -> Trigger:
    """A declared trigger, or UNKNOWN when it is absent or unrecognised."""
    if value is None:
        return Trigger.UNKNOWN
    try:
        return Trigger(value.strip().lower())
    except ValueError:
        return Trigger.UNKNOWN


def _days(value: str | None) -> int | None:
    """A day count from ``"30 days"``/``"30"``, or None when unreadable.

    None rather than 0: a period nobody declared and a period declared as zero
    are different statements, and only the second is a decision.
    """
    if value is None:
        return None
    match = _LEADING_INT.match(value)
    return int(match.group(1)) if match else None
