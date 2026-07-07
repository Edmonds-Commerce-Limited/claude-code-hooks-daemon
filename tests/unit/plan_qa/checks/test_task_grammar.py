"""Tests for the task-grammar check (Plan 00144; sin E6)."""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.task_grammar import CHECK
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_TEMPLATE_GRAMMAR = "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [x] ✅ **Task 1**: done\n"
_LEGACY_GRAMMAR = "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [~] **Task 1**: half done\n"


def _context(
    file_rel: str,
    content: str,
    exists_before: bool = False,
    legacy: frozenset[int] = frozenset(),
) -> CheckContext:
    return CheckContext(
        project_root=_PROJECT_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        legacy_plan_allowlist=legacy,
        file_path=_PROJECT_ROOT / file_rel,
        file_content=content,
        file_exists_before=exists_before,
    )


class TestSpec:
    def test_registered_for_edit_stage(self) -> None:
        assert CHECK.check_id == "task-grammar"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("E6",)


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/notes.md", _LEGACY_GRAMMAR)
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []


class TestFindings:
    def test_template_grammar_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _TEMPLATE_GRAMMAR)
        assert CHECK.run(context) == []

    def test_legacy_grammar_blocks_new_material(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _LEGACY_GRAMMAR, exists_before=False)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "task-grammar"
        assert finding.level == Level.BLOCK
        assert "⬜" in finding.remediation

    def test_legacy_grammar_advises_on_existing_file(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _LEGACY_GRAMMAR, exists_before=True)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
