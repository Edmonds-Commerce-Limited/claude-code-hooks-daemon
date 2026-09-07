"""Tests for the stats-recount tree check (Plan 00144; sin B5)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.stats_recount import CHECKS
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
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


def _context(tmp_path: Path, readme_text: str) -> CheckContext:
    return CheckContext(
        project_root=tmp_path,
        plan_dir_rel=_PLAN_DIR_REL,
        tree=PlanTree.scan(tmp_path / _PLAN_DIR_REL),
        readme=ReadmeIndex.parse(readme_text),
    )


@pytest.fixture
def plan_root(tmp_path: Path) -> Path:
    root = tmp_path / _PLAN_DIR_REL
    root.mkdir(parents=True)
    (root / "Completed").mkdir()
    return root


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


_UNDERCOUNTING_README = (
    "# Plans\n\n## Plan Statistics\n\n- **Total Plans Created**: 1 (git counter)\n"
)


def _repo_with_drift(tmp_path: Path) -> Path:
    """A repository whose HEAD already understates the plan count."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    plan_root = root / _PLAN_DIR_REL
    plan_root.mkdir(parents=True)
    _make_folder(plan_root, "00001-alpha")
    _make_folder(plan_root, "00002-beta")
    (plan_root / "README.md").write_text(_UNDERCOUNTING_README)
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _total_levels(root: Path) -> list[Level]:
    plan_root = root / _PLAN_DIR_REL
    context = CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        tree=PlanTree.scan(plan_root),
        readme=ReadmeIndex.parse((plan_root / "README.md").read_text()),
        gitfacts=GitFacts(root),
    )
    commit_spec, _sweep_spec = CHECKS
    return [f.level for f in commit_spec.run(context) if "plan folders exist on disk" in f.message]


class TestOnlyACommitThatChangesTheFolderSetIsBlamed:
    """Plan 00343 Phase 3 — the count can only be wrong because of a folder.

    Statistics drift is real whenever it exists, but an ordinary source commit
    cannot have caused it and cannot be expected to fix it. Only a commit that
    adds, removes or moves a plan folder changes what the recount produces.
    """

    def test_drift_this_commit_inherited_only_advises(self, tmp_path: Path) -> None:
        root = _repo_with_drift(tmp_path)
        (root / "src" / "thing.py").write_text("x = 1\n")
        _git(root, "add", "-A")

        assert _total_levels(root) == [Level.ADVISE]

    def test_a_commit_that_adds_a_plan_folder_still_blocks(self, tmp_path: Path) -> None:
        root = _repo_with_drift(tmp_path)
        _make_folder(root / _PLAN_DIR_REL, "00003-gamma")
        _git(root, "add", "-A")

        assert _total_levels(root) == [Level.BLOCK]


class TestSpec:
    def test_both_specs_share_id_and_metadata(self) -> None:
        commit_spec, sweep_spec = CHECKS
        assert commit_spec.check_id == "stats-recount"
        assert sweep_spec.check_id == "stats-recount"
        assert {commit_spec.stage, sweep_spec.stage} == {Stage.COMMIT, Stage.SWEEP}
        assert commit_spec.level == Level.BLOCK
        assert commit_spec.sins == ("B5",)
        assert commit_spec.run is sweep_spec.run


class TestNoop:
    def test_returns_empty_when_tree_missing(self) -> None:
        context = CheckContext(
            project_root=Path("/repo"),
            plan_dir_rel=_PLAN_DIR_REL,
            readme=ReadmeIndex.parse("## Statistics\n\n- **Total**: 1\n"),
        )
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_returns_empty_when_readme_missing(self, plan_root: Path, tmp_path: Path) -> None:
        context = CheckContext(
            project_root=tmp_path,
            plan_dir_rel=_PLAN_DIR_REL,
            tree=PlanTree.scan(plan_root),
        )
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_returns_empty_when_stats_empty(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        context = _context(tmp_path, "## Active Plans\n\n- [00001: Alpha](00001-alpha/PLAN.md)\n")
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestTotal:
    def test_matching_total_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        readme = "## Statistics\n\n- **Total**: 1 (all time)\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_total_higher_than_folder_count_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        readme = "## Statistics\n\n- **Total**: 5 (all time)\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_total_undercount_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        _make_folder(plan_root, "00002-beta")
        readme = "## Statistics\n\n- **Total**: 1 (all time)\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.BLOCK
        assert "Total" in findings[0].message


class TestCategoryCounts:
    def test_active_mismatch_advises(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha")
        readme = "## Statistics\n\n- **Active**: 5\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
        assert "Active" in findings[0].message

    def test_completed_mismatch_advises(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", sub="Completed")
        readme = "## Statistics\n\n- **Completed**: 0\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE

    def test_cancelled_matching_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", sub="Cancelled")
        readme = "## Statistics\n\n- **Cancelled**: 1\n"
        context = _context(tmp_path, readme)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []
