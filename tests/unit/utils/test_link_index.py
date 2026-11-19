"""Tests for the project link index (Plan 00623 phase 2).

The index replaces the per-call link scan, whose 512-directory cap denied
ordinary commands in any larger project. It lives in daemon memory only, is
verified against the filesystem before every use, and reports an unfinished
verification as such, so a caller denies.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import link_index
from claude_code_hooks_daemon.utils.link_index import LinkIndex, build_link_index


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    link_index.reset_link_indexes()
    yield
    link_index.reset_link_indexes()


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """A project with a file link, a directory link, a nested link and a ``.git``."""
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    (outside / "dummy").write_bytes(b"x")
    root = tmp_path / "proj"
    (root / "a" / "b").mkdir(parents=True)
    (root / "plain").mkdir()
    (root / "flink").symlink_to(outside / "dummy")
    (root / "a" / "dlink").symlink_to(outside / "sub")
    (root / "a" / "b" / "flink2").symlink_to(outside / "dummy")
    (root / ".git" / "hooks").mkdir(parents=True)
    (root / ".git" / "hooks" / "glink").symlink_to(outside / "dummy")
    return root


def _settled(index: LinkIndex) -> LinkIndex:
    """``index`` with every directory listed long ago, so nothing is re-listed as racy."""
    index.age_for_tests(seconds=3600)
    return index


def _scan(index: LinkIndex) -> tuple[set[str], set[str]]:
    result = index.verify().required()
    return set(result.holding), set(result.directory_links)


class TestBuild:
    def test_it_finds_each_directory_holding_a_link_and_each_directory_link(
        self, tree: Path
    ) -> None:
        holding, directory_links = _scan(_settled(build_link_index(str(tree))))
        assert holding == {
            str(tree),
            str(tree / "a"),
            str(tree / "a" / "b"),
            str(tree / ".git" / "hooks"),
        }
        assert directory_links == {str(tree / "a" / "dlink")}

    def test_it_enters_git(self, tree: Path) -> None:
        """Plan 00623 review F4: bash can move into `.git`, so a link there is indexed."""
        holding, _ = _scan(_settled(build_link_index(str(tree))))
        assert str(tree / ".git" / "hooks") in holding

    def test_a_tree_past_the_build_cap_is_overflowed_and_never_complete(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(link_index, "BUILD_DIRECTORY_CAP", 2)
        result = build_link_index(str(tree)).verify()
        assert not result.complete
        assert "overflow" in result.reason


class TestVerificationSeesEveryChange:
    def test_a_link_made_after_the_build_is_found(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        (tree / "plain" / "late").symlink_to(tree.parent / "outside" / "dummy")
        holding, _ = _scan(index)
        assert str(tree / "plain") in holding

    def test_a_deep_new_subtree_made_in_one_step_is_found(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        deep = tree / "plain" / "x" / "y" / "z"
        deep.mkdir(parents=True)
        (deep / "dl").symlink_to(tree.parent / "outside" / "sub")
        holding, directory_links = _scan(index)
        assert str(deep) in holding
        assert str(deep / "dl") in directory_links

    def test_a_renamed_link_holding_subtree_is_found_where_it_now_is(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        (tree / "a").rename(tree / "plain" / "moved")
        holding, directory_links = _scan(index)
        assert str(tree / "plain" / "moved" / "b") in holding
        assert str(tree / "a") not in holding
        assert directory_links == {str(tree / "plain" / "moved" / "dlink")}

    def test_a_link_retargeted_in_place_is_classified_again(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        (tree / "flink").unlink()
        (tree / "flink").symlink_to(tree.parent / "outside" / "sub")
        _, directory_links = _scan(index)
        assert str(tree / "flink") in directory_links

    def test_a_link_whose_target_becomes_a_directory_is_classified_again(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        target = tree.parent / "outside" / "dummy"
        target.unlink()
        target.mkdir()
        _, directory_links = _scan(index)
        assert str(tree / "flink") in directory_links

    def test_resetting_the_mtime_does_not_hide_a_new_link(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        before = os.lstat(tree / "plain")
        (tree / "plain" / "late").symlink_to(tree.parent / "outside" / "dummy")
        os.utime(tree / "plain", ns=(before.st_atime_ns, before.st_mtime_ns), follow_symlinks=False)
        holding, _ = _scan(index)
        assert str(tree / "plain") in holding

    def test_a_directory_listed_within_the_racy_window_is_listed_again(self, tree: Path) -> None:
        index = build_link_index(str(tree))
        # Listed just now: a change in the same clock tick would not move its ctime.
        (tree / "plain" / "late").symlink_to(tree.parent / "outside" / "dummy")
        holding, _ = _scan(index)
        assert str(tree / "plain") in holding

    def test_a_removed_link_is_dropped(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        (tree / "a" / "b" / "flink2").unlink()
        holding, _ = _scan(index)
        assert str(tree / "a" / "b") not in holding


class TestFailClosed:
    def test_stale_past_the_relist_cap(self, tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        index = _settled(build_link_index(str(tree)))
        (tree / "plain" / "late").symlink_to(tree.parent / "outside" / "dummy")
        monkeypatch.setattr(link_index, "VERIFY_RELIST_CAP", 0)
        result = index.verify()
        assert not result.complete
        assert "stale" in result.reason

    def test_stale_past_the_deadline(self, tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        index = _settled(build_link_index(str(tree)))
        monkeypatch.setattr(link_index, "VERIFY_DEADLINE_SECONDS", -1.0)
        result = index.verify()
        assert not result.complete
        assert "deadline" in result.reason

    def test_unreadable_root(self, tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        index = _settled(build_link_index(str(tree)))
        real_lstat = os.lstat

        def refuse_root(path: str | os.PathLike[str]) -> os.stat_result:
            if os.fspath(path) == str(tree):
                raise PermissionError(errno.EACCES, "refused")
            return real_lstat(path)

        monkeypatch.setattr(link_index.os, "lstat", refuse_root)
        result = index.verify()
        assert not result.complete
        assert "unreadable" in result.reason

    def test_a_directory_that_cannot_be_listed_is_judged_as_holding_a_link(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_scandir = os.scandir

        def refuse(path: str) -> Iterator[os.DirEntry[str]]:
            if os.fspath(path) == str(tree / "plain"):
                raise PermissionError(errno.EACCES, "refused")
            return real_scandir(path)

        monkeypatch.setattr(link_index.os, "scandir", refuse)
        result = _settled(build_link_index(str(tree))).verify()
        assert str(tree / "plain") in result.value.holding

    def test_a_directory_that_cannot_be_listed_stops_the_verification(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plan 00623 adversarial review: what lies UNDER an unlistable directory is
        unknown (a searchable but unreadable directory still lets bash `cd` through
        it), so the index cannot say it found every link: the result is stopped."""
        real_scandir = os.scandir

        def refuse(path: str) -> Iterator[os.DirEntry[str]]:
            if os.fspath(path) == str(tree / "plain"):
                raise PermissionError(errno.EACCES, "refused")
            return real_scandir(path)

        monkeypatch.setattr(link_index.os, "scandir", refuse)
        result = _settled(build_link_index(str(tree))).verify()
        assert not result.complete
        assert "listed" in result.reason

    def test_corrupt(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        index.corrupt_for_tests()
        result = index.verify()
        assert not result.complete
        assert "corrupt" in result.reason

    def test_a_link_whose_target_cannot_be_told_stops_the_verification(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        index = _settled(build_link_index(str(tree)))
        real_stat = os.stat

        def refuse(path: str | os.PathLike[str], *, follow_symlinks: bool = True) -> os.stat_result:
            if os.fspath(path) == str(tree / "flink"):
                raise PermissionError(errno.EACCES, "refused")
            return real_stat(path, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(link_index.os, "stat", refuse)
        result = index.verify()
        assert not result.complete

    def test_a_link_loop_is_no_directory_and_does_not_stop_it(self, tree: Path) -> None:
        index = _settled(build_link_index(str(tree)))
        (tree / "plain" / "l1").symlink_to(tree / "plain" / "l2")
        (tree / "plain" / "l2").symlink_to(tree / "plain" / "l1")
        holding, directory_links = _scan(index)
        assert str(tree / "plain") in holding
        assert str(tree / "plain" / "l1") not in directory_links


class TestCache:
    def test_no_index_until_one_is_built_and_asking_starts_the_build(self, tree: Path) -> None:
        assert link_index.link_scan_for(str(tree)) is None
        link_index.wait_for_link_index(30.0)
        assert link_index.link_scan_for(str(tree)) is not None

    def test_an_overflowed_index_is_rebuilt_in_the_background_not_on_the_call(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(link_index, "BUILD_DIRECTORY_CAP", 2)
        link_index.prewarm(str(tree))
        link_index.wait_for_link_index(30.0)
        result = link_index.link_scan_for(str(tree))
        assert result is not None
        assert not result.complete

    def test_nothing_is_written_to_disk(self, tree: Path) -> None:
        before = sorted(str(path) for path in tree.parent.rglob("*"))
        link_index.prewarm(str(tree))
        link_index.wait_for_link_index(30.0)
        link_index.link_scan_for(str(tree))
        assert sorted(str(path) for path in tree.parent.rglob("*")) == before
