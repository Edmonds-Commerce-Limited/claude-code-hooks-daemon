"""Tests for the ``journal-folder-present`` SWEEP check (Plan 00163).

An In-Progress plan numbered at/after ``grandfather_before`` that has no
``JOURNAL/`` is nagged (ADVISE) to start journalling. Legacy plans below the
threshold, and non-active statuses, are never nagged (no backfill).
"""

from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks import journal_folder_present
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


def _folder(number: int, status: PlanStatus, *, has_journal: bool) -> PlanFolder:
    return PlanFolder(
        path=Path(f"/repo/CLAUDE/Plan/{number:05d}-x"),
        name=f"{number:05d}-x",
        number=number,
        location=PlanLocation.ROOT,
        has_plan_md=True,
        doc=_doc(status),
        has_journal=has_journal,
        latest_journal_date=None,
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
    grandfather_before: int = 163,
    journal_enabled: bool = True,
    journal_mode: str = "advise",
) -> CheckContext:
    return CheckContext(
        project_root=Path("/repo"),
        plan_dir_rel="CLAUDE/Plan",
        tree=tree,
        today=date(2026, 7, 14),
        journal_enabled=journal_enabled,
        journal_mode=journal_mode,
        journal_grandfather_before=grandfather_before,
    )


class TestSpec:
    def test_registered_sweep_advise(self) -> None:
        spec = journal_folder_present.CHECK
        assert spec.check_id == "journal-folder-present"
        assert spec.stage == Stage.SWEEP
        assert spec.level == Level.ADVISE


class TestRun:
    def test_active_plan_without_journal_advises(self) -> None:
        tree = _tree(_folder(163, PlanStatus.IN_PROGRESS, has_journal=False))
        findings = journal_folder_present.CHECK.run(_ctx(tree))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
        assert "00163-x" in findings[0].message

    def test_active_plan_with_journal_is_clean(self) -> None:
        tree = _tree(_folder(163, PlanStatus.IN_PROGRESS, has_journal=True))
        assert journal_folder_present.CHECK.run(_ctx(tree)) == []

    def test_legacy_plan_below_threshold_never_nagged(self) -> None:
        tree = _tree(_folder(50, PlanStatus.IN_PROGRESS, has_journal=False))
        assert journal_folder_present.CHECK.run(_ctx(tree)) == []

    def test_not_started_plan_not_nagged(self) -> None:
        tree = _tree(_folder(200, PlanStatus.NOT_STARTED, has_journal=False))
        assert journal_folder_present.CHECK.run(_ctx(tree)) == []

    def test_disabled_journalling_is_silent(self) -> None:
        tree = _tree(_folder(163, PlanStatus.IN_PROGRESS, has_journal=False))
        assert journal_folder_present.CHECK.run(_ctx(tree, journal_enabled=False)) == []
        assert journal_folder_present.CHECK.run(_ctx(tree, journal_mode="off")) == []

    def test_no_tree_is_silent(self) -> None:
        ctx = CheckContext(project_root=Path("/repo"), plan_dir_rel="CLAUDE/Plan")
        assert journal_folder_present.CHECK.run(ctx) == []
