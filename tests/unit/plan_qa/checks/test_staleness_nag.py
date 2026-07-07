"""Tests for the staleness-nag check (Plan 00144; sins A4, A6, E3)."""

import subprocess
from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.staleness_nag import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.model import PlanTree
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"
_TODAY = date(2026, 7, 1)


def _git(repo: Path, *args: str, commit_date: str | None = None) -> None:
    """Run a git command in ``repo``, optionally pinning author/committer dates."""
    env = None
    if commit_date is not None:
        import os

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
        assert CHECK.check_id == "staleness-nag"
        assert CHECK.stage == Stage.SWEEP
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("A4", "A6", "E3")


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
    def test_no_stale_plans_is_clean(self, repo: Path) -> None:
        _make_plan(repo, "00001-fresh", "In Progress", "2026-06-25T12:00:00")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_stale_non_terminal_plan_advises(self, repo: Path) -> None:
        _make_plan(repo, "00001-stale", "In Progress", "2026-01-01T12:00:00")
        context = _context(repo)
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "staleness-nag"
        assert finding.level == Level.ADVISE
        assert "00001-stale" in finding.message
        assert "days since last commit" in finding.message

    def test_terminal_plan_is_ignored(self, repo: Path) -> None:
        _make_plan(repo, "00001-done", "Complete", "2026-01-01T12:00:00")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_only_in_progress_is_nagged(self, repo: Path) -> None:
        """Dogfooding decision (Plan 00144 Task 2.2): scope is In Progress ONLY.

        Not Started is honest backlog; Blocked/Dormant are declared
        inactivity — nagging them contradicts dormant-honesty's remediation
        and turns the sweep into ignorable noise.
        """
        _make_plan(repo, "00001-backlog", "Not Started", "2026-01-01T12:00:00")
        _make_plan(repo, "00002-blocked", "Blocked (upstream fix)", "2026-01-01T12:00:00")
        _make_plan(repo, "00003-dormant", "Dormant (awaiting review)", "2026-01-01T12:00:00")
        context = _context(repo)
        assert CHECK.run(context) == []

    def test_ranks_most_stale_first(self, repo: Path) -> None:
        _make_plan(repo, "00001-oldest", "In Progress", "2026-01-01T12:00:00")
        _make_plan(repo, "00002-newer-stale", "In Progress", "2026-05-01T12:00:00")
        context = _context(repo)
        findings = CHECK.run(context)
        assert len(findings) == 1
        message = findings[0].message
        oldest_pos = message.index("00001-oldest")
        newer_pos = message.index("00002-newer-stale")
        assert oldest_pos < newer_pos
