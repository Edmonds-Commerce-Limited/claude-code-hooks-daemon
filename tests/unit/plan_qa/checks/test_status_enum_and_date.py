"""Tests for the status-enum-and-date check (Plan 00144; sin A1).

Every check module follows the exemplar shape from
``test_status_line_present.py``: applies only to PLAN.md content under the
plan dir, blocks new material, advises on grandfathered legacy plans.
"""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.status_enum_and_date import CHECKS
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

# These tests exercise the edit-time surface; the sweep twin is covered by
# tests/unit/plan_qa/checks/test_document_rule_stage_parity.py.
CHECK = CHECKS.edit

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_VALID_PLAN = "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [ ] task\n"
_BAD_STATUS_PLAN = "# Plan 00042: Widget\n\n**Status**: Doneish\n\n- [ ] task\n"
_NO_STATUS_PLAN = "# Plan 00042: Widget\n\n## Progress\n\n- [x] did things\n"
_TERMINAL_NO_DATE_PLAN = "# Plan 00042: Widget\n\n**Status**: Complete\n\n- [x] task\n"
_TERMINAL_WITH_DATE_PLAN = (
    "# Plan 00042: Widget\n\n**Status**: Complete (2026-06-30)\n\n- [x] task\n"
)


def _context(
    file_rel: str,
    content: str,
    exists_before: bool = False,
    legacy: frozenset[int] = frozenset(),
    require_terminal_date: bool = False,
) -> CheckContext:
    return CheckContext(
        project_root=_PROJECT_ROOT,
        plan_dir_rel=_PLAN_DIR_REL,
        legacy_plan_allowlist=legacy,
        file_path=_PROJECT_ROOT / file_rel,
        file_content=content,
        file_exists_before=exists_before,
        require_terminal_date=require_terminal_date,
    )


class TestSpec:
    def test_registered_for_edit_stage(self) -> None:
        assert CHECK.check_id == "status-enum-and-date"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.BLOCK
        assert CHECK.sins == ("A1",)


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/notes.md", _BAD_STATUS_PLAN)
        assert CHECK.run(context) == []

    def test_ignores_when_no_status_line_present(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _NO_STATUS_PLAN)
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []


class TestFindings:
    def test_valid_status_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _VALID_PLAN)
        assert CHECK.run(context) == []

    def test_unrecognised_status_token_blocks_new_material(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _BAD_STATUS_PLAN)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "status-enum-and-date"
        assert finding.level == Level.BLOCK
        assert "Doneish" in finding.message
        assert "Not Started" in finding.remediation

    def test_unrecognised_status_token_advises_on_legacy_plan(self) -> None:
        context = _context(
            "CLAUDE/Plan/00042-widget/PLAN.md",
            _BAD_STATUS_PLAN,
            exists_before=True,
            legacy=frozenset({42}),
        )
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_terminal_status_without_date_passes_when_dates_not_required(self) -> None:
        context = _context(
            "CLAUDE/Plan/00042-widget/PLAN.md",
            _TERMINAL_NO_DATE_PLAN,
            require_terminal_date=False,
        )
        assert CHECK.run(context) == []

    def test_terminal_status_without_date_blocks_when_required(self) -> None:
        context = _context(
            "CLAUDE/Plan/00042-widget/PLAN.md",
            _TERMINAL_NO_DATE_PLAN,
            require_terminal_date=True,
        )
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK
        assert "YYYY-MM-DD" in findings[0].remediation

    def test_terminal_status_with_date_passes_when_required(self) -> None:
        context = _context(
            "CLAUDE/Plan/00042-widget/PLAN.md",
            _TERMINAL_WITH_DATE_PLAN,
            require_terminal_date=True,
        )
        assert CHECK.run(context) == []

    def test_both_findings_can_fire_together(self) -> None:
        bad_terminal = "# Plan 00042: Widget\n\n**Status**: Doneish\n\n- [x] task\n"
        context = _context(
            "CLAUDE/Plan/00042-widget/PLAN.md",
            bad_terminal,
            require_terminal_date=True,
        )
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK
