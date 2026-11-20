"""The scratch entry walker (Plan 00627 Task 1.3).

Every test builds its tree with the Task 1.1 builder. The walker reads only
``lstat`` data and directory listings: it never follows a link and never opens
a file.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.scratch_walk import (
    NodeKind,
    WalkBudget,
    list_entries,
    walk_entry,
)
from tests.support.scratch_tree import ScratchTree, build_scratch_tree

_OLD = 1_600_000_000.0


@pytest.fixture
def tree(tmp_path: Path) -> ScratchTree:
    return build_scratch_tree(tmp_path)


def _budget(seconds: float = 60.0, max_inodes: int = 100_000) -> WalkBudget:
    return WalkBudget(seconds=seconds, max_inodes=max_inodes)


def _now() -> float:
    return time.time()


class TestCounts:
    def test_a_directory_entry_is_counted(self, tree: ScratchTree) -> None:
        tree.file("e/a.txt", b"abc")
        tree.file("e/sub/b.txt", b"de")
        result = walk_entry(tree.root, "e", now=_now(), budget=_budget())
        assert result.complete
        stats = result.value
        assert stats.kind is NodeKind.DIRECTORY
        assert stats.directories == 2
        assert stats.files == 2
        assert stats.bytes == 5

    def test_a_loose_file_is_an_entry(self, tree: ScratchTree) -> None:
        tree.file("note.md", b"hello")
        result = walk_entry(tree.root, "note.md", now=_now(), budget=_budget())
        assert result.complete
        assert result.value.kind is NodeKind.FILE
        assert (result.value.files, result.value.directories, result.value.bytes) == (1, 0, 5)

    def test_node_paths_are_relative_to_the_root_and_include_the_entry(
        self, tree: ScratchTree
    ) -> None:
        tree.file("__pycache__/x.pyc")
        stats = walk_entry(tree.root, "__pycache__", now=_now(), budget=_budget()).value
        paths = {node.path: node.kind for node in stats.nodes}
        assert paths == {
            "__pycache__": NodeKind.DIRECTORY,
            "__pycache__/x.pyc": NodeKind.FILE,
        }

    def test_an_empty_directory_node_is_marked_empty(self, tree: ScratchTree) -> None:
        tree.directory("e/empty")
        tree.file("e/f")
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        empties = {node.path for node in stats.nodes if node.empty}
        assert empties == {"e/empty"}


class TestLinksAreNeverFollowed:
    def test_a_link_inside_is_recorded_and_not_descended(self, tree: ScratchTree) -> None:
        outside_dir = tree.outside / "big"
        outside_dir.mkdir()
        (outside_dir / "secret").write_bytes(b"s" * 100)
        tree.symlink("e/link", outside_dir)
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        kinds = {node.path: node.kind for node in stats.nodes}
        assert kinds["e/link"] is NodeKind.SYMLINK
        assert not any("secret" in path for path in kinds)
        assert stats.directories == 1

    def test_an_entry_that_is_a_link_records_its_target(self, tree: ScratchTree) -> None:
        dummy = tree.outside_dummy("d")
        tree.symlink("top", dummy)
        result = walk_entry(tree.root, "top", now=_now(), budget=_budget())
        assert result.complete
        assert result.value.kind is NodeKind.SYMLINK
        assert result.value.link_target == str(dummy)
        assert [node.path for node in result.value.nodes] == ["top"]

    def test_a_dangling_link_is_recorded(self, tree: ScratchTree) -> None:
        tree.symlink("e/dangling", tree.outside / "missing")
        result = walk_entry(tree.root, "e", now=_now(), budget=_budget())
        assert result.complete
        assert NodeKind.SYMLINK in {node.kind for node in result.value.nodes}


class TestSpecialAndMultiLinked:
    def test_a_fifo_is_a_special_file(self, tree: ScratchTree) -> None:
        tree.fifo("e/pipe")
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        assert stats.special_files == ("e/pipe",)

    def test_a_file_with_a_name_outside_is_multi_linked(self, tree: ScratchTree) -> None:
        dummy = tree.outside_dummy("d")
        tree.hardlink("e/second", dummy)
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        assert stats.multi_linked == ("e/second",)

    def test_two_names_inside_the_same_entry_are_not_multi_linked(
        self, tree: ScratchTree
    ) -> None:
        first = tree.file("e/a")
        tree.hardlink("e/b", first)
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        assert stats.multi_linked == ()


class TestGitMarkers:
    def test_a_nested_git_directory_is_found(self, tree: ScratchTree) -> None:
        tree.git_marker("e/deep/repo")
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        assert stats.git_markers == ("e/deep/repo/.git",)

    def test_a_git_file_is_found(self, tree: ScratchTree) -> None:
        tree.git_marker("e", gitdir="/somewhere/else")
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        assert stats.git_markers == ("e/.git",)


class TestTimes:
    def test_newest_mtime_is_the_newest_inode(self, tree: ScratchTree) -> None:
        tree.file("e/a", mtime=_OLD)
        tree.file("e/b", mtime=_OLD + 500)
        tree.set_tree_mtime("e", _OLD)
        os.utime(tree.root / "e/b", (_OLD + 500, _OLD + 500), follow_symlinks=False)
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        assert stats.newest_mtime_ns == int((_OLD + 500) * 1e9)

    def test_a_future_mtime_is_replaced_by_that_inode_ctime(self, tree: ScratchTree) -> None:
        path = tree.file("e/a")
        tree.set_tree_mtime("e", _OLD)
        future = _now() + 10 * 86400
        os.utime(path, (future, future), follow_symlinks=False)
        ctime_ns = os.lstat(path).st_ctime_ns
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        assert stats.newest_mtime_ns == ctime_ns

    def test_root_ctime_is_recorded(self, tree: ScratchTree) -> None:
        tree.directory("e")
        stats = walk_entry(tree.root, "e", now=_now(), budget=_budget()).value
        assert stats.root_ctime_ns == os.lstat(tree.root / "e").st_ctime_ns


class TestIncomplete:
    def test_an_unreadable_directory_stops_the_walk(self, tree: ScratchTree) -> None:
        tree.file("e/ok")
        tree.file("e/locked/x")
        result = walk_entry(
            tree.root,
            "e",
            now=_now(),
            budget=_budget(),
            scandir=tree.refusing_scandir("e/locked"),
        )
        assert not result.complete
        assert "e/locked" in result.reason

    def test_the_inode_cap_stops_the_walk(self, tree: ScratchTree) -> None:
        for index in range(10):
            tree.file(f"e/f{index}")
        result = walk_entry(tree.root, "e", now=_now(), budget=_budget(max_inodes=3))
        assert not result.complete
        assert "inode" in result.reason

    def test_the_deadline_stops_the_walk(self, tree: ScratchTree) -> None:
        tree.file("e/a")
        ticks = iter([0.0, 100.0, 200.0, 300.0, 400.0])
        budget = WalkBudget(seconds=50.0, max_inodes=100, clock=lambda: next(ticks))
        result = walk_entry(tree.root, "e", now=_now(), budget=budget)
        assert not result.complete
        assert "deadline" in result.reason

    def test_a_spent_budget_stops_every_later_entry(self, tree: ScratchTree) -> None:
        tree.file("a/x")
        tree.file("b/y")
        budget = _budget(max_inodes=2)
        walk_entry(tree.root, "a", now=_now(), budget=budget)
        assert not walk_entry(tree.root, "b", now=_now(), budget=budget).complete

    def test_a_second_device_stops_the_walk(
        self, tree: ScratchTree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tree.file("e/mnt/x")
        real_lstat = os.lstat
        mount = str(tree.root / "e/mnt")

        class _Shifted:
            def __init__(self, info: os.stat_result) -> None:
                self._info = info

            def __getattr__(self, name: str) -> object:
                if name == "st_dev":
                    return self._info.st_dev + 1
                return getattr(self._info, name)

        def lstat(path: str | os.PathLike[str]) -> object:
            info = real_lstat(path)
            return _Shifted(info) if os.fspath(path) == mount else info

        monkeypatch.setattr("claude_code_hooks_daemon.core.scratch_walk.os.lstat", lstat)
        result = walk_entry(tree.root, "e", now=_now(), budget=_budget())
        assert not result.complete
        assert "device" in result.reason

    def test_a_missing_entry_is_incomplete_not_empty(self, tree: ScratchTree) -> None:
        result = walk_entry(tree.root, "gone", now=_now(), budget=_budget())
        assert not result.complete
        assert result.value.kind is NodeKind.UNREAD
        assert result.value.name == "gone"


class TestListEntries:
    def test_entries_are_the_root_children_sorted(self, tree: ScratchTree) -> None:
        tree.file("b.txt")
        tree.directory("a")
        assert list_entries(tree.root).required() == ("a", "b.txt")

    def test_the_root_gitignore_is_not_an_entry(self, tree: ScratchTree) -> None:
        tree.file(".gitignore")
        tree.file("x")
        assert list_entries(tree.root).required() == ("x",)

    def test_an_unreadable_root_is_incomplete(self, tree: ScratchTree) -> None:
        refusing = tree.refusing_scandir("")
        result = list_entries(tree.root, scandir=refusing)
        assert not result.complete


class TestReadsNothing:
    def test_a_walk_changes_no_inode(self, tree: ScratchTree) -> None:
        tree.file("e/a", b"content")
        tree.symlink("e/l", tree.outside_dummy("d"))
        tree.fifo("e/p")
        tree.git_marker("e/r")
        before = tree.snapshot()
        walk_entry(tree.root, "e", now=_now(), budget=_budget())
        assert tree.snapshot() == before
