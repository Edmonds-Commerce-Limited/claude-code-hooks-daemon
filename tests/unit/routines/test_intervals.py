"""Plan 00412 Task 2.1 — the interval algebra, RED first.

D2 is the plan's most important decision, taken from `cargo-vet`: a Routine
run records **the span it covered** (`from` -> `to`, each a commit or tag) on
the run record itself, and never bumps a mutable "last reviewed" pointer.

The difference is entirely about failure. Intervals COMPOSE — laying two runs
end to end either meets, overlaps, or leaves a hole, and a hole is arithmetic
rather than judgement. A pointer has no such property: bump it wrongly once,
by a crash, a rebase or a careless edit, and every later run believes a window
was covered that nobody looked at. It is silently wrong forever and nothing
can detect it afterwards.

This file pins that arithmetic. Two design points it exists to hold:

- **Detection needs no oracle; CLASSIFICATION does.** Whether two runs are
  discontinuous is string inequality — `current.from != previous.to` — and
  that is deliberately all the dead-man's-switch needs. Telling a GAP from an
  OVERLAP needs to know which ref came first, which is git ancestry, so the
  algebra takes that as an injected oracle rather than shelling out. The
  arithmetic stays pure and testable; the subprocess stays at the edge.
- **A skipped run WIDENS the next interval; it never leaves a hole** (D5,
  systemd's `Persistent=` rather than a replay queue). If run B never happens,
  run C covers `A.to -> HEAD` and composing A with C reads as MEETS — because
  it genuinely is covered. That property is what makes "missed runs widen"
  safe rather than a way to lose a window.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.routines.intervals import (
    Continuity,
    RunInterval,
    compose,
    discontinuities,
)


class _FakeHistory:
    """An ancestry oracle over a linear list of refs, oldest first.

    Stands in for `git merge-base --is-ancestor` so the algebra can be tested
    without a repository. A ref the history does not know is unrelated to
    everything, which is how a diverged branch behaves.
    """

    def __init__(self, *refs: str) -> None:
        self._order = {ref: index for index, ref in enumerate(refs)}
        self.calls = 0

    def is_ancestor(self, earlier: str, later: str) -> bool:
        self.calls += 1
        if earlier not in self._order or later not in self._order:
            return False
        return self._order[earlier] < self._order[later]


_HISTORY = ("c1", "c2", "c3", "c4", "c5")


def _history() -> _FakeHistory:
    return _FakeHistory(*_HISTORY)


class TestTwoRunsThatMeet:
    def test_end_to_start_is_full_coverage(self) -> None:
        first = RunInterval(from_ref="c1", to_ref="c3")
        second = RunInterval(from_ref="c3", to_ref="c5")
        assert compose(first, second, _history()) is Continuity.MEETS

    def test_meeting_costs_no_ancestry_call(self) -> None:
        """The common case must not pay for a subprocess.

        Every healthy consecutive pair meets, so a design that asked the
        oracle anyway would shell out once per pair on every QA sweep to
        learn something string equality already knew.
        """
        history = _history()
        compose(
            RunInterval(from_ref="c1", to_ref="c3"),
            RunInterval(from_ref="c3", to_ref="c5"),
            history,
        )
        assert history.calls == 0


class TestAGapIsVisible:
    def test_a_skipped_span_reads_as_a_gap(self) -> None:
        # c3 -> c4 was covered by nobody.
        first = RunInterval(from_ref="c1", to_ref="c3")
        second = RunInterval(from_ref="c4", to_ref="c5")
        assert compose(first, second, _history()) is Continuity.GAP

    def test_the_gap_is_found_without_consulting_anything_mutable(self) -> None:
        """The whole point of D2, asserted directly.

        `compose` is given the two records and an ancestry oracle over
        immutable history. There is no "last run" state to read, and so
        none to be wrong.
        """
        first = RunInterval(from_ref="c1", to_ref="c2")
        second = RunInterval(from_ref="c4", to_ref="c5")
        assert compose(first, second, _history()) is Continuity.GAP


class TestAnOverlapIsNotAGap:
    def test_re_covering_ground_reads_as_overlap(self) -> None:
        # Wasteful, not dangerous — and it must never be reported as a hole.
        first = RunInterval(from_ref="c1", to_ref="c4")
        second = RunInterval(from_ref="c2", to_ref="c5")
        assert compose(first, second, _history()) is Continuity.OVERLAP


class TestDivergedRefsAreNeitherMetNorOrdered:
    def test_an_unknown_ref_is_unrelated_rather_than_meeting(self) -> None:
        # A rebase or a branch can leave a recorded ref that is on no shared
        # line of history. Reporting that as MEETS would be the pointer bug
        # wearing an interval's clothes.
        first = RunInterval(from_ref="c1", to_ref="c3")
        second = RunInterval(from_ref="deadbeef", to_ref="c5")
        assert compose(first, second, _history()) is Continuity.UNRELATED

    def test_unrelated_is_not_silently_a_gap(self) -> None:
        first = RunInterval(from_ref="c1", to_ref="c3")
        second = RunInterval(from_ref="deadbeef", to_ref="c5")
        assert compose(first, second, _history()) is not Continuity.GAP


class TestAMissedRunWidensRatherThanHoles:
    def test_the_next_run_covers_the_skipped_span(self) -> None:
        """D5: systemd's `Persistent=`, not a replay queue.

        Run B never happened. Run C starts where A finished, so the span is
        genuinely covered and the composition says so — the record does not
        need to know a run was skipped, only what was looked at.
        """
        ran = RunInterval(from_ref="c1", to_ref="c2")
        after_a_miss = RunInterval(from_ref="c2", to_ref="c5")
        assert compose(ran, after_a_miss, _history()) is Continuity.MEETS


class TestAnEmptyIntervalIsDetectable:
    def test_a_run_that_covered_nothing_says_so(self) -> None:
        # Distinct from "never ran": this one ran and covered zero commits.
        assert RunInterval(from_ref="c3", to_ref="c3").is_empty is True

    def test_a_real_span_is_not_empty(self) -> None:
        assert RunInterval(from_ref="c1", to_ref="c3").is_empty is False

    def test_a_blank_ref_is_refused_at_construction(self) -> None:
        # A record with a missing endpoint composes with everything and means
        # nothing; refuse it where it is built rather than reason about it.
        with pytest.raises(ValueError):
            RunInterval(from_ref="", to_ref="c3")
        with pytest.raises(ValueError):
            RunInterval(from_ref="c1", to_ref="   ")


class TestASequenceOfRuns:
    def test_a_clean_chain_reports_nothing(self) -> None:
        runs = [
            RunInterval(from_ref="c1", to_ref="c2"),
            RunInterval(from_ref="c2", to_ref="c3"),
            RunInterval(from_ref="c3", to_ref="c5"),
        ]
        assert discontinuities(runs, _history()) == []

    def test_each_break_is_reported_with_its_position(self) -> None:
        runs = [
            RunInterval(from_ref="c1", to_ref="c2"),
            RunInterval(from_ref="c3", to_ref="c4"),  # gap after index 0
            RunInterval(from_ref="c4", to_ref="c5"),
        ]
        assert discontinuities(runs, _history()) == [(0, Continuity.GAP)]

    def test_overlaps_are_reported_too_and_named_distinctly(self) -> None:
        runs = [
            RunInterval(from_ref="c1", to_ref="c4"),
            RunInterval(from_ref="c2", to_ref="c5"),
        ]
        assert discontinuities(runs, _history()) == [(0, Continuity.OVERLAP)]

    def test_a_single_run_has_nothing_to_compose(self) -> None:
        assert discontinuities([RunInterval(from_ref="c1", to_ref="c2")], _history()) == []

    def test_no_runs_is_not_an_error_here(self) -> None:
        """Absence of a run is D6's problem, not this function's.

        "Never ran" is deliberately NOT expressible as a gap between runs —
        there are no runs to compose. Something outside this algebra has to
        assert a run is overdue (Task 2.5), and conflating the two would let
        a routine that never ran report as continuous.
        """
        assert discontinuities([], _history()) == []
