"""Tests for the ``journal-freshness`` SWEEP check (Plan 00163).

An In-Progress plan that HAS a ``JOURNAL/`` whose newest day-file is older than
``freshness_days`` is nagged (ADVISE). Freshness reads the day-file NAME
(``latest_journal_date``), never git dates, so uncommitted journals still
count. Scoped to plans that already journal — presence is a separate check.
"""

from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks import journal_freshness
from claude_code_hooks_daemon.plan_qa.model import (
    PlanDoc,
    PlanFolder,
    PlanLocation,
    PlanStatus,
    PlanTree,
    TaskCounts,
)
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_ZERO_TASKS = TaskCounts(0, 0, 0, 0, 0, 0, 0, 0)


def _doc(status: PlanStatus) -> PlanDoc:
    return PlanDoc(
        plan_number=None,
        title=None,
        status_line_present=True,
        status=status,
        status_raw=status.value,
        status_date=None,
        created=None,
        owner=None,
        priority=None,
        tasks=_ZERO_TASKS,
        done_marker_count=0,
    )


def _folder(
    number: int,
    status: PlanStatus,
    *,
    has_journal: bool,
    latest: date | None,
) -> PlanFolder:
    return PlanFolder(
        path=Path(f"/repo/CLAUDE/Plan/{number:05d}-x"),
        name=f"{number:05d}-x",
        number=number,
        location=PlanLocation.ROOT,
        has_plan_md=True,
        doc=_doc(status),
        has_journal=has_journal,
        latest_journal_date=latest,
    )


def _tree(*folders: PlanFolder) -> PlanTree:
    return PlanTree(
        root=Path("/repo/CLAUDE/Plan"),
        completed_dir_name="Completed",
        cancelled_dir_name="Cancelled",
        folders=folders,
        stray_files=(),
        has_readme=True,
        has_completed_dir=True,
        has_cancelled_dir=True,
    )


def _ctx(
    tree: PlanTree,
    *,
    freshness_days: int = 3,
    journal_enabled: bool = True,
    journal_mode: str = "advise",
    today: date = date(2026, 7, 14),
) -> CheckContext:
    return CheckContext(
        project_root=Path("/repo"),
        plan_dir_rel="CLAUDE/Plan",
        tree=tree,
        today=today,
        journal_enabled=journal_enabled,
        journal_mode=journal_mode,
        journal_freshness_days=freshness_days,
    )


class TestSpec:
    def test_registered_sweep_advise(self) -> None:
        spec = journal_freshness.CHECK
        assert spec.check_id == "journal-freshness"
        assert spec.stage == Stage.SWEEP
        assert spec.level == Level.ADVISE


class TestRun:
    def test_fresh_journal_is_clean(self) -> None:
        tree = _tree(
            _folder(163, PlanStatus.IN_PROGRESS, has_journal=True, latest=date(2026, 7, 14))
        )
        assert journal_freshness.CHECK.run(_ctx(tree)) == []

    def test_stale_journal_advises(self) -> None:
        # 07-14 today, newest day-file 07-09 → 5 days > 3.
        tree = _tree(
            _folder(163, PlanStatus.IN_PROGRESS, has_journal=True, latest=date(2026, 7, 9))
        )
        findings = journal_freshness.CHECK.run(_ctx(tree))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
        assert "00163-x" in findings[0].message

    def test_boundary_not_stale(self) -> None:
        # exactly freshness_days old → not yet stale (strictly greater).
        tree = _tree(
            _folder(163, PlanStatus.IN_PROGRESS, has_journal=True, latest=date(2026, 7, 11))
        )
        assert journal_freshness.CHECK.run(_ctx(tree)) == []

    def test_plan_without_journal_not_this_checks_concern(self) -> None:
        tree = _tree(_folder(163, PlanStatus.IN_PROGRESS, has_journal=False, latest=None))
        assert journal_freshness.CHECK.run(_ctx(tree)) == []

    def test_journal_dir_without_dayfiles_not_flagged(self) -> None:
        # has_journal but no parseable date → cannot judge freshness; silent.
        tree = _tree(_folder(163, PlanStatus.IN_PROGRESS, has_journal=True, latest=None))
        assert journal_freshness.CHECK.run(_ctx(tree)) == []

    def test_non_active_status_not_flagged(self) -> None:
        tree = _tree(_folder(163, PlanStatus.DORMANT, has_journal=True, latest=date(2026, 1, 1)))
        assert journal_freshness.CHECK.run(_ctx(tree)) == []

    def test_disabled_is_silent(self) -> None:
        tree = _tree(
            _folder(163, PlanStatus.IN_PROGRESS, has_journal=True, latest=date(2026, 1, 1))
        )
        assert journal_freshness.CHECK.run(_ctx(tree, journal_enabled=False)) == []

    def test_no_tree_or_today_is_silent(self) -> None:
        ctx = CheckContext(project_root=Path("/repo"), plan_dir_rel="CLAUDE/Plan")
        assert journal_freshness.CHECK.run(ctx) == []
