"""Tests for the dormant-honesty check (Plan 00144; sin A6)."""

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.dormant_honesty import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.model import PlanTree
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"
_TODAY = date(2026, 7, 1)


def _git(repo: Path, *args: str, commit_date: str | None = None) -> None:
    env = None
    if commit_date is not None:
        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = commit_date
        env["GIT_COMMITTER_DATE"] = commit_date
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
        env=env,
    )


def _make_plan(repo: Path, folder_name: str, status: str, commit_date: str) -> None:
    plan_dir = repo / _PLAN_DIR_REL / folder_name
    plan_dir.mkdir(parents=True)
    number = folder_name.split("-", 1)[0]
    (plan_dir / "PLAN.md").write_text(f"# Plan {number}: {folder_name}\n\n**Status**: {status}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"add {folder_name}", commit_date=commit_date)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    (root / _PLAN_DIR_REL).mkdir(parents=True)
    (root / _PLAN_DIR_REL / "README.md").write_text("# Plans Index\n\n## Active Plans\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial", commit_date="2026-01-01T12:00:00")
    return root


def _context(root: Path, staleness_days: int = 30) -> CheckContext:
    tree = PlanTree.scan(root / _PLAN_DIR_REL)
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        staleness_days=staleness_days,
        gitfacts=GitFacts(root),
        tree=tree,
        today=_TODAY,
    )


class TestSpec:
    def test_registered_for_sweep_stage(self) -> None:
        assert CHECK.check_id == "dormant-honesty"
        assert CHECK.stage == Stage.SWEEP
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("A6",)


class TestPreconditions:
    def test_no_tree_returns_empty(self) -> None:
        context = CheckContext(
            project_root=Path("/repo"),
            plan_dir_rel=_PLAN_DIR_REL,
            gitfacts=None,
            tree=None,
            today=_TODAY,
        )
        assert CHECK.run(context) == []

    def test_no_gitfacts_returns_empty(self, repo: Path) -> None:
        tree = PlanTree.scan(repo / _PLAN_DIR_REL)
        context = CheckContext(
            project_root=repo,
            plan_dir_rel=_PLAN_DIR_REL,
            gitfacts=None,
            tree=tree,
            today=_TODAY,
        )
        assert CHECK.run(context) == []

    def test_no_today_returns_empty(self, repo: Path) -> None:
        tree = PlanTree.scan(repo / _PLAN_DIR_REL)
        context = CheckContext(
            project_root=repo,
            plan_dir_rel=_PLAN_DIR_REL,
            gitfacts=GitFacts(repo),
            tree=tree,
            today=None,
        )
        assert CHECK.run(context) == []


class TestFindings:
    def test_recently_active_in_progress_is_clean(self, repo: Path) -> None:
        _make_plan(repo, "00001-active", "In Progress", "2026-06-25T12:00:00")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_stale_but_not_double_threshold_is_clean(self, repo: Path) -> None:
        # 30 days stale, threshold for dormant-honesty is 2x staleness_days (60).
        _make_plan(repo, "00001-stale", "In Progress", "2026-05-15T12:00:00")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_double_stale_in_progress_advises(self, repo: Path) -> None:
        _make_plan(repo, "00001-ancient", "In Progress", "2026-01-01T12:00:00")
        context = _context(repo)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "dormant-honesty"
        assert finding.level == Level.ADVISE
        assert "00001-ancient" in finding.message
        assert "Dormant" in finding.remediation

    def test_non_in_progress_status_is_ignored(self, repo: Path) -> None:
        _make_plan(repo, "00001-blocked", "Blocked", "2026-01-01T12:00:00")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_one_finding_per_plan(self, repo: Path) -> None:
        _make_plan(repo, "00001-ancient", "In Progress", "2026-01-01T12:00:00")
        _make_plan(repo, "00002-ancient-too", "In Progress", "2026-01-02T12:00:00")
        context = _context(repo)
        findings = CHECK.run(context)
        assert len(findings) == 2
