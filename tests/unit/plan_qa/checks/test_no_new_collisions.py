"""Tests for the no-new-collisions tree check (Plan 00144; sin D1)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks.no_new_collisions import CHECKS
from claude_code_hooks_daemon.plan_qa.model import PlanTree
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"


def _make_folder(root: Path, name: str) -> None:
    folder = root / name
    folder.mkdir()
    (folder / "PLAN.md").write_text(
        f"# Plan {name.split('-')[0]}: Widget\n\n**Status**: In Progress\n"
    )


def _context(
    tmp_path: Path,
    collision_allowlist: frozenset[int] = frozenset(),
    legacy_plan_allowlist: frozenset[int] = frozenset(),
) -> CheckContext:
    return CheckContext(
        project_root=tmp_path,
        plan_dir_rel=_PLAN_DIR_REL,
        tree=PlanTree.scan(tmp_path / _PLAN_DIR_REL),
        collision_allowlist=collision_allowlist,
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
        assert commit_spec.check_id == "no-new-collisions"
        assert sweep_spec.check_id == "no-new-collisions"
        assert {commit_spec.stage, sweep_spec.stage} == {Stage.COMMIT, Stage.SWEEP}
        assert commit_spec.level == Level.BLOCK
        assert sweep_spec.level == Level.BLOCK
        assert commit_spec.sins == ("D1",)
        assert sweep_spec.sins == ("D1",)
        assert commit_spec.run is sweep_spec.run


class TestTreeNone:
    def test_returns_empty_when_tree_missing(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel=_PLAN_DIR_REL)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestFindings:
    def test_clean_tree_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        _make_folder(plan_root, "00002-beta")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_collision_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        _make_folder(plan_root, "00001-beta")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "no-new-collisions"
        assert finding.level == Level.BLOCK
        assert "00001-alpha" in finding.message
        assert "00001-beta" in finding.message

    def test_collision_allowlist_suppresses_finding(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        _make_folder(plan_root, "00001-beta")
        context = _context(tmp_path, collision_allowlist=frozenset({1}))
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_legacy_allowlist_downgrades_to_advise(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        _make_folder(plan_root, "00001-beta")
        context = _context(tmp_path, legacy_plan_allowlist=frozenset({1}))
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_sweep_spec_runs_identically(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        _make_folder(plan_root, "00001-beta")
        context = _context(tmp_path)
        _commit_spec, sweep_spec = CHECKS
        findings = sweep_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK
