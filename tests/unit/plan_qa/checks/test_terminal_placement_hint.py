"""Tests for the terminal-placement-hint check (Plan 00144; sins C1, C2, C3)."""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.terminal_placement_hint import CHECK
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_COMPLETE_PLAN = "# Plan 00042: Widget\n\n**Status**: Complete\n\n- [x] task\n"
_IN_PROGRESS_PLAN = "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [ ] task\n"


def _context(file_rel: str, content: str) -> CheckContext:
    return CheckContext(
        project_root=_PROJECT_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        file_path=_PROJECT_ROOT / file_rel,
        file_content=content,
    )


class TestSpec:
    def test_registered_for_edit_stage(self) -> None:
        assert CHECK.check_id == "terminal-placement-hint"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("C1", "C2", "C3")


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/notes.md", _COMPLETE_PLAN)
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []


class TestFindings:
    def test_non_terminal_plan_in_root_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _IN_PROGRESS_PLAN)
        assert CHECK.run(context) == []

    def test_terminal_plan_already_archived_passes(self) -> None:
        context = _context("CLAUDE/Plan/Completed/00042-widget/PLAN.md", _COMPLETE_PLAN)
        assert CHECK.run(context) == []

    def test_terminal_plan_still_in_root_advises(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _COMPLETE_PLAN)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "terminal-placement-hint"
        assert finding.level == Level.ADVISE
        assert "git mv" in finding.remediation
        assert "README" in finding.remediation
