"""Tests for the location-status-coherence tree check (Plan 00144; sins A1, A5, C1, C2, E8)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.location_status_coherence import CHECKS
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.model import PlanTree
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"


def _make_folder(root: Path, name: str, content: str | None, sub: str = "") -> Path:
    parent = root / sub if sub else root
    parent.mkdir(parents=True, exist_ok=True)
    folder = parent / name
    folder.mkdir()
    if content is not None:
        (folder / "PLAN.md").write_text(content)
    return folder


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
    (root / "Completed").mkdir()
    (root / "Cancelled").mkdir()
    return root


_IN_PROGRESS = "# Plan 00001: Widget\n\n**Status**: In Progress\n"
_COMPLETE = "# Plan 00001: Widget\n\n**Status**: Complete\n"
_CANCELLED = "# Plan 00001: Widget\n\n**Status**: Cancelled\n"
_NO_STATUS = "# Plan 00001: Widget\n\nSome prose, no status header.\n"


class TestSpec:
    def test_both_specs_share_id_and_metadata(self) -> None:
        commit_spec, sweep_spec = CHECKS
        assert commit_spec.check_id == "location-status-coherence"
        assert sweep_spec.check_id == "location-status-coherence"
        assert {commit_spec.stage, sweep_spec.stage} == {Stage.COMMIT, Stage.SWEEP}
        assert commit_spec.level == Level.BLOCK
        assert commit_spec.sins == ("A1", "A5", "C1", "C2", "E8")
        assert commit_spec.run is sweep_spec.run


class TestTreeNone:
    def test_returns_empty_when_tree_missing(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel=_PLAN_DIR_REL)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestClean:
    def test_active_in_progress_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", _IN_PROGRESS)
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_archived_complete_passes(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", _COMPLETE, sub="Completed")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []

    def test_other_location_ignored(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", _IN_PROGRESS, sub="Scratch")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        assert commit_spec.run(context) == []


class TestMissingPlanMd:
    def test_folder_without_plan_md_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", None)
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert "no PLAN.md" in findings[0].message
        assert findings[0].level == Level.BLOCK

    def test_legacy_allowlist_downgrades_missing_plan_md(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        _make_folder(plan_root, "00001-alpha", None)
        context = _context(tmp_path, legacy_plan_allowlist=frozenset({1}))
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


class TestMissingStatusLine:
    def test_missing_status_line_advises(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", _NO_STATUS)
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


class TestTerminalLoitering:
    def test_complete_plan_in_root_blocks(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", _COMPLETE)
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert "git mv" in findings[0].remediation
        assert "Completed" in findings[0].remediation
        assert findings[0].level == Level.BLOCK

    def test_cancelled_plan_in_root_names_cancelled_dir(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        _make_folder(plan_root, "00001-alpha", _CANCELLED)
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert "Cancelled" in findings[0].remediation

    def test_legacy_allowlist_downgrades_loitering(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", _COMPLETE)
        context = _context(tmp_path, legacy_plan_allowlist=frozenset({1}))
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


class TestStaleArchivedHeader:
    def test_in_progress_in_completed_dir_advises(self, plan_root: Path, tmp_path: Path) -> None:
        _make_folder(plan_root, "00001-alpha", _IN_PROGRESS, sub="Completed")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
        assert "status header" in findings[0].message

    def test_not_started_in_cancelled_dir_advises(self, plan_root: Path, tmp_path: Path) -> None:
        content = "# Plan 00001: Widget\n\n**Status**: Not Started\n"
        _make_folder(plan_root, "00001-alpha", content, sub="Cancelled")
        context = _context(tmp_path)
        commit_spec, _sweep_spec = CHECKS
        findings = commit_spec.run(context)
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


# Distinct names, NOT a second _IN_PROGRESS/_COMPLETE: a redefinition lower in
# the module silently rebinds the constants every test above also reads.
_REPO_IN_PROGRESS = "# Plan 00304: Widget\n\n**Status**: In Progress\n"
_REPO_COMPLETE = "# Plan 00304: Widget\n\n**Status**: Complete\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose HEAD holds one active, non-terminal plan."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    plan_root = root / _PLAN_DIR_REL
    plan_root.mkdir(parents=True)
    (plan_root / "Completed").mkdir()
    (plan_root / "Cancelled").mkdir()
    _make_folder(plan_root, "00304-widget", _REPO_IN_PROGRESS)
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _terminal_levels(root: Path) -> list[Level]:
    context = CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        tree=PlanTree.scan(root / _PLAN_DIR_REL, cancelled_dir="Cancelled"),
        gitfacts=GitFacts(root),
    )
    commit_spec, _sweep_spec = CHECKS
    return [f.level for f in commit_spec.run(context) if "still in the active root" in f.message]


class TestACommitIsAnswerableOnlyForThePlansItTouches:
    """Plan 00343 Phase 3 — the same narrowing as row-folder-bijection.

    Two of the eighteen would-be denials in the 250-commit replay were this
    check firing on plans 00304 and 00302, which had been left in the active
    root with a terminal header. The blamed commits were an error-hiding
    exclusions change and a php-qa-ci documentation change; neither touches
    either plan folder.
    """

    def test_a_plan_left_terminal_in_the_root_by_an_earlier_commit_only_advises(
        self, repo: Path
    ) -> None:
        (repo / _PLAN_DIR_REL / "00304-widget" / "PLAN.md").write_text(_REPO_COMPLETE)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "flip the status and forget the git mv")
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")

        assert _terminal_levels(repo) == [Level.ADVISE]

    def test_the_commit_that_flips_the_status_without_moving_still_blocks(self, repo: Path) -> None:
        (repo / _PLAN_DIR_REL / "00304-widget" / "PLAN.md").write_text(_REPO_COMPLETE)
        _git(repo, "add", "-A")

        assert _terminal_levels(repo) == [Level.BLOCK]

    def test_the_sweep_is_unchanged_because_it_has_no_commit_to_blame(
        self, plan_root: Path, tmp_path: Path
    ) -> None:
        _make_folder(plan_root, "00304-widget", _REPO_COMPLETE)
        _commit_spec, sweep_spec = CHECKS
        findings = [
            f for f in sweep_spec.run(_context(tmp_path)) if "still in the active root" in f.message
        ]

        assert [f.level for f in findings] == [Level.BLOCK]
