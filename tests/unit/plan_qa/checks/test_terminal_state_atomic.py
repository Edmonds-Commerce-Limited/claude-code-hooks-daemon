"""Tests for the terminal-state-atomic check (Plan 00144; sins C1, C2, C3, B3)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.terminal_state_atomic import CHECK
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_PLAN_DIR_REL = "CLAUDE/Plan"

_IN_PROGRESS = "# Plan 00001: first\n\n**Status**: In Progress\n"
_COMPLETE = "# Plan 00001: first\n\n**Status**: Complete\n"
_CANCELLED = "# Plan 00001: first\n\n**Status**: Cancelled\n"


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
    plan_dir = root / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "README.md").write_text("# Plans Index\n\n## Active Plans\n")
    (plan_dir / "00001-first").mkdir()
    (plan_dir / "00001-first" / "PLAN.md").write_text(_IN_PROGRESS)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _context(root: Path, legacy: frozenset[int] = frozenset()) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        legacy_plan_allowlist=legacy,
        gitfacts=GitFacts(root),
    )


class TestSpec:
    def test_registered_for_commit_stage(self) -> None:
        assert CHECK.check_id == "terminal-state-atomic"
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.BLOCK
        assert set(CHECK.sins) == {"C1", "C2", "C3", "B3"}


class TestScope:
    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []

    def test_no_staged_changes_is_clean(self, repo: Path) -> None:
        assert CHECK.run(_context(repo)) == []

    def test_non_terminal_edit_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(
            "# Plan 00001: first\n\n**Status**: In Progress\n\n- [x] did a thing\n"
        )
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []


class TestFlipWithoutMove:
    def test_terminal_flip_still_in_root_without_readme_blocks(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE)
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "terminal-state-atomic"
        assert finding.level == Level.BLOCK
        assert (
            "git mv CLAUDE/Plan/00001-first CLAUDE/Plan/Completed/00001-first"
            in finding.remediation
        )
        assert "README" in finding.remediation

    def test_terminal_flip_with_readme_staged_omits_readme_item(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE)
        (repo / "CLAUDE/Plan/README.md").write_text("# Plans Index (updated)\n")
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        assert "git mv" in findings[0].remediation
        assert "README" not in findings[0].remediation

    def test_cancelled_flip_uses_cancelled_dir(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_CANCELLED)
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        assert "CLAUDE/Plan/Cancelled/00001-first" in findings[0].remediation

    def test_already_terminal_at_head_is_not_reflagged(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "mark complete but forget to move")
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE + "\n- [x] extra note\n")
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []

    def test_legacy_allowlisted_downgrades_to_advise(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE)
        _git(repo, "add", "-A")
        findings = CHECK.run(_context(repo, legacy=frozenset({1})))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE


class TestMoveWithoutReadme:
    def test_rename_into_completed_without_readme_blocks(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "mark complete")
        completed = repo / "CLAUDE/Plan/Completed"
        completed.mkdir()
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        assert "README" in findings[0].message or "README" in findings[0].remediation

    def test_rename_into_completed_with_readme_staged_is_clean(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(_COMPLETE)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "mark complete")
        completed = repo / "CLAUDE/Plan/Completed"
        completed.mkdir()
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        (repo / "CLAUDE/Plan/README.md").write_text("# Plans Index (updated)\n")
        _git(repo, "add", "-A")
        assert CHECK.run(_context(repo)) == []
