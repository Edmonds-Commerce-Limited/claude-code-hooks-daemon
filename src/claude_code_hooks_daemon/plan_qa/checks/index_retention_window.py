"""Check ``index-retention-window`` (Stage 2/3, block; Plan 00379 N1).

The main index keeps only the newest :data:`DEFAULT_COMPLETED_ROWS_MAX`
completed rows; every older row moves verbatim into ``Completed/README.md``.
That keeps the entry point to the tree navigable without losing a row.

This is the FAST equivalent of
``tests/integration/test_plan_index_navigability.py::test_completed_rows_stay_within_the_retention_window``,
which stays exactly as it is (a commit gate and a suite guard see different
things). The suite guard's only feedback path is a full QA run, and that delay
is not theoretical: three consecutive archival commits each added a row without
ageing one out, reaching 33 rows against a ceiling of 30. Every
``plan-qa --sweep`` in between reported a clean tree, because no check looked.

**COMMIT and SWEEP, deliberately no EDIT.** An archival adds the new row and
removes the aged-out ones, and between those two writes the index is
legitimately over the window. Blocking at EDIT would deny the first half of a
correct archival and force an artificial ordering on it. This is the same
reasoning that keeps ``terminal-state-atomic`` commit-only: atomicity is a
property of a COMMIT, so a half-finished one is not yet a violation.

Why the row COUNT rather than the row numbers: the rule is a navigability
ceiling, so what matters is how many rows a reader must scan. Which specific
rows should have aged out follows from the ordering the index already keeps,
and naming them here would duplicate a judgement ``row-folder-bijection``
and the archive index already own.
"""

from typing import Final

from claude_code_hooks_daemon.plan_qa.model import README_FILENAME
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex, ReadmeSection
from claude_code_hooks_daemon.plan_qa.types import (
    DEFAULT_COMPLETED_ROWS_MAX,
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "index-retention-window"

_REMEDIATION: Final[str] = (
    "Move every completed row beyond the newest "
    f"{DEFAULT_COMPLETED_ROWS_MAX} — verbatim, content unchanged — into "
    "Completed/README.md, rebasing each link off the Completed/ prefix. Do it "
    "in the SAME commit as the archival that displaced them, per the Plan "
    "Completion Checklist in CLAUDE/PlanWorkflow.md."
)


def _completed_row_count(context: CheckContext) -> int | None:
    """How many rows sit under the PRIMARY index's completed section, or ``None``.

    Counted by re-parsing ``readme.lines``, NOT by filtering ``readme.rows``.
    That distinction is the whole check: ``rows`` is deliberately the UNION of
    the main index and the archive index (see ``plan_qa/context.py`` — it is
    merged so ``row-folder-bijection`` still sees a plan whose row has aged
    out), while ``lines`` stays sourced from the primary file alone. Filtering
    ``rows`` here counts every archived row too and reports the whole corpus as
    overdue — measured at 340 against a window of 30 on a tree that was
    correctly at 30.

    Re-parsing rather than re-implementing keeps one definition of what a row
    is and which section it sits under.
    """
    readme = context.readme
    if readme is None:
        return None
    primary = ReadmeIndex.parse("\n".join(readme.lines))
    return sum(1 for row in primary.rows if row.section is ReadmeSection.COMPLETED)


def _message(count: int) -> str:
    overflow = count - DEFAULT_COMPLETED_ROWS_MAX
    plural = "row" if overflow == 1 else "rows"
    return (
        f"The plan index carries {count:,} completed rows against a retention "
        f"window of {DEFAULT_COMPLETED_ROWS_MAX:,}. An archival adds a row and "
        f"must age one out in the same commit; {overflow:,} {plural} overdue "
        "for the archive index."
    )


def _run_tree(context: CheckContext) -> list[Finding]:
    """Stages 2 and 3: the index as it stands, from the parsed tree view."""
    count = _completed_row_count(context)
    if count is None or count <= DEFAULT_COMPLETED_ROWS_MAX:
        return []
    return [
        Finding(
            check_id=CHECK_ID,
            level=Level.BLOCK,
            message=_message(count),
            remediation=_REMEDIATION,
            path=f"{context.plan_dir_rel.rstrip('/')}/{README_FILENAME}",
        )
    ]


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    # No 00144 audit-catalogue sin: the retention window post-dates it, and the
    # failure it catches (an archival that forgot the age-out) was measured in
    # this repository rather than predicted.
    CheckSpec(check_id=CHECK_ID, stage=Stage.COMMIT, level=Level.BLOCK, sins=(), run=_run_tree),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.BLOCK, sins=(), run=_run_tree),
)
