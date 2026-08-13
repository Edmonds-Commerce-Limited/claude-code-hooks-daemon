"""Tests for the header-body-coherence check (Plan 00144; sins A3, A1)."""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.header_body_coherence import CHECKS
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

# These tests exercise the edit-time surface; the sweep twin is covered by
# tests/unit/plan_qa/checks/test_document_rule_stage_parity.py.
CHECK = CHECKS.edit

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_COHERENT_IN_PROGRESS = "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [ ] task\n"
_NOT_STARTED_ALL_CHECKED = "# Plan 00042: Widget\n\n**Status**: Not Started\n\n- [x] task\n"
_IN_PROGRESS_DONE_MARKER = (
    "# Plan 00042: Widget\n\n**Status**: In Progress\n\nAll tasks complete.\n- [x] task\n"
)
_COMPLETE_ALL_CHECKED = "# Plan 00042: Widget\n\n**Status**: Complete\n\n- [x] task\n"


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
        assert CHECK.check_id == "header-body-coherence"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.BLOCK
        assert CHECK.sins == ("A3", "A1")


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/notes.md", _NOT_STARTED_ALL_CHECKED)
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []


class TestFindings:
    def test_coherent_in_progress_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _COHERENT_IN_PROGRESS)
        assert CHECK.run(context) == []

    def test_complete_status_with_all_checked_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _COMPLETE_ALL_CHECKED)
        assert CHECK.run(context) == []

    def test_not_started_with_all_checked_blocks(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _NOT_STARTED_ALL_CHECKED)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "header-body-coherence"
        assert finding.level == Level.BLOCK
        assert "Complete" in finding.remediation

    def test_in_progress_with_done_marker_blocks(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _IN_PROGRESS_DONE_MARKER)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK

    def test_legacy_allowlisted_plan_advises_instead(self) -> None:
        context = _context(
            "CLAUDE/Plan/00042-widget/PLAN.md",
            _NOT_STARTED_ALL_CHECKED,
            exists_before=True,
            legacy=frozenset({42}),
        )
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
