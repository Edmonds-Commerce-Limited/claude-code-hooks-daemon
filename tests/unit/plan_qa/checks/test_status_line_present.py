"""Tests for the status-line-present check (Plan 00144; sins A2, E8).

This check is the EXEMPLAR for the Stage 1 catalogue: every edit-time check
follows the same shape — applies only to PLAN.md content under the plan dir,
blocks new material, advises on grandfathered legacy plans.
"""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.status_line_present import CHECK
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PROJECT_ROOT = Path("/repo")
_PLAN_DIR_REL = "CLAUDE/Plan"

_VALID_PLAN = "# Plan 00042: Widget\n\n**Status**: In Progress\n\n- [ ] task\n"
_NO_STATUS_PLAN = "# Plan 00042: Widget\n\n## Progress\n\n- [x] did things\n"


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
        assert CHECK.check_id == "status-line-present"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.BLOCK
        assert "A2" in CHECK.sins


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/notes.md", _NO_STATUS_PLAN)
        assert CHECK.run(context) == []

    def test_ignores_plan_md_outside_plan_dir(self) -> None:
        context = _context("docs/PLAN.md", _NO_STATUS_PLAN)
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self) -> None:
        context = CheckContext(project_root=_PROJECT_ROOT, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []


class TestFindings:
    def test_valid_status_line_passes(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _VALID_PLAN)
        assert CHECK.run(context) == []

    def test_missing_status_line_blocks_new_material(self) -> None:
        context = _context("CLAUDE/Plan/00042-widget/PLAN.md", _NO_STATUS_PLAN)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "status-line-present"
        assert finding.level == Level.BLOCK
        assert "**Status**:" in finding.remediation

    def test_legacy_allowlisted_plan_advises_instead(self) -> None:
        context = _context(
            "CLAUDE/Plan/00042-widget/PLAN.md",
            _NO_STATUS_PLAN,
            exists_before=True,
            legacy=frozenset({42}),
        )
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_archived_plan_md_is_still_checked(self) -> None:
        context = _context("CLAUDE/Plan/Completed/00042-widget/PLAN.md", _NO_STATUS_PLAN)
        findings = CHECK.run(context)
        assert len(findings) == 1
