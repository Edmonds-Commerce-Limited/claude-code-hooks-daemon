"""Drift checks for the Routine tree (Plan 00412 Task 2.4).

Mirrors ``plan_qa``'s shape — pure check functions over a context, a tiny
runner, findings that each carry their own remediation — at the size this tree
actually needs.

Every check here exists because the failure it catches is SILENT. That is the
whole point of the Routine concept: a recurring obligation that stops being met
produces no error, no failing test and no diff. It produces an ABSENCE, and an
absence is indistinguishable from everything being fine unless something goes
looking. These checks are that something.

One consequence worth stating, because it looks like leniency and is not: a
RETIRED routine is skipped by the overdue and never-run checks. Reporting a
retired routine for ever would train its reader to skim past the section, and
a sweep nobody reads has the same value as a sweep that finds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.plan_qa.types import Level
from claude_code_hooks_daemon.routines.intervals import Ancestry, Continuity, discontinuities
from claude_code_hooks_daemon.routines.ledger import (
    LedgerEvent,
    RunEvent,
    malformed_rows,
    read_events,
)
from claude_code_hooks_daemon.routines.model import (
    RoutineDoc,
    RoutineStatus,
    Trigger,
    parse_routine,
)
from claude_code_hooks_daemon.routines.resolver import list_routines

CHECK_NEVER_RUN: Final[str] = "routine-never-run"
CHECK_OVERDUE: Final[str] = "routine-overdue"
CHECK_GAP: Final[str] = "routine-run-gap"
CHECK_LEDGER_UNREADABLE: Final[str] = "routine-ledger-unreadable"
CHECK_NOT_CONFIGURED: Final[str] = "routine-not-configured"

#: Events that END a run. Only these prove coverage — a START proves somebody
#: began, which is not the same claim and must never reset an overdue clock.
_TERMINAL: Final[frozenset[LedgerEvent]] = frozenset(
    {LedgerEvent.CLEAN, LedgerEvent.FINDINGS, LedgerEvent.SKIPPED}
)


@dataclass(frozen=True)
class RoutineFinding:
    """One violated invariant, the routine it belongs to, and its fix."""

    check_id: str
    level: Level
    routine: str
    message: str
    remediation: str


def sweep(
    project_root: Path,
    *,
    today: date,
    ancestry: Ancestry | None = None,
) -> list[RoutineFinding]:
    """Every finding across every live routine in ``project_root``.

    Args:
        project_root: Repository root.
        today: The date to measure overdue-ness against, injected so the
            checks stay pure and testable.
        ancestry: Oracle for the gap check. When omitted the gap check is
            skipped and every other check still runs — a caller without git
            gets a smaller answer rather than no answer.

    Returns:
        The findings, in routine order. Empty when the project declares no
        routines, which is not a failing state.
    """
    findings: list[RoutineFinding] = []
    for folder in list_routines(project_root):
        findings.extend(_check_routine(folder, today=today, ancestry=ancestry))
    return findings


def _check_routine(folder: Path, *, today: date, ancestry: Ancestry | None) -> list[RoutineFinding]:
    """Run every check against one routine folder."""
    try:
        doc = parse_routine(folder)
    except FileNotFoundError:
        return [
            RoutineFinding(
                check_id=CHECK_NOT_CONFIGURED,
                level=Level.ADVISE,
                routine=folder.name,
                message="the folder holds no ROUTINE.md, so nothing declares what it is",
                remediation="Add a ROUTINE.md, or remove the folder if it was created in error.",
            )
        ]

    events = read_events(folder)
    findings: list[RoutineFinding] = []
    findings.extend(_not_configured(doc))
    findings.extend(_ledger_unreadable(doc))
    findings.extend(_never_run(doc, events))
    findings.extend(_overdue(doc, events, today))
    if ancestry is not None:
        findings.extend(_gap(doc, events, ancestry))
    return findings


def _not_configured(doc: RoutineDoc) -> list[RoutineFinding]:
    """A routine nobody finished declaring.

    Deliberately reported even though a freshly scaffolded routine always
    trips it: every other check consults status and trigger, so an
    unrecognised value silently removes the routine from all of them. A check
    a typo can switch off is worse than no check, because it looks like one.
    """
    unreadable = [
        name
        for name, unknown in (
            ("Status", doc.status is RoutineStatus.UNKNOWN),
            ("Trigger", doc.trigger is Trigger.UNKNOWN),
        )
        if unknown
    ]
    if not unreadable:
        return []
    return [
        RoutineFinding(
            check_id=CHECK_NOT_CONFIGURED,
            level=Level.ADVISE,
            routine=doc.folder.name,
            message=(
                f"{' and '.join(unreadable)} not declared or not recognised, so this "
                "routine is invisible to the other checks"
            ),
            remediation=(
                "Fill in the ROUTINE.md header: Status is Active or Retired, "
                "Trigger is schedule, session_start or release."
            ),
        )
    ]


def _ledger_unreadable(doc: RoutineDoc) -> list[RoutineFinding]:
    """Rows a human edited into a state the reader cannot parse."""
    return [
        RoutineFinding(
            check_id=CHECK_LEDGER_UNREADABLE,
            level=Level.ADVISE,
            routine=doc.folder.name,
            message=f"run ledger has an unreadable row — {problem}",
            remediation=(
                "Repair the row in RUNS/. Until it parses, that run is missing "
                "from the coverage chain and a gap either side of it is invisible."
            ),
        )
        for problem in malformed_rows(doc.folder)
    ]


def _never_run(doc: RoutineDoc, events: list[RunEvent]) -> list[RoutineFinding]:
    """The dead-man's switch: no record at all.

    D6 keeps "never ran" out of the run-state vocabulary precisely so that it
    cannot be reported from the records. It has to be asserted from OUTSIDE
    them, by something that knows the routine exists — which is here.
    """
    if doc.status is not RoutineStatus.ACTIVE or events:
        return []
    return [
        RoutineFinding(
            check_id=CHECK_NEVER_RUN,
            level=Level.ADVISE,
            routine=doc.folder.name,
            message="declared active but has never run — no record exists at all",
            remediation=(
                f"Run it: `hooks-daemon run-routine {doc.folder.name}`. "
                "If it is no longer an obligation, set Status to Retired."
            ),
        )
    ]


def _overdue(doc: RoutineDoc, events: list[RunEvent], today: date) -> list[RoutineFinding]:
    """Past period PLUS grace since the last run that actually FINISHED."""
    if doc.status is not RoutineStatus.ACTIVE:
        return []
    due_after = doc.due_after_days
    if due_after is None:
        return []

    finished = [event for event in events if event.event in _TERMINAL]
    if not finished:
        return []

    last = max(event.at for event in finished).date()
    elapsed = (today - last).days
    if elapsed <= due_after:
        return []
    return [
        RoutineFinding(
            check_id=CHECK_OVERDUE,
            level=Level.ADVISE,
            routine=doc.folder.name,
            message=(
                f"overdue: last finished {elapsed} days ago, and its period plus "
                f"grace is {due_after} days"
            ),
            remediation=(
                f"Run it: `hooks-daemon run-routine {doc.folder.name}`. "
                "If the cadence is wrong, change Period/Grace rather than ignoring this."
            ),
        )
    ]


def _gap(doc: RoutineDoc, events: list[RunEvent], ancestry: Ancestry) -> list[RoutineFinding]:
    """Commits between two runs that neither of them covered.

    Only runs that recorded an interval take part. A skipped run covered
    nothing by definition, so including it would manufacture a hole where the
    design says there is none: a missed run WIDENS the next interval (D5).
    """
    covered = [event.interval for event in events if event.interval is not None]
    findings: list[RoutineFinding] = []
    for index, continuity in discontinuities(covered, ancestry):
        if continuity is Continuity.OVERLAP:
            # Ground covered twice. Wasteful, never dangerous, and reporting
            # it as drift would bury the finding that matters.
            continue
        earlier, later = covered[index], covered[index + 1]
        findings.append(
            RoutineFinding(
                check_id=CHECK_GAP,
                level=Level.ADVISE,
                routine=doc.folder.name,
                message=(
                    f"coverage {continuity} between runs: one ended at "
                    f"{earlier.to_ref} and the next began at {later.from_ref}"
                ),
                remediation=(
                    "Run the routine over the uncovered span, recording it as "
                    f"`--from {earlier.to_ref} --to {later.from_ref}`."
                ),
            )
        )
    return findings
