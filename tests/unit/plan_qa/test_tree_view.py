"""Tests for plan_qa.tree_view — the disk and the index as two views of a plan tree.

Ledger 00474 N244: the plan QA commit gate judges the tree the commit WILL
record, so :meth:`PlanTree.scan` must be able to walk a listing that has no
counterpart on disk at all.
"""

from datetime import date
from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.model import PlanLocation, PlanTree
from claude_code_hooks_daemon.plan_qa.tree_view import DiskTreeView, IndexTreeView

_PLAN = "# Plan 00001: first\n\n**Status**: In Progress\n"


def _index_view(root: Path, texts: dict[str, str]) -> IndexTreeView:
    """A view over files that exist ONLY in this listing, never on disk."""
    return IndexTreeView(
        files=[root / name for name in texts],
        texts={root / name: text for name, text in texts.items()},
    )


class TestIndexTreeView:
    def test_a_directory_is_any_ancestor_of_a_listed_file(self, tmp_path: Path) -> None:
        view = _index_view(tmp_path, {"a/b/c.md": "x"})

        assert view.is_dir(tmp_path / "a")
        assert view.is_dir(tmp_path / "a" / "b")
        assert not view.is_dir(tmp_path / "a" / "b" / "c.md")
        assert not view.is_dir(tmp_path / "nowhere")

    def test_a_file_is_a_listed_path(self, tmp_path: Path) -> None:
        view = _index_view(tmp_path, {"a/b/c.md": "x"})

        assert view.is_file(tmp_path / "a" / "b" / "c.md")
        assert not view.is_file(tmp_path / "a")

    def test_children_are_sorted_and_direct_only(self, tmp_path: Path) -> None:
        view = _index_view(tmp_path, {"b/1.md": "x", "a/2.md": "x", "a/sub/3.md": "x", "z.md": "x"})

        assert view.children(tmp_path) == [tmp_path / "a", tmp_path / "b", tmp_path / "z.md"]
        assert view.children(tmp_path / "a") == [tmp_path / "a" / "2.md", tmp_path / "a" / "sub"]

    def test_children_of_an_unlisted_directory_are_empty(self, tmp_path: Path) -> None:
        assert _index_view(tmp_path, {"a.md": "x"}).children(tmp_path / "nowhere") == []

    def test_a_declared_empty_directory_exists_but_holds_nothing(self, tmp_path: Path) -> None:
        view = IndexTreeView(
            files=[tmp_path / "a.md"], texts={}, empty_dirs=[tmp_path / "Completed"]
        )

        assert view.is_dir(tmp_path / "Completed")
        assert view.children(tmp_path / "Completed") == []

    def test_reads_the_listed_text(self, tmp_path: Path) -> None:
        view = _index_view(tmp_path, {"a.md": "hello"})

        assert view.read_text(tmp_path / "a.md") == "hello"

    def test_reading_a_file_that_was_not_loaded_fails_fast(self, tmp_path: Path) -> None:
        view = IndexTreeView(files=[tmp_path / "a.md"], texts={})

        with pytest.raises(KeyError):
            view.read_text(tmp_path / "a.md")


class TestDiskTreeView:
    def test_reads_what_is_on_disk(self, tmp_path: Path) -> None:
        (tmp_path / "d").mkdir()
        (tmp_path / "d" / "f.md").write_text("on disk")
        view = DiskTreeView()

        assert view.is_dir(tmp_path / "d")
        assert view.is_file(tmp_path / "d" / "f.md")
        assert view.children(tmp_path) == [tmp_path / "d"]
        assert view.read_text(tmp_path / "d" / "f.md") == "on disk"


class TestScanOverAnIndexView:
    def test_scans_a_tree_that_does_not_exist_on_disk(self, tmp_path: Path) -> None:
        root = tmp_path / "Plan"
        view = _index_view(
            root,
            {
                "README.md": "# index",
                "00001-first/PLAN.md": _PLAN,
                "00001-first/JOURNAL/00001-Journal-26-07-02.md": "j",
                "Completed/00002-second/PLAN.md": "# Plan 00002: second\n\n**Status**: Complete\n",
                "notes.txt": "stray",
            },
        )

        tree = PlanTree.scan(root, view=view)

        assert [(f.number, f.location) for f in tree.folders] == [
            (1, PlanLocation.ROOT),
            (2, PlanLocation.COMPLETED),
        ]
        first = tree.folders[0]
        assert first.has_plan_md
        assert first.doc is not None and first.doc.plan_number == 1
        assert first.has_journal
        assert first.latest_journal_date == date(2026, 7, 2)
        assert tree.stray_files == (root / "notes.txt",)
        assert tree.has_readme
        assert tree.has_completed_dir
        assert not tree.has_cancelled_dir

    def test_an_empty_listing_is_a_missing_plan_directory(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            PlanTree.scan(tmp_path / "Plan", view=_index_view(tmp_path / "Plan", {}))

    def test_the_tree_answers_is_dir_from_its_own_view(self, tmp_path: Path) -> None:
        root = tmp_path / "Plan"
        tree = PlanTree.scan(root, view=_index_view(root, {"00001-first/PLAN.md": _PLAN}))

        assert tree.is_dir(root / "00001-first")
        assert not tree.is_dir(root / "00009-gone")

    def test_a_tree_scanned_from_disk_answers_from_disk(self, tmp_path: Path) -> None:
        (tmp_path / "00001-first").mkdir()
        (tmp_path / "00001-first" / "PLAN.md").write_text(_PLAN)

        tree = PlanTree.scan(tmp_path)

        assert tree.is_dir(tmp_path / "00001-first")
        assert not tree.is_dir(tmp_path / "00009-gone")
