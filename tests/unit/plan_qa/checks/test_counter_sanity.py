"""Tests for the counter-sanity check (Plan 00144; sin D1)."""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.checks.counter_sanity import CHECK
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
    plan_dir = root / "CLAUDE" / "Plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "README.md").write_text("# Plans Index\n\n## Active Plans\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _stage_new_plan(root: Path, folder: str) -> None:
    plan_folder = root / "CLAUDE" / "Plan" / folder
    plan_folder.mkdir(parents=True)
    (plan_folder / "PLAN.md").write_text(
        f"# Plan {folder.split('-')[0]}: x\n\n**Status**: Not Started\n"
    )
    _git(root, "add", "-A")


def _context(root: Path, legacy: frozenset[int] = frozenset()) -> CheckContext:
    return CheckContext(
        project_root=root,
        plan_dir_rel=_PLAN_DIR_REL,
        legacy_plan_allowlist=legacy,
        gitfacts=GitFacts(root),
    )


class TestSpec:
    def test_registered_for_commit_stage(self) -> None:
        assert CHECK.check_id == "counter-sanity"
        assert CHECK.stage == Stage.COMMIT
        assert CHECK.level == Level.BLOCK
        assert CHECK.sins == ("D1",)


class TestScope:
    def test_no_gitfacts_returns_empty(self) -> None:
        context = CheckContext(project_root=Path("/repo"), plan_dir_rel=_PLAN_DIR_REL)
        assert CHECK.run(context) == []

    def test_no_new_plan_folders_is_clean(self, repo: Path) -> None:
        assert CHECK.run(_context(repo)) == []

    def test_counter_unset_is_clean_even_with_new_folder(self, repo: Path) -> None:
        _stage_new_plan(repo, "00002-widget")
        assert CHECK.run(_context(repo)) == []


class TestFindings:
    def test_folder_within_counter_is_clean(self, repo: Path) -> None:
        _git(repo, "config", "--local", "hooksdaemon.latestPlanNumber", "2")
        _stage_new_plan(repo, "00002-widget")
        assert CHECK.run(_context(repo)) == []

    def test_folder_exceeding_counter_blocks(self, repo: Path) -> None:
        _git(repo, "config", "--local", "hooksdaemon.latestPlanNumber", "1")
        _stage_new_plan(repo, "00005-widget")
        findings = CHECK.run(_context(repo))
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check_id == "counter-sanity"
        assert finding.level == Level.BLOCK
        assert "00005" in finding.message
        assert "mkplan.bash" in finding.remediation

    def test_legacy_allowlisted_downgrades_to_advise(self, repo: Path) -> None:
        _git(repo, "config", "--local", "hooksdaemon.latestPlanNumber", "1")
        _stage_new_plan(repo, "00005-widget")
        findings = CHECK.run(_context(repo, legacy=frozenset({5})))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
