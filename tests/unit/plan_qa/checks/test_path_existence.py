"""Tests for the path-existence check (Plan 00144; sin E5)."""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks.path_existence import CHECK
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"


def _context(project_root: Path, file_rel: str, content: str) -> CheckContext:
    return CheckContext(
        project_root=project_root,
        plan_dir_rel=_PLAN_DIR_REL,
        file_path=project_root / file_rel,
        file_content=content,
    )


class TestSpec:
    def test_registered_for_edit_stage(self) -> None:
        assert CHECK.check_id == "path-existence"
        assert CHECK.stage == Stage.EDIT
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("E5",)


class TestMatchesScope:
    def test_ignores_non_plan_md_files(self, tmp_path: Path) -> None:
        content = "See `src/missing.py` for details.\n"
        context = _context(tmp_path, "CLAUDE/Plan/00042-widget/notes.md", content)
        assert CHECK.run(context) == []

    def test_ignores_non_edit_context(self, tmp_path: Path) -> None:
        context = CheckContext(project_root=tmp_path, plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []

    def test_ignores_archived_plans(self, tmp_path: Path) -> None:
        content = "See `src/missing.py` for details.\n"
        context = _context(tmp_path, "CLAUDE/Plan/Completed/00042-widget/PLAN.md", content)
        assert CHECK.run(context) == []


class TestFindings:
    def test_existing_path_passes(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        (source_dir / "present.py").write_text("x = 1\n")
        content = "# Plan 00042: Widget\n\nSee `src/present.py` for details.\n"
        context = _context(tmp_path, "CLAUDE/Plan/00042-widget/PLAN.md", content)
        assert CHECK.run(context) == []

    def test_missing_path_advises(self, tmp_path: Path) -> None:
        content = "# Plan 00042: Widget\n\nSee `src/missing.py` for details.\n"
        context = _context(tmp_path, "CLAUDE/Plan/00042-widget/PLAN.md", content)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "path-existence"
        assert finding.level == Level.ADVISE
        assert "src/missing.py" in finding.message

    def test_non_path_like_inline_code_is_ignored(self, tmp_path: Path) -> None:
        content = "# Plan 00042: Widget\n\nRun `pytest -q` and check `foo()`.\n"
        context = _context(tmp_path, "CLAUDE/Plan/00042-widget/PLAN.md", content)
        assert CHECK.run(context) == []

    def test_ignores_paths_inside_fenced_code_blocks(self, tmp_path: Path) -> None:
        content = "# Plan 00042: Widget\n\n```\nsrc/missing.py\n```\n"
        context = _context(tmp_path, "CLAUDE/Plan/00042-widget/PLAN.md", content)
        assert CHECK.run(context) == []

    def test_duplicate_missing_paths_are_deduped_and_ordered(self, tmp_path: Path) -> None:
        content = "# Plan 00042: Widget\n\n" "See `src/a.py` and `src/b.py` and `src/a.py` again.\n"
        context = _context(tmp_path, "CLAUDE/Plan/00042-widget/PLAN.md", content)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert "src/a.py" in findings[0].message
        assert "src/b.py" in findings[0].message
        assert findings[0].message.index("src/a.py") < findings[0].message.index("src/b.py")

    def test_missing_path_list_is_capped(self, tmp_path: Path) -> None:
        paths = " ".join(f"`src/missing{i}.py`" for i in range(15))
        content = f"# Plan 00042: Widget\n\n{paths}\n"
        context = _context(tmp_path, "CLAUDE/Plan/00042-widget/PLAN.md", content)
        findings = CHECK.run(context)
        assert len(findings) == 1
        assert findings[0].message.count("src/missing") == 10
