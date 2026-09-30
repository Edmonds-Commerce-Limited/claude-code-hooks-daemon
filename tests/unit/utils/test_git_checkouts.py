"""Which git checkout a path belongs to, decided from git's own markers (N264).

Real repositories built with the ``git`` binary, because the claim under test is
that the answer agrees with what git itself wrote: a ``.git`` directory for the
main working tree, a ``.git`` file plus ``commondir`` for a linked worktree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.git_checkouts import (
    CheckoutUndecidableError,
    enclosing_checkout,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README").write_text("x")
    _git(root, "add", "README")
    _git(root, "commit", "-q", "-m", "init")
    return root.resolve()


def _worktree(repo: Path, where: Path, branch: str) -> Path:
    where.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", branch, str(where))
    return where.resolve()


class TestMainWorkingTree:
    def test_a_file_in_the_main_tree_belongs_to_it(self, repo: Path) -> None:
        found = enclosing_checkout(repo / "README")
        assert found is not None
        assert found.root == repo
        assert found.linked is False

    def test_a_directory_below_the_root_belongs_to_it(self, repo: Path) -> None:
        (repo / "a" / "b").mkdir(parents=True)
        found = enclosing_checkout(repo / "a" / "b")
        assert found is not None and found.root == repo

    def test_a_file_that_does_not_exist_yet_belongs_to_its_nearest_checkout(
        self, repo: Path
    ) -> None:
        found = enclosing_checkout(repo / "new" / "deeper" / "file.py")
        assert found is not None and found.root == repo


class TestLinkedWorktree:
    def test_a_linked_worktree_is_linked_and_shares_the_common_dir(
        self, repo: Path, tmp_path: Path
    ) -> None:
        wt = _worktree(repo, tmp_path / "wt" / "a", "a")
        main = enclosing_checkout(repo)
        linked = enclosing_checkout(wt / "README")
        assert main is not None and linked is not None
        assert linked.root == wt
        assert linked.linked is True
        assert linked.common_dir == main.common_dir

    def test_a_worktree_nested_inside_the_main_tree_is_attributed_to_itself(
        self, repo: Path
    ) -> None:
        wt = _worktree(repo, repo / "untracked" / "worktrees" / "x", "x")
        found = enclosing_checkout(wt / "README")
        assert found is not None
        assert found.root == wt
        assert found.linked is True
        # The main tree's own files stay the main tree's.
        outer = enclosing_checkout(repo / "README")
        assert outer is not None and outer.root == repo

    def test_a_symlink_into_a_worktree_is_resolved_first(self, repo: Path, tmp_path: Path) -> None:
        wt = _worktree(repo, tmp_path / "wt" / "a", "a")
        link = tmp_path / "shortcut"
        link.symlink_to(wt)
        found = enclosing_checkout(link / "README")
        assert found is not None and found.root == wt

    def test_two_linked_worktrees_are_distinct_checkouts_of_one_repository(
        self, repo: Path, tmp_path: Path
    ) -> None:
        a = _worktree(repo, tmp_path / "wt" / "a", "a")
        b = _worktree(repo, tmp_path / "wt" / "b", "b")
        found_a = enclosing_checkout(a)
        found_b = enclosing_checkout(b)
        assert found_a is not None and found_b is not None
        assert found_a.root != found_b.root
        assert found_a.common_dir == found_b.common_dir


class TestNotDecidable:
    def test_a_path_outside_any_repository_has_no_checkout(self, tmp_path: Path) -> None:
        (tmp_path / "plain").mkdir()
        assert enclosing_checkout(tmp_path / "plain" / "f.txt") is None

    def test_a_submodule_style_git_file_is_a_main_checkout_not_a_linked_one(
        self, tmp_path: Path
    ) -> None:
        gitdir = tmp_path / "super" / ".git" / "modules" / "sub"
        gitdir.mkdir(parents=True)
        sub = tmp_path / "super" / "sub"
        sub.mkdir()
        (sub / ".git").write_text(f"gitdir: {gitdir}\n")
        found = enclosing_checkout(sub / "f.py")
        assert found is not None
        assert found.linked is False
        assert found.common_dir == gitdir.resolve()

    def test_an_unparseable_git_file_is_undecidable(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".git").write_text("this is not a gitdir line\n")
        with pytest.raises(CheckoutUndecidableError, match="no gitdir line"):
            enclosing_checkout(broken / "f.py")

    def test_a_git_file_naming_a_missing_gitdir_is_undecidable(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".git").write_text(f"gitdir: {tmp_path}/gone/.git/worktrees/x\n")
        with pytest.raises(CheckoutUndecidableError, match="missing"):
            enclosing_checkout(broken / "f.py")

    def test_an_empty_commondir_is_undecidable(self, tmp_path: Path) -> None:
        gitdir = tmp_path / "main" / ".git" / "worktrees" / "w"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("\n")
        wt = tmp_path / "w"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {gitdir}\n")
        with pytest.raises(CheckoutUndecidableError, match="empty"):
            enclosing_checkout(wt / "f.py")

    def test_an_unreadable_git_file_is_undecidable(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        marker = broken / ".git"
        marker.write_bytes(b"gitdir: x\n")
        marker.chmod(0)
        try:
            if marker.read_bytes():  # running as root: the mode does not bite
                pytest.skip("file permissions are not enforced for this user")
        except PermissionError:
            with pytest.raises(CheckoutUndecidableError, match="cannot read"):
                enclosing_checkout(broken / "f.py")
        finally:
            marker.chmod(0o600)

    def test_a_relative_gitdir_is_read_against_the_git_file(self, tmp_path: Path) -> None:
        gitdir = tmp_path / "main" / ".git" / "worktrees" / "w"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n")
        wt = tmp_path / "w"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: ../main/.git/worktrees/w\n")
        found = enclosing_checkout(wt / "f.py")
        assert found is not None
        assert found.linked is True
        assert found.common_dir == (tmp_path / "main" / ".git").resolve()

    def test_a_nul_byte_path_is_undecidable(self) -> None:
        with pytest.raises(CheckoutUndecidableError, match="cannot resolve"):
            enclosing_checkout("/tmp/a\0b")
