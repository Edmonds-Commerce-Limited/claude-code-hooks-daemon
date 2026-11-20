"""Tests for judging the links a link-following recursive read passes through (Plan 00613).

A worktree seeded in link mode holds links into the main checkout. ``grep -R``,
``find -L`` and the like FOLLOW every link below their root, so a protected file
the root does not lexically hold is read through one. :func:`link_reach.reached_through_links`
finds those links (from the verified link index, or a bounded walk) and judges
each target as the direct path would be judged; anything it cannot resolve fails
closed.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import link_index, link_reach, protected_file_index
from claude_code_hooks_daemon.utils.link_reach import LinkFollow, reached_through_links
from claude_code_hooks_daemon.utils.protected_file_index import ProtectedFileIndex
from tests.indexed_project import index_project

_GLOB = "conf/vault.txt"
_PATTERNS = (_GLOB,)


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()
    yield
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "conf").mkdir(parents=True)
    (root / _GLOB).write_bytes(b"not-a-real-secret\n")
    (root / "docs").mkdir()
    (root / "docs" / "readme.txt").write_text("ordinary\n", encoding="utf-8")
    (root / "tree").mkdir()
    return root


def _index(root: Path) -> ProtectedFileIndex:
    return index_project(root, _PATTERNS)


def _with_link_index(root: Path) -> None:
    """Build and settle the link index, so the index path (not the walk) is taken."""
    assert link_index.link_scan_for(str(root)) is None
    link_index.wait_for_link_index(timeout=30)
    held = link_index._indexes[os.path.normpath(str(root))]
    held.age_for_tests(seconds=3600)


@pytest.fixture(params=["walk", "link-index"])
def source(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _reach(root: Path, searched: Path, follow: LinkFollow, source: str) -> str | None:
    index = _index(root)
    if source == "link-index":
        _with_link_index(root)
    return reached_through_links(str(searched), follow, index)


class TestDirectoryLinks:
    def test_a_followed_directory_link_to_a_protected_directory_is_reached(
        self, project: Path, source: str
    ) -> None:
        (project / "tree" / "conf").symlink_to(project / "conf")
        assert _reach(project, project / "tree", LinkFollow.ALL, source) == _GLOB

    def test_a_reader_that_follows_only_file_links_does_not_descend_it(
        self, project: Path, source: str
    ) -> None:
        (project / "tree" / "conf").symlink_to(project / "conf")
        assert _reach(project, project / "tree", LinkFollow.FILES, source) is None

    def test_a_reader_that_follows_no_link_is_not_judged(self, project: Path, source: str) -> None:
        (project / "tree" / "conf").symlink_to(project / "conf")
        assert _reach(project, project / "tree", LinkFollow.NONE, source) is None

    def test_a_link_to_an_unprotected_directory_is_not_reached(
        self, project: Path, source: str
    ) -> None:
        (project / "tree" / "docs").symlink_to(project / "docs")
        assert _reach(project, project / "tree", LinkFollow.ALL, source) is None

    def test_a_chain_of_links_is_followed(self, project: Path, source: str) -> None:
        (project / "hop").mkdir()
        (project / "hop" / "next").symlink_to(project / "conf")
        (project / "tree" / "first").symlink_to(project / "hop")
        assert _reach(project, project / "tree", LinkFollow.ALL, source) == _GLOB

    def test_a_link_loop_ends(self, project: Path, source: str) -> None:
        (project / "tree" / "self").symlink_to(project / "tree")
        assert _reach(project, project / "tree", LinkFollow.ALL, source) is None

    def test_a_directory_link_out_of_the_project_fails_closed(
        self, project: Path, tmp_path: Path, source: str
    ) -> None:
        (tmp_path / "elsewhere").mkdir()
        (project / "tree" / "out").symlink_to(tmp_path / "elsewhere")
        assert _reach(project, project / "tree", LinkFollow.ALL, source) == _GLOB

    def test_a_root_above_the_link_reaches_it(self, project: Path, source: str) -> None:
        (project / "tree" / "deep").mkdir()
        (project / "tree" / "deep" / "conf").symlink_to(project / "conf")
        assert _reach(project, project, LinkFollow.ALL, source) == _GLOB


class TestFileLinks:
    def test_a_file_link_to_a_protected_file_is_reached(self, project: Path, source: str) -> None:
        (project / "tree" / "v").symlink_to(project / _GLOB)
        assert _reach(project, project / "tree", LinkFollow.FILES, source) == _GLOB

    def test_a_reader_that_follows_no_link_is_not_judged(self, project: Path, source: str) -> None:
        (project / "tree" / "v").symlink_to(project / _GLOB)
        assert _reach(project, project / "tree", LinkFollow.NONE, source) is None

    def test_a_file_link_to_an_unprotected_file_is_not_reached(
        self, project: Path, source: str
    ) -> None:
        (project / "tree" / "r").symlink_to(project / "docs" / "readme.txt")
        assert _reach(project, project / "tree", LinkFollow.ALL, source) is None

    def test_a_dangling_link_is_not_reached(self, project: Path, source: str) -> None:
        (project / "tree" / "gone").symlink_to(project / "missing")
        assert _reach(project, project / "tree", LinkFollow.ALL, source) is None

    def test_an_exempt_target_is_not_reached(self, project: Path) -> None:
        (project / "tree" / "v").symlink_to(project / _GLOB)
        found = reached_through_links(
            str(project / "tree"), LinkFollow.ALL, _index(project), is_exempt=lambda _path: True
        )
        assert found is None


class TestOutsideTheProject:
    def test_a_root_outside_the_project_is_walked(self, project: Path, tmp_path: Path) -> None:
        outside = tmp_path / "other-worktree"
        outside.mkdir()
        (outside / "conf").symlink_to(project / "conf")
        assert reached_through_links(str(outside), LinkFollow.ALL, _index(project)) == _GLOB


class TestFailClosed:
    def test_a_walk_past_its_cap_fails_closed(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("a", "b", "c"):
            (project / "tree" / name).mkdir()
        monkeypatch.setattr(link_reach, "WALK_DIRECTORY_CAP", 2)
        assert (
            reached_through_links(str(project / "tree"), LinkFollow.ALL, _index(project)) == _GLOB
        )

    def test_too_many_links_fail_closed(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in ("a", "b", "c"):
            (project / "tree" / name).symlink_to(project / "docs")
        monkeypatch.setattr(link_reach, "LINK_CAP", 2)
        assert (
            reached_through_links(str(project / "tree"), LinkFollow.ALL, _index(project)) == _GLOB
        )

    def test_no_patterns_means_nothing_to_reach(self, project: Path) -> None:
        index = ProtectedFileIndex(project_root=str(project), patterns=(), files=())
        (project / "tree" / "conf").symlink_to(project / "conf")
        assert reached_through_links(str(project / "tree"), LinkFollow.ALL, index) is None
