"""Tests for the row-folder-bijection tree check (Plan 00144; sins B1, B2, B7)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks.row_folder_bijection import CHECKS
from claude_code_hooks_daemon.plan_qa.model import PlanTree
from claude_code_hooks_daemon.plan_qa.readme_index import ReadmeIndex
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"


def _make_folder(root: Path, name: str, sub: str = "") -> None:
    parent = root / sub if sub else root
    parent.mkdir(parents=True, exist_ok=True)
    folder = parent / name
    folder.mkdir()
    number = name.split("-")[0]
    (folder / "PLAN.md").write_text(f"# Plan {number}: Widget\n\n**Status**: In Progress\n")


def _context(
    tmp_path: Path,
    readme_text: str,
    legacy_plan_allowlist: frozenset[int] = frozenset(),
) -> CheckContext:
    return CheckContext(
        project_root=tmp_path,
        plan_dir_rel=_PLAN_DIR_REL,
        tree=PlanTree.scan(tmp_path / _PLAN_DIR_REL),
        readme=ReadmeIndex.parse(readme_text),
        legacy_plan_allowlist=legacy_plan_allowlist,
    )


@pytest.fixture
def plan_root(tmp_path: Path) -> Path:
    root = tmp_path / _PLAN_DIR_REL
    root.mkdir(parents=True)
    (root / "Completed").mkdir()
    return root


class TestSpec:
    def test_both_specs_share_id_and_metadata(self) -> None:
        commit_spec, sweep_spec = CHECKS
        assert commit_spec.check_id == "row-folder-bijection"
        assert sweep_spec.check_id == "row-folder-bijection"
        assert {commit_spec.stage, sweep_spec.stage} == {Stage.COMMIT, Stage.SWEEP}
        assert commit_spec.level == Level.BLOCK
        assert commit_spec.sins == ("B1", "B2", "B7")
        assert commit_spec.run is sweep_spec.run


class TestTreeOrReadmeNone:
    def test_returns_empty_when_tree_missing(self) -> None:
        context = CheckContext(
            project_root=Path("/repo"),
            plan_dir_rel=_PLAN_DIR_REL,
            readme=ReadmeIndex.parse("## Active Plans\n"),
        )
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_returns_empty_when_readme_missing(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        context = CheckContext(
            project_root=tmp_path,
            plan_dir_rel=_PLAN_DIR_REL,
            tree=PlanTree.scan(plan_root),
        )
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestClean:
    def test_matching_row_and_folder_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        readme = "## Active Plans\n\n- [00001: Alpha](00001-alpha/PLAN.md) - In Progress\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_completed_folder_in_completed_section_passes(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        _make_folder(plan_root, "00001-alpha", sub="Completed")
        readme = (
            "## Completed Plans\n\n- [00001: Alpha](Completed/00001-alpha/PLAN.md) - Complete\n"
        )
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_other_location_folders_ignored(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", sub="Scratch")
        context = _context(tmp_path, "## Active Plans\n")
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestUnindexedFolder:
    def test_folder_with_no_row_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        context = _context(tmp_path, "## Active Plans\n")
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert "no README index row" in findings[0].message
        assert findings[0].level == Level.BLOCK

    def test_legacy_allowlist_downgrades_unindexed(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        context = _context(tmp_path, "## Active Plans\n", legacy_plan_allowlist=frozenset({1}))
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


class TestWrongSection:
    def test_root_folder_indexed_under_completed_blocks(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        _make_folder(plan_root, "00001-alpha")
        readme = "## Completed Plans\n\n- [00001: Alpha](00001-alpha/PLAN.md) - Complete\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert "section" in findings[0].message.lower()
        assert findings[0].level == Level.BLOCK


class TestBrokenLink:
    def test_link_to_missing_folder_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        readme = "## Active Plans\n\n- [00002: Ghost](00002-ghost/PLAN.md) - In Progress\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        messages = [f.message for f in findings]
        assert any("does not exist" in message for message in messages)


class TestOrphanRow:
    def test_row_with_no_folder_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        readme = "## Blocked Plans\n\n- **00099** - Waiting on approval\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert any("no folder" in f.message for f in findings)

    def test_legacy_allowlist_downgrades_orphan_row(self, plan_root: Path, tmp_path: Path) -> None:
        readme = "## Blocked Plans\n\n- **00099** - Waiting on approval\n"
        context = _context(tmp_path, readme, legacy_plan_allowlist=frozenset({99}))
        commit_spec, _sweep_spec = CHECKS
        findings = [f for f in commit_spec.run(context) if "no folder" in f.message]
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
