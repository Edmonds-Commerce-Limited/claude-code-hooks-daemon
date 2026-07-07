"""Tests for the template-metadata check (Plan 00144; sin E7)."""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.template_metadata import CHECK
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_FULL_METADATA = (
    "# Plan 00042: Widget\n\n"
    "**Status**: Not Started\n"
    "**Created**: 2026-07-01\n"
    "**Owner**: Alice\n"
    "**Priority**: High\n"
)
_MISSING_OWNER_PRIORITY = (
    "# Plan 00042: Widget\n\n**Status**: Not Started\n**Created**: 2026-07-01\n"
)
_MISSING_ALL = "# Plan 00042: Widget\n\n**Status**: Not Started\n"


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
        assert CHECK.check_id == "template-metadata"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("E7",)


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/notes.md", _MISSING_ALL)
        assert CHECK.run(context) == []

    def test_ignores_existing_files(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _MISSING_ALL, exists_before=True)
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []


class TestFindings:
    def test_full_metadata_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _FULL_METADATA)
        assert CHECK.run(context) == []

    def test_missing_owner_and_priority_advises(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _MISSING_OWNER_PRIORITY)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "template-metadata"
        assert finding.level == Level.ADVISE
        assert "Owner" in finding.message
        assert "Priority" in finding.message
        assert "Created" not in finding.message

    def test_missing_all_metadata_advises(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _MISSING_ALL)
        findings = CHECK.run(context)
        assert len(findings) == 1
        message = findings[0].message
        assert "Created" in message
        assert "Owner" in message
        assert "Priority" in message
