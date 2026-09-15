"""Coverage as an interval, never a pointer (Plan 00412 Task 2.1, D2).

Taken from ``cargo-vet``, and the most important decision in the plan. A
Routine run records **the span it covered** — ``from`` -> ``to``, each a commit
or a tag — on the run record itself, and never bumps a mutable "last reviewed"
pointer.

The difference is entirely about FAILURE. Intervals compose: laying two runs
end to end either meets, overlaps, or leaves a hole, and a hole is arithmetic
rather than judgement. A pointer has no such property — bump it wrongly once,
by a crash, a rebase, a merge or a careless edit, and every subsequent run
believes a window was covered that nobody looked at. The pointer is silently
wrong forever, and nothing can detect it after the fact.

Two design points this module exists to hold:

- **Detection needs no oracle; CLASSIFICATION does.** Whether two runs are
  discontinuous is string inequality (``current.from != previous.to``), and
  that is deliberately all the dead-man's switch needs. Telling a GAP from an
  OVERLAP needs to know which ref came first, which is git ancestry — so that
  arrives as an injected :class:`Ancestry` rather than a subprocess call from
  in here. The arithmetic stays pure and testable; the subprocess stays at the
  edge, and the common case (a healthy consecutive pair) never pays for one.

- **A missed run WIDENS the next interval; it never leaves a hole** (D5 —
  systemd's ``Persistent=`` rather than a replay queue). If a run is skipped,
  the next one covers ``<last run's to> -> HEAD`` and composes as
  :data:`Continuity.MEETS`, because the span genuinely was covered. The record
  does not need to know a run was skipped, only what was looked at.

**Absence of a run is NOT expressible here** (D6). A Routine that never ran has
no runs to compose, so :func:`discontinuities` reports nothing — correctly.
Something outside this algebra has to assert that a run is overdue; conflating
the two would let a Routine nobody has ever run report as continuous.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Continuity(StrEnum):
    """How one run's interval sits against the previous run's."""

    #: The spans meet exactly: everything between them was covered.
    MEETS = "meets"
    #: The later run starts AFTER the earlier one ended — commits nobody
    #: covered. This is the finding the whole design exists to make visible.
    GAP = "gap"
    #: The later run starts BEFORE the earlier one ended — ground covered
    #: twice. Wasteful, never dangerous, and never to be reported as a hole.
    OVERLAP = "overlap"
    #: Neither ref is an ancestor of the other: a rebase, a diverged branch,
    #: or a ref nothing in history reaches. Deliberately its own answer —
    #: reporting it as MEETS would be the pointer bug in an interval's clothes.
    UNRELATED = "unrelated"


class Ancestry(Protocol):
    """Whether one ref precedes another in history.

    The real implementation is ``git merge-base --is-ancestor``; tests inject
    a plain ordered list. Kept as a Protocol so this module never shells out —
    a pure algebra is worth far more than the convenience of calling git from
    inside it.
    """

    def is_ancestor(self, earlier: str, later: str) -> bool:
        """True iff ``earlier`` is an ancestor of ``later``.

        An unknown or unreachable ref is not an ancestor of anything, which
        is how a diverged branch behaves.
        """
        ...


@dataclass(frozen=True, slots=True)
class RunInterval:
    """The span one Routine run covered.

    Both endpoints are required and non-blank: a record with a missing
    endpoint composes with everything and means nothing, so it is refused
    where it is built rather than reasoned about downstream.
    """

    from_ref: str
    to_ref: str

    def __post_init__(self) -> None:
        """Refuse a blank endpoint at construction.

        Raises:
            ValueError: Either endpoint is empty or whitespace only.
        """
        if not self.from_ref.strip():
            raise ValueError("RunInterval.from_ref must name a commit or tag")
        if not self.to_ref.strip():
            raise ValueError("RunInterval.to_ref must name a commit or tag")

    @property
    def is_empty(self) -> bool:
        """Whether this run covered no commits at all.

        Distinct from never having run: this one RAN and covered nothing,
        which is a real (if usually uninteresting) outcome and must not be
        confused with an absent record.
        """
        return self.from_ref == self.to_ref


def compose(previous: RunInterval, current: RunInterval, ancestry: Ancestry) -> Continuity:
    """How ``current`` sits against ``previous``.

    The equality test comes first and short-circuits, so the healthy case —
    every consecutive pair in a well-run Routine — costs no ancestry lookup at
    all. That matters because the real oracle is a subprocess and a QA sweep
    composes every adjacent pair on every run.

    Args:
        previous: The earlier run's interval.
        current: The later run's interval.
        ancestry: Oracle used only when the endpoints differ.

    Returns:
        The :class:`Continuity` between the two.
    """
    if current.from_ref == previous.to_ref:
        return Continuity.MEETS
    if ancestry.is_ancestor(previous.to_ref, current.from_ref):
        return Continuity.GAP
    if ancestry.is_ancestor(current.from_ref, previous.to_ref):
        return Continuity.OVERLAP
    return Continuity.UNRELATED


def discontinuities(
    runs: Sequence[RunInterval], ancestry: Ancestry
) -> list[tuple[int, Continuity]]:
    """Every adjacent pair in ``runs`` that does not meet cleanly.

    Args:
        runs: Run intervals in chronological order, oldest first.
        ancestry: Oracle passed through to :func:`compose`.

    Returns:
        ``(index, continuity)`` for each break, where ``index`` is the
        position of the EARLIER run of the pair. Empty when the chain is
        continuous — and also empty for zero or one run, because there is
        nothing to compose (see the module docstring on why "never ran" is
        deliberately not expressible here).
    """
    breaks: list[tuple[int, Continuity]] = []
    for index in range(len(runs) - 1):
        continuity = compose(runs[index], runs[index + 1], ancestry)
        if continuity is not Continuity.MEETS:
            breaks.append((index, continuity))
    return breaks
