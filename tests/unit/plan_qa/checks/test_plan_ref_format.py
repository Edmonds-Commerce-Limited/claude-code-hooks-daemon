"""Tests for the plan-ref-format check (Plan 00144; sin G3)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.plan_ref_format import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    (root / "src").mkdir()
    plan_dir = root / "CLAUDE" / "Plan" / "00042-widget"
    plan_dir.mkdir(parents=True)
    (plan_dir / "PLAN.md").write_text("# Plan 00042: Widget\n\n**Status**: In Progress\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _context(root: Path, message: str | None) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        gitfacts=GitFacts(root),
        commit_message=message,
    )


class TestSpec:
    def test_registered_for_commit_stage(self) -> None:
        assert CHECK.check_id == "plan-ref-format"
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.ADVISE
        assert CHECK.sins == ("G3",)


class TestScope:
    def test_no_commit_message_returns_empty(self, repo: Path) -> None:
        context = CheckContext(
            project_root=repo, plan_dir_rel=_PLAN_DIR_REL, gitfacts=GitFacts(repo)
        )
        assert CHECK.run(context) == []

    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(
            project_root=Path("/repo"),
            plan_dir_rel=_PLAN_DIR_REL,
            commit_message="plan 42: did stuff",
        )
        assert CHECK.run(context) == []

    def test_no_staged_plan_dir_path_is_clean(self, repo: Path) -> None:
        (repo / "src" / "thing.py").write_text("x = 1\n")
        _git(repo, "add", "-A")
        context = _context(repo, "plan 42: unrelated wording")
        assert CHECK.run(context) == []


class TestFindings:
    def test_canonical_form_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00042-widget/PLAN.md").write_text(
            "# Plan 00042: Widget\n\n**Status**: Complete\n"
        )
        _git(repo, "add", "-A")
        context = _context(repo, "Plan 00042: mark complete")
        assert CHECK.run(context) == []

    def test_non_canonical_form_advises(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00042-widget/PLAN.md").write_text(
            "# Plan 00042: Widget\n\n**Status**: Complete\n"
        )
        _git(repo, "add", "-A")
        context = _context(repo, "plan 42: mark complete")
        findings = CHECK.run(context)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "plan-ref-format"
        assert finding.level == Level.ADVISE
        assert "NNNNN" in finding.remediation

    def test_no_plan_reference_at_all_advises(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00042-widget/PLAN.md").write_text(
            "# Plan 00042: Widget\n\n**Status**: Complete\n"
        )
        _git(repo, "add", "-A")
        context = _context(repo, "mark complete")
        findings = CHECK.run(context)
        assert len(findings) == 1
