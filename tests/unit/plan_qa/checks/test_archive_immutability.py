"""Tests for the archive-immutability check (Plan 00144; sin A5)."""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.archive_immutability import CHECK
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_COMPLETE_PLAN = "# Plan 00042: Widget\n\n**Status**: Complete\n\n- [x] task\n"


def _context(file_rel: str, content: str, exists_before: bool = False) -> CheckContext:
    return CheckContext(
        project_root=_PROJECT_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        file_path=_PROJECT_ROOT / file_rel,
        file_content=content,
        file_exists_before=exists_before,
    )


class TestSpec:
    def test_registered_for_edit_stage(self) -> None:
        assert CHECK.check_id == "archive-immutability"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("A5",)


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self) -> None:
        context = _context(
            "CLAUDE/Plan/Completed/00042-widget/notes.md", _COMPLETE_PLAN, exists_before=True
        )
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []


class TestFindings:
    def test_new_file_in_archive_passes(self) -> None:
        context = _context(
            "CLAUDE/Plan/Completed/00042-widget/PLAN.md", _COMPLETE_PLAN, exists_before=False
        )
        assert CHECK.run(context) == []

    def test_edit_of_active_plan_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _COMPLETE_PLAN, exists_before=True)
        assert CHECK.run(context) == []

    def test_edit_of_existing_archived_plan_advises(self) -> None:
        context = _context(
            "CLAUDE/Plan/Completed/00042-widget/PLAN.md", _COMPLETE_PLAN, exists_before=True
        )
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "archive-immutability"
        assert finding.level == Level.ADVISE
        assert "history" in finding.message
