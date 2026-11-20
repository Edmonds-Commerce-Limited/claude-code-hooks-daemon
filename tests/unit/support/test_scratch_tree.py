"""Tests for the fake scratch-tree builder (Plan 00627 Task 1.1)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from tests.support.scratch_tree import ScratchTree, build_scratch_tree


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    return build_scratch_tree(tmp_path)


def test_root_and_outside_are_separate_directories(tree: ScratchTree) -> None:
    assert tree.root.is_dir()
    assert tree.outside.is_dir()
    assert not str(tree.outside).startswith(str(tree.root) + os.sep)
    assert not str(tree.root).startswith(str(tree.outside) + os.sep)


def test_file_creates_parents_and_content(tree: ScratchTree) -> None:
    path = tree.file("entry/a/b.txt", b"hello")
    assert path == tree.root / "entry" / "a" / "b.txt"
    assert path.read_bytes() == b"hello"


def test_file_sets_mtime(tree: ScratchTree) -> None:
    path = tree.file("entry/x.log", mtime=1_000_000.0)
    assert os.lstat(path).st_mtime == 1_000_000.0


def test_directory_creates_empty_directory(tree: ScratchTree) -> None:
    path = tree.directory("empty/inner")
    assert path.is_dir()
    assert not any(path.iterdir())


def test_set_tree_mtime_ages_every_inode_without_following_links(tree: ScratchTree) -> None:
    dummy = tree.outside_dummy("target.txt", b"outside")
    before = os.lstat(dummy).st_mtime
    tree.file("e/a/f.txt")
    tree.symlink("e/link", dummy)
    tree.set_tree_mtime("e", 500_000.0)
    for path in (tree.root / "e", tree.root / "e/a", tree.root / "e/a/f.txt", tree.root / "e/link"):
        assert os.lstat(path).st_mtime == 500_000.0
    assert os.lstat(dummy).st_mtime == before


def test_symlink_to_outside_dummy(tree: ScratchTree) -> None:
    dummy = tree.outside_dummy("secret.txt", b"dummy")
    link = tree.symlink("entry/to-secret", dummy)
    assert link.is_symlink()
    assert link.readlink() == dummy
    assert dummy.read_bytes() == b"dummy"


def test_hardlink_shares_inode(tree: ScratchTree) -> None:
    dummy = tree.outside_dummy("shared.txt", b"s")
    link = tree.hardlink("entry/shared.txt", dummy)
    assert os.lstat(link).st_ino == os.lstat(dummy).st_ino
    assert os.lstat(link).st_nlink == 2


def test_fifo(tree: ScratchTree) -> None:
    path = tree.fifo("entry/pipe")
    assert stat.S_ISFIFO(os.lstat(path).st_mode)


def test_git_marker_directory_and_file(tree: ScratchTree) -> None:
    as_dir = tree.git_marker("repo")
    assert as_dir == tree.root / "repo" / ".git"
    assert as_dir.is_dir()
    as_file = tree.git_marker("wt", gitdir="/elsewhere/.git/worktrees/wt")
    assert as_file.is_file()
    assert as_file.read_text() == "gitdir: /elsewhere/.git/worktrees/wt\n"


def test_refusing_scandir_raises_only_for_named_directories(tree: ScratchTree) -> None:
    tree.file("ok/a.txt")
    tree.file("locked/b.txt")
    scandir = tree.refusing_scandir("locked")
    with scandir(str(tree.root / "ok")) as entries:
        assert [entry.name for entry in entries] == ["a.txt"]
    with pytest.raises(PermissionError):
        scandir(str(tree.root / "locked"))


def test_snapshot_records_names_mtime_and_ctime(tree: ScratchTree) -> None:
    tree.file("e/a.txt")
    first = tree.snapshot()
    assert (tree.root / "e" / "a.txt").relative_to(tree.base).as_posix() in first
    assert tree.snapshot() == first
    tree.file("e/b.txt")
    assert tree.snapshot() != first
