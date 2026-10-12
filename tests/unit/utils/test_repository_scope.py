"""Tests for the shared 'is this path in THIS repository' boundary (Issue #80)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.utils import git_repo
from claude_code_hooks_daemon.utils.git_repo import path_is_git_ignored
from claude_code_hooks_daemon.utils.repository_scope import (
    outside_this_repository,
    owning_checkout,
)
from tests.support.git_fixtures import run_git


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    run_git(root, "init")
    run_git(root, "config", "user.email", "t@example.com")
    run_git(root, "config", "user.name", "T")
    return root


class TestOwningCheckout:
    def test_an_ordinary_file_belongs_to_the_project(self, project: Path) -> None:
        doc = project / "docs" / "a.md"
        assert owning_checkout(str(doc), project) == project

    def test_a_nested_clone_belongs_to_another_repository(self, project: Path) -> None:
        clone = project / "vendor" / "other"
        run_git(project, "init", str(clone))
        assert owning_checkout(str(clone / "CLAUDE.md"), project) is None
        assert outside_this_repository(str(clone / "CLAUDE.md"), project)

    def test_a_submodule_style_git_file_belongs_to_another_repository(self, project: Path) -> None:
        sub = project / "sub"
        sub.mkdir()
        (sub / ".git").write_text("gitdir: ../.git/modules/sub\n")
        assert outside_this_repository(str(sub / "CLAUDE.md"), project)

    def test_a_linked_worktree_of_another_repository_is_foreign(
        self, project: Path, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        (other / ".git" / "worktrees").mkdir(parents=True)
        foreign = project / "untracked" / "scratch" / "foreign"
        foreign.mkdir(parents=True)
        (foreign / ".git").write_text(f"gitdir: {other}/.git/worktrees/foreign\n")
        assert outside_this_repository(str(foreign / "CLAUDE.md"), project)

    def test_a_linked_worktree_of_this_repository_owns_its_files(self, project: Path) -> None:
        (project / "README.md").write_text("# r\n")
        run_git(project, "add", "README.md")
        run_git(project, "commit", "-m", "init")
        worktree = project / "untracked" / "worktrees" / "wt"
        run_git(project, "worktree", "add", "-b", "wt", str(worktree))
        assert not outside_this_repository(str(worktree / "CLAUDE.md"), project)
        assert owning_checkout(str(worktree / "CLAUDE.md"), project) == worktree.resolve()


class TestPathIsGitIgnored:
    def test_an_ignored_path_is_ignored(self, project: Path) -> None:
        (project / ".gitignore").write_text("ignored/\n")
        assert path_is_git_ignored(project, project / "ignored" / "CLAUDE.md")

    def test_an_unignored_untracked_path_is_not_ignored(self, project: Path) -> None:
        (project / ".gitignore").write_text("ignored/\n")
        assert not path_is_git_ignored(project, project / "src" / "CLAUDE.md")

    def test_a_tracked_file_under_an_ignore_rule_is_not_ignored(self, project: Path) -> None:
        (project / ".gitignore").write_text("ignored/\n")
        tracked = project / "ignored" / "CLAUDE.md"
        tracked.parent.mkdir()
        tracked.write_text("# t\n")
        run_git(project, "add", "-f", "ignored/CLAUDE.md")
        assert not path_is_git_ignored(project, tracked)

    def test_outside_a_repository_fails_open(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert not path_is_git_ignored(plain, plain / "CLAUDE.md")

    def test_a_git_error_fails_open(self, project: Path) -> None:
        with patch.object(git_repo, "run_git") as fake:
            fake.return_value.returncode = git_repo.GIT_TIMED_OUT
            fake.return_value.stderr = "timed out"
            assert not path_is_git_ignored(project, project / "ignored" / "CLAUDE.md")

    def test_a_path_outside_the_checkout_fails_open(self, project: Path, tmp_path: Path) -> None:
        assert not path_is_git_ignored(project, tmp_path / "elsewhere" / "CLAUDE.md")
