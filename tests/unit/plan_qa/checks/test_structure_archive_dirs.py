"""Tests for the structure-archive-dirs tree check (Plan 00144; sin C3)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks.structure_archive_dirs import CHECKS
from claude_code_hooks_daemon.plan_qa.model import PlanTree
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
    cancelled_dir: str | None = "Cancelled",
    legacy_plan_allowlist: frozenset[int] = frozenset(),
) -> CheckContext:
    return CheckContext(
        project_root=tmp_path,
        plan_dir_rel=_PLAN_DIR_REL,
        cancelled_dir=cancelled_dir,
        legacy_plan_allowlist=legacy_plan_allowlist,
        tree=PlanTree.scan(tmp_path / _PLAN_DIR_REL, cancelled_dir=cancelled_dir),
    )


@pytest.fixture
def plan_root(tmp_path: Path) -> Path:
    root = tmp_path / _PLAN_DIR_REL
    root.mkdir(parents=True)
    (root / "README.md").write_text("# Plans\n")
    (root / "Completed").mkdir()
    (root / "Cancelled").mkdir()
    return root


class TestSpec:
    def test_both_specs_share_id_and_metadata(self) -> None:
        commit_spec, sweep_spec = CHECKS
        assert commit_spec.check_id == "structure-archive-dirs"
        assert sweep_spec.check_id == "structure-archive-dirs"
        assert {commit_spec.stage, sweep_spec.stage} == {Stage.COMMIT, Stage.SWEEP}
        assert commit_spec.level == Level.BLOCK
        assert commit_spec.sins == ("C3",)
        assert commit_spec.run is sweep_spec.run


class TestTreeNone:
    def test_returns_empty_when_tree_missing(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel=_PLAN_DIR_REL)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestClean:
    def test_well_formed_tree_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestMissingReadme:
    def test_missing_readme_blocks(self, tmp_path: Path) -> None:
        root = tmp_path / _PLAN_DIR_REL
        root.mkdir(parents=True)
        (root / "Completed").mkdir()
        (root / "Cancelled").mkdir()
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert any("README.md" in f.remediation for f in findings)
        assert all(f.level == Level.BLOCK for f in findings if "README.md" in f.remediation)


class TestMissingCompletedDir:
    def test_missing_completed_dir_blocks(self, tmp_path: Path) -> None:
        root = tmp_path / _PLAN_DIR_REL
        root.mkdir(parents=True)
        (root / "README.md").write_text("# Plans\n")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert any("mkdir" in f.remediation and "Completed" in f.remediation for f in findings)


class TestMissingCancelledDir:
    def test_missing_optional_cancelled_dir_advises(self, tmp_path: Path) -> None:
        root = tmp_path / _PLAN_DIR_REL
        root.mkdir(parents=True)
        (root / "README.md").write_text("# Plans\n")
        (root / "Completed").mkdir()
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = [f for f in commit_spec.run(context) if "Cancelled" in f.remediation]
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_cancelled_dir_not_configured_is_not_required(self, tmp_path: Path) -> None:
        root = tmp_path / _PLAN_DIR_REL
        root.mkdir(parents=True)
        (root / "README.md").write_text("# Plans\n")
        (root / "Completed").mkdir()
        context = _context(tmp_path, cancelled_dir=None)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestOtherLocationFolders:
    def test_folder_outside_root_and_archive_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", sub="Scratch")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert "git mv" in findings[0].remediation
        assert findings[0].level == Level.BLOCK

    def test_legacy_allowlist_downgrades_other_location(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        _make_folder(plan_root, "00001-alpha", sub="Scratch")
        context = _context(tmp_path, legacy_plan_allowlist=frozenset({1}))
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


class TestStrayFiles:
    def test_stray_file_at_root_advises(self, plan_root: Path, tmp_path: Path) -> None:
        (plan_root / "notes.txt").write_text("scratch\n")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
        assert "notes.txt" in (findings[0].path or "")
