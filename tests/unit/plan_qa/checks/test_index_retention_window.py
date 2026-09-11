"""Tests for ``index-retention-window`` (Plan 00379 N1).

The main index keeps only the newest ``DEFAULT_COMPLETED_ROWS_MAX`` completed
rows; older ones move verbatim into ``Completed/README.md``. That rule already
had a batch guard
(``tests/integration/test_plan_index_navigability.py::test_completed_rows_stay_within_the_retention_window``)
whose only feedback path is a full QA run — so three consecutive archival
commits each added a row without ageing one out, reaching 33 rows against a
ceiling of 30, and every ``plan-qa --sweep`` in between reported a clean tree.

**COMMIT and SWEEP, deliberately no EDIT.** An archival adds the new row and
removes the aged-out ones; between those two writes the file is legitimately
over the window. An EDIT-stage block would deny the first half of a correct
archival and force an artificial ordering, which is the same reasoning that
keeps ``terminal-state-atomic`` commit-only: atomicity is a property of a
COMMIT, so a half-finished commit is not a violation to report.
"""

from dataclasses import replace
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.index_retention_window import CHECK_ID, CHECKS
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import (
    DEFAULT_COMPLETED_ROWS_MAX,
    CheckContext,
    Level,
    Stage,
)

_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_COMMIT_CHECK = next(spec for spec in CHECKS if spec.stage is Stage.COMMIT)
_SWEEP_CHECK = next(spec for spec in CHECKS if spec.stage is Stage.SWEEP)


def _completed_row(number: int) -> str:
    return f"- [{number:05d}: a plan](Completed/{number:05d}-a-plan/PLAN.md) - Complete\n"


def _active_row(number: int) -> str:
    return f"- [{number:05d}: a plan]({number:05d}-a-plan/PLAN.md) - In Progress\n"


def _index(completed: int, *, active: int = 0, cancelled: int = 0) -> str:
    text = "# Plans Index\n\n## Active Plans\n\n"
    text += "".join(_active_row(900 + i) for i in range(active))
    text += "\n## Completed Plans\n\n"
    text += "".join(_completed_row(100 + i) for i in range(completed))
    text += "\n## Cancelled Plans\n\n"
    text += "".join(_completed_row(500 + i) for i in range(cancelled))
    return text


def _tree_context(readme_text: str | None) -> CheckContext:
    return CheckContext(
        project_root=_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        readme=None if readme_text is None else ReadmeIndex.parse(readme_text),
    )


def _merged_context(primary: str, archived_rows: int) -> CheckContext:
    """A context shaped like the real one: ``rows`` merged, ``lines`` primary-only.

    ``plan_qa/context.py`` appends the archive index's rows to the primary
    ``ReadmeIndex`` so ``row-folder-bijection`` still sees a plan whose row has
    aged out, while leaving ``lines`` sourced from the primary file alone.
    """
    index = ReadmeIndex.parse(primary)
    archive_text = "# Archive\n\n## Completed Plans (Archive)\n\n" + "".join(
        _completed_row(700 + i) for i in range(archived_rows)
    )
    archive = ReadmeIndex.parse(archive_text)
    return CheckContext(
        project_root=_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        readme=replace(index, rows=index.rows + archive.rows),
    )


class TestRegistration:
    def test_it_runs_at_commit_and_sweep(self) -> None:
        assert {spec.stage for spec in CHECKS} == {Stage.COMMIT, Stage.SWEEP}

    def test_it_never_runs_at_edit(self) -> None:
        """A mid-archival write is legitimately over the window — see module docstring."""
        assert Stage.EDIT not in {spec.stage for spec in CHECKS}

    def test_every_registration_blocks(self) -> None:
        assert {spec.level for spec in CHECKS} == {Level.BLOCK}

    def test_every_registration_shares_the_check_id(self) -> None:
        assert {spec.check_id for spec in CHECKS} == {CHECK_ID}


class TestTheWindowIsRespected:
    def test_an_empty_section_is_clean(self) -> None:
        assert _COMMIT_CHECK.run(_tree_context(_index(0))) == []

    def test_well_under_the_window_is_clean(self) -> None:
        assert _COMMIT_CHECK.run(_tree_context(_index(5))) == []

    def test_exactly_the_window_is_clean(self) -> None:
        """The limit itself is allowed — ``>`` not ``>=``, matching the batch guard."""
        assert _COMMIT_CHECK.run(_tree_context(_index(DEFAULT_COMPLETED_ROWS_MAX))) == []

    def test_a_missing_readme_reports_nothing(self) -> None:
        assert _COMMIT_CHECK.run(_tree_context(None)) == []


class TestTheWindowIsExceeded:
    def test_one_row_over_is_caught(self) -> None:
        findings = _COMMIT_CHECK.run(_tree_context(_index(DEFAULT_COMPLETED_ROWS_MAX + 1)))
        assert len(findings) == 1

    def test_the_finding_blocks(self) -> None:
        findings = _COMMIT_CHECK.run(_tree_context(_index(DEFAULT_COMPLETED_ROWS_MAX + 1)))
        assert findings[0].level is Level.BLOCK

    def test_the_message_names_both_numbers(self) -> None:
        """A count with no ceiling beside it does not tell you how many to move."""
        over = DEFAULT_COMPLETED_ROWS_MAX + 3
        findings = _COMMIT_CHECK.run(_tree_context(_index(over)))
        assert str(over) in findings[0].message
        assert str(DEFAULT_COMPLETED_ROWS_MAX) in findings[0].message

    def test_the_remediation_names_the_archive(self) -> None:
        findings = _COMMIT_CHECK.run(_tree_context(_index(DEFAULT_COMPLETED_ROWS_MAX + 1)))
        assert "Completed/README.md" in findings[0].remediation

    def test_the_sweep_catches_it_too(self) -> None:
        """The surface that stayed silent for three commits."""
        findings = _SWEEP_CHECK.run(_tree_context(_index(DEFAULT_COMPLETED_ROWS_MAX + 3)))
        assert len(findings) == 1


class TestTheArchiveIndexIsNotCounted:
    """The regression that a synthetic fixture could not show.

    ``plan_qa/context.py`` merges the archive index's rows into ``readme.rows``.
    A first cut of this check filtered ``rows`` and reported 340 completed rows
    against a window of 30, on a tree that was correctly AT 30 — it would have
    blocked every commit in the repository.
    """

    def test_a_full_archive_does_not_trip_a_compliant_index(self) -> None:
        context = _merged_context(_index(DEFAULT_COMPLETED_ROWS_MAX), archived_rows=310)
        assert _COMMIT_CHECK.run(context) == []

    def test_the_count_ignores_merged_archive_rows(self) -> None:
        context = _merged_context(_index(DEFAULT_COMPLETED_ROWS_MAX + 2), archived_rows=310)
        findings = _COMMIT_CHECK.run(context)
        assert len(findings) == 1
        assert str(DEFAULT_COMPLETED_ROWS_MAX + 2) in findings[0].message

    def test_the_sweep_ignores_merged_archive_rows_too(self) -> None:
        context = _merged_context(_index(DEFAULT_COMPLETED_ROWS_MAX), archived_rows=310)
        assert _SWEEP_CHECK.run(context) == []


class TestOnlyCompletedRowsCount:
    def test_active_rows_do_not_push_it_over(self) -> None:
        """Active plans are not aged out, so they must not trip the ceiling."""
        context = _tree_context(_index(DEFAULT_COMPLETED_ROWS_MAX, active=20))
        assert _COMMIT_CHECK.run(context) == []

    def test_cancelled_rows_do_not_push_it_over(self) -> None:
        context = _tree_context(_index(DEFAULT_COMPLETED_ROWS_MAX, cancelled=20))
        assert _COMMIT_CHECK.run(context) == []

    def test_the_count_reported_is_the_completed_count(self) -> None:
        over = DEFAULT_COMPLETED_ROWS_MAX + 2
        context = _tree_context(_index(over, active=9, cancelled=7))
        findings = _COMMIT_CHECK.run(context)
        assert str(over) in findings[0].message
