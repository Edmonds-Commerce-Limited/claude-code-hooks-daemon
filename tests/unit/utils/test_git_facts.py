"""Tests for the shared read-only git facts.

Plan 00444, from ledger 00422 N14. The class began in ``plan_qa`` and grew a
``docs_qa`` caller, which made docs QA depend on plan QA for git plumbing that
has nothing to do with plans. The generic core lives here; ``plan_qa`` keeps a
subclass for the one plan-specific accessor.

These tests exercise the base directly against a real repository, because the
whole value of the class is that it reports what git reports. ``plan_qa``'s own
``test_gitfacts.py`` still covers the subclass and is deliberately left
untouched — if the public surface moved, it would say so.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_facts import (
    GitFactsBase,
    StagedChange,
    project_relative_head_text,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        timeout=Timeout.GIT_CONTEXT,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one committed file and one staged addition."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "committed.md").write_text("original\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    (root / "added.md").write_text("new\n", encoding="utf-8")
    _git(root, "add", "-A")
    return root


class TestStagedChanges:
    def test_a_staged_addition_is_reported(self, repo: Path) -> None:
        changes = GitFactsBase(repo).staged_changes()

        assert changes == (StagedChange(status="A", path="added.md", old_path=None),)

    def test_a_rename_carries_both_paths(self, repo: Path) -> None:
        _git(repo, "mv", "committed.md", "renamed.md")

        statuses = {
            change.status[0]: (change.old_path, change.path)
            for change in GitFactsBase(repo).staged_changes()
        }

        assert statuses["R"] == ("committed.md", "renamed.md")

    def test_it_is_read_from_git_once_per_instance(self, repo: Path) -> None:
        """Memoised: the commit gate asks once per plan folder."""
        facts = GitFactsBase(repo)
        first = facts.staged_changes()

        (repo / "later.md").write_text("later\n", encoding="utf-8")
        _git(repo, "add", "-A")

        assert facts.staged_changes() is first

    def test_a_fresh_instance_sees_the_newer_state(self, repo: Path) -> None:
        """The control for memoisation: it is per-instance, not global."""
        GitFactsBase(repo).staged_changes()
        (repo / "later.md").write_text("later\n", encoding="utf-8")
        _git(repo, "add", "-A")

        paths = {change.path for change in GitFactsBase(repo).staged_changes()}

        assert "later.md" in paths


class TestPathspecScoping:
    """``git commit <pathspec>`` commits those paths' WORKING TREE content."""

    def test_an_unstaged_named_path_is_still_seen(self, repo: Path) -> None:
        (repo / "committed.md").write_text("modified but not staged\n", encoding="utf-8")

        facts = GitFactsBase(repo, pathspecs=["committed.md"])

        assert [change.path for change in facts.staged_changes()] == ["committed.md"]

    def test_a_staged_but_unnamed_path_is_excluded(self, repo: Path) -> None:
        (repo / "committed.md").write_text("modified but not staged\n", encoding="utf-8")

        facts = GitFactsBase(repo, pathspecs=["committed.md"])

        assert "added.md" not in {change.path for change in facts.staged_changes()}


class TestFileText:
    def test_staged_text_comes_from_the_index(self, repo: Path) -> None:
        assert GitFactsBase(repo).staged_file_text("added.md") == "new\n"

    def test_head_text_comes_from_the_commit(self, repo: Path) -> None:
        (repo / "committed.md").write_text("changed\n", encoding="utf-8")
        _git(repo, "add", "-A")

        assert GitFactsBase(repo).head_file_text("committed.md") == "original\n"

    def test_an_unknown_path_is_none_rather_than_an_error(self, repo: Path) -> None:
        """A non-zero git exit is "fact not available", not a failure."""
        assert GitFactsBase(repo).staged_file_text("nope.md") is None


class TestStagedPathsUnder:
    def test_it_filters_by_prefix_and_sorts(self, repo: Path) -> None:
        (repo / "docs").mkdir()
        (repo / "docs" / "b.md").write_text("b\n", encoding="utf-8")
        (repo / "docs" / "a.md").write_text("a\n", encoding="utf-8")
        _git(repo, "add", "-A")

        assert GitFactsBase(repo).staged_paths_under("docs") == ("docs/a.md", "docs/b.md")

    def test_a_prefix_matching_nothing_is_empty(self, repo: Path) -> None:
        assert GitFactsBase(repo).staged_paths_under("absent") == ()


class TestLastCommitDate:
    def test_a_committed_path_has_a_date(self, repo: Path) -> None:
        assert GitFactsBase(repo).last_commit_date("committed.md") is not None

    def test_a_never_committed_path_is_none(self, repo: Path) -> None:
        assert GitFactsBase(repo).last_commit_date("added.md") is None


class TestItIsStrictlyReadOnly:
    def test_reading_facts_leaves_the_index_unchanged(self, repo: Path) -> None:
        """The whole class is read-only; nothing here may stage or commit."""
        facts = GitFactsBase(repo)
        before = {change.path for change in facts.staged_changes()}

        facts.staged_file_text("added.md")
        facts.head_file_text("committed.md")
        facts.last_commit_date("committed.md")

        assert {change.path for change in GitFactsBase(repo).staged_changes()} == before


class TestProjectRelativeHeadText:
    """Ledger 00466 N3: the shared HEAD-comparison helper both
    ``goal_injection`` and ``recovery_cron_advisor`` use for their
    transition checks. Review nit n3: ``project_root`` is a plain
    parameter -- this module stays core-free -- so these tests pass it
    directly rather than monkeypatching ``ProjectContext``."""

    def test_a_committed_path_returns_its_head_content(self, repo: Path) -> None:
        (repo / "committed.md").write_text("changed\n", encoding="utf-8")

        assert project_relative_head_text(repo / "committed.md", repo) == "original\n"

    def test_a_never_committed_path_is_none(self, repo: Path) -> None:
        assert project_relative_head_text(repo / "added.md", repo) is None

    def test_a_path_outside_the_project_root_is_none(self, tmp_path: Path, repo: Path) -> None:
        outside = tmp_path / "outside.md"
        outside.write_text("x\n", encoding="utf-8")

        assert project_relative_head_text(outside, repo) is None

    def test_a_nested_path_resolves_correctly(self, repo: Path) -> None:
        nested_dir = repo / "CLAUDE" / "Plan" / "00042-my-plan"
        nested_dir.mkdir(parents=True)
        nested = nested_dir / "PLAN.md"
        nested.write_text("**Status**: Complete\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "add plan")
        nested.write_text("**Status**: Complete\n\nMore.\n", encoding="utf-8")

        assert project_relative_head_text(nested, repo) == "**Status**: Complete\n"

    def test_a_file_in_a_nested_repository_reads_from_its_OWN_head(self, repo: Path) -> None:
        """Ledger 00466 review m5: a file under the project root can belong
        to a DIFFERENT git repository (a linked worktree, a nested clone).
        HEAD must come from THAT repo, not the project root's -- which never
        tracks the nested path at all, so it always answered "absent" and a
        write there was silently misread as a genuine transition."""
        nested = repo / "untracked" / "worktrees" / "wt"
        nested.mkdir(parents=True)
        _git(nested, "init")
        _git(nested, "config", "user.email", "t@example.com")
        _git(nested, "config", "user.name", "T")
        plan_dir = nested / "CLAUDE" / "Plan" / "00301-fourth"
        plan_dir.mkdir(parents=True)
        plan_md = plan_dir / "PLAN.md"
        plan_md.write_text("**Status**: In Progress\n", encoding="utf-8")
        _git(nested, "add", "-A")
        _git(nested, "commit", "-m", "flip")
        plan_md.write_text("**Status**: In Progress\n\nmore\n", encoding="utf-8")

        assert project_relative_head_text(plan_md, repo) == "**Status**: In Progress\n"
