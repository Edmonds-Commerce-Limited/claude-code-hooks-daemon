"""Tests for plan_qa.checks.common — shared edit-target helpers (Plan 00144)."""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.common import edit_target, level_for_plan
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level

_ROOT = Path("/repo")
_PLAN_CONTENT = "# Plan 00042: Widget\n\n**Status**: In Progress\n"


def _context(file_rel: str | None, content: str | None = _PLAN_CONTENT) -> CheckContext:
    return CheckContext(
        project_root=_ROOT,
        plan_dir_rel="CLAUDE/Plan",
        file_path=None if file_rel is None else _ROOT / file_rel,
        file_content=content,
    )


class TestEditTarget:
    def test_plan_md_in_root_plan_folder(self) -> None:
        target = edit_target(_context("CLAUDE/Plan/00042-widget/PLAN.md"))
        assert target is not None
        assert target.plan_number == 42
        assert target.in_archive is False
        assert target.doc.plan_number == 42
        assert target.rel_path == "CLAUDE/Plan/00042-widget/PLAN.md"

    def test_plan_md_in_completed_is_archive(self) -> None:
        target = edit_target(_context("CLAUDE/Plan/Completed/00042-widget/PLAN.md"))
        assert target is not None
        assert target.in_archive is True

    def test_plan_md_in_cancelled_is_archive(self) -> None:
        target = edit_target(_context("CLAUDE/Plan/Cancelled/00042-widget/PLAN.md"))
        assert target is not None
        assert target.in_archive is True

    def test_none_when_not_plan_md(self) -> None:
        assert edit_target(_context("CLAUDE/Plan/00042-widget/notes.md")) is None

    def test_none_when_outside_plan_dir(self) -> None:
        assert edit_target(_context("docs/PLAN.md")) is None

    def test_none_when_no_file_in_context(self) -> None:
        assert edit_target(_context(None)) is None

    def test_none_when_no_content(self) -> None:
        assert edit_target(_context("CLAUDE/Plan/00042-widget/PLAN.md", content=None)) is None

    def test_plan_number_none_for_unnumbered_folder(self) -> None:
        target = edit_target(_context("CLAUDE/Plan/scratch-notes/PLAN.md"))
        assert target is not None
        assert target.plan_number is None


class TestLevelForPlan:
    def test_blocks_by_default(self) -> None:
        assert level_for_plan(_context(None), 42) == Level.BLOCK

    def test_advises_for_allowlisted_legacy_plan(self) -> None:
        context = CheckContext(
            project_root=_ROOT,
            plan_dir_rel="CLAUDE/Plan",
            legacy_plan_allowlist=frozenset({42}),
        )
        assert level_for_plan(context, 42) == Level.ADVISE

    def test_blocks_for_unknown_number(self) -> None:
        assert level_for_plan(_context(None), None) == Level.BLOCK
