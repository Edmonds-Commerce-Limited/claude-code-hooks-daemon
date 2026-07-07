"""Tests for plan_qa.gitfacts — staged/HEAD git fact gathering (Plan 00144, Task 1.4)."""

import subprocess
from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts, StagedChange


def _git(repo: Path, *args: str) -> None:
    """Run a git command in ``repo`` (helper for fixture setup)."""
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
    (plan_dir / "00001-first" / "PLAN.md").write_text(
        "# Plan 00001: first\n\n**Status**: In Progress\n"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


class TestStagedChanges:
    def test_clean_repo_has_no_staged_changes(self, repo: Path) -> None:
        assert GitFacts(repo).staged_changes() == ()

    def test_added_file_reported(self, repo: Path) -> None:
        new_plan = repo / "CLAUDE/Plan/00002-second"
        new_plan.mkdir()
        (new_plan / "PLAN.md").write_text("# Plan 00002: second\n\n**Status**: Not Started\n")
        _git(repo, "add", "-A")
        changes = GitFacts(repo).staged_changes()
        assert changes == (
            StagedChange(status="A", path="CLAUDE/Plan/00002-second/PLAN.md", old_path=None),
        )

    def test_modified_file_reported(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text(
            "# Plan 00001: first\n\n**Status**: Complete\n"
        )
        _git(repo, "add", "-A")
        changes = GitFacts(repo).staged_changes()
        assert changes[0].status == "M"
        assert changes[0].path == "CLAUDE/Plan/00001-first/PLAN.md"

    def test_rename_reports_old_and_new_path(self, repo: Path) -> None:
        completed = repo / "CLAUDE/Plan/Completed"
        completed.mkdir()
        _git(repo, "mv", "CLAUDE/Plan/00001-first", "CLAUDE/Plan/Completed/00001-first")
        changes = GitFacts(repo).staged_changes()
        assert len(changes) == 1
        change = changes[0]
        assert change.status.startswith("R")
        assert change.old_path == "CLAUDE/Plan/00001-first/PLAN.md"
        assert change.path == "CLAUDE/Plan/Completed/00001-first/PLAN.md"

    def test_unstaged_changes_not_reported(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/00001-first/PLAN.md").write_text("unstaged edit\n")
        assert GitFacts(repo).staged_changes() == ()

    def test_staged_paths_under_prefix(self, repo: Path) -> None:
        (repo / "other.txt").write_text("x\n")
        (repo / "CLAUDE/Plan/README.md").write_text("# Plans Index (edited)\n")
        _git(repo, "add", "-A")
        facts = GitFacts(repo)
        under_plan = facts.staged_paths_under("CLAUDE/Plan")
        assert under_plan == ("CLAUDE/Plan/README.md",)


class TestFileTexts:
    def test_staged_file_text_reads_index_version(self, repo: Path) -> None:
        (repo / "CLAUDE/Plan/README.md").write_text("staged content\n")
        _git(repo, "add", "-A")
        # Working tree diverges after staging — staged text must win.
        (repo / "CLAUDE/Plan/README.md").write_text("worktree content\n")
        facts = GitFacts(repo)
        assert facts.staged_file_text("CLAUDE/Plan/README.md") == "staged content\n"

    def test_staged_file_text_missing_path_is_none(self, repo: Path) -> None:
        assert GitFacts(repo).staged_file_text("CLAUDE/Plan/nope.md") is None

    def test_head_file_text_reads_committed_version(self, repo: Path) -> None:
        facts = GitFacts(repo)
        head_text = facts.head_file_text("CLAUDE/Plan/00001-first/PLAN.md")
        assert head_text is not None
        assert "**Status**: In Progress" in head_text

    def test_head_file_text_missing_path_is_none(self, repo: Path) -> None:
        assert GitFacts(repo).head_file_text("does/not/exist.md") is None


class TestCounterAndDates:
    def test_plan_counter_unset_is_none(self, repo: Path) -> None:
        assert GitFacts(repo).plan_counter() is None

    def test_plan_counter_reads_git_config(self, repo: Path) -> None:
        _git(repo, "config", "--local", "hooksdaemon.latestPlanNumber", "41")
        assert GitFacts(repo).plan_counter() == 41

    def test_last_commit_date_for_committed_path(self, repo: Path) -> None:
        facts = GitFacts(repo)
        commit_date = facts.last_commit_date("CLAUDE/Plan/00001-first")
        assert isinstance(commit_date, date)

    def test_last_commit_date_for_unknown_path_is_none(self, repo: Path) -> None:
        assert GitFacts(repo).last_commit_date("CLAUDE/Plan/00099-ghost") is None
