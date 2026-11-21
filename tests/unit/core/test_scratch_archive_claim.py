"""Claim-by-rename of a scratch entry (Plan 00627 Task 3.2, DESIGN.md section 5.2 steps 2-3).

An entry is renamed to ``.sweeping-<name>`` in the same directory through a
directory descriptor, never replacing anything already there; its fingerprint
is then re-taken and compared with the one the classifier saw, and any change
renames it back.
"""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import scratch_archive_claim as claim_mod
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    CLAIM_PREFIX,
    Claimed,
    ClaimRefused,
    ClaimStuck,
    RenamedBack,
    WalkRefused,
    claim,
    fingerprint_at,
    open_dir,
    release,
    walk_tree,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "scratch"
    path.mkdir()
    return path


@pytest.fixture
def root_fd(root: Path) -> Iterator[int]:
    fd = open_dir(root)
    yield fd
    os.close(fd)


def _entry(root: Path, name: str = "e1") -> Path:
    entry = root / name
    (entry / "sub").mkdir(parents=True)
    (entry / "a.txt").write_text("a")
    (entry / "sub" / "b.txt").write_text("b")
    return entry


class TestFingerprint:
    def test_counts_every_inode_and_reads_newest_ctime_below_the_root(
        self, root: Path, root_fd: int
    ) -> None:
        _entry(root)
        print_ = fingerprint_at(root_fd, "e1", max_inodes=100)
        assert print_.count == 4
        assert print_.root_kind == "dir"
        assert print_.newest_ctime_ns > 0

    def test_a_new_file_changes_it(self, root: Path, root_fd: int) -> None:
        entry = _entry(root)
        before = fingerprint_at(root_fd, "e1", max_inodes=100)
        (entry / "sub" / "c.txt").write_text("c")
        assert fingerprint_at(root_fd, "e1", max_inodes=100) != before

    def test_a_loose_file_entry(self, root: Path, root_fd: int) -> None:
        (root / "notes.txt").write_text("x")
        print_ = fingerprint_at(root_fd, "notes.txt", max_inodes=10)
        assert (print_.count, print_.root_kind) == (1, "file")

    def test_inode_cap_refuses(self, root: Path, root_fd: int) -> None:
        entry = root / "big"
        entry.mkdir()
        for i in range(50):
            (entry / f"f{i}").write_text("")
        with pytest.raises(WalkRefused, match="inode"):
            fingerprint_at(root_fd, "big", max_inodes=20)

    def test_depth_cap_refuses(self, root: Path, root_fd: int) -> None:
        deep = root / "deep"
        deep.mkdir()
        cur = deep
        for _ in range(12):
            cur = cur / "d"
            cur.mkdir()
        with pytest.raises(WalkRefused, match="depth"):
            walk_tree(root_fd, "deep", max_inodes=100, max_depth=5)

    def test_unreadable_directory_refuses(
        self, root: Path, root_fd: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Listing ``sub`` fails with EACCES, injected so it holds for every euid."""
        entry = _entry(root)
        sub_ino = (entry / "sub").stat().st_ino
        real_scandir = os.scandir
        denied: list[int] = []

        def scandir(fd: int) -> Any:
            if os.fstat(fd).st_ino == sub_ino:
                denied.append(fd)
                raise PermissionError(errno.EACCES, "Permission denied")
            return real_scandir(fd)

        monkeypatch.setattr(os, "scandir", scandir)
        with pytest.raises(WalkRefused, match="cannot list a directory"):
            fingerprint_at(root_fd, "e1", max_inodes=100)
        assert len(denied) == 1

    def test_links_are_never_followed(self, root: Path, root_fd: int, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        for i in range(30):
            (outside / f"o{i}").write_text("")
        entry = root / "e1"
        entry.mkdir()
        (entry / "link").symlink_to(outside)
        listing = walk_tree(root_fd, "e1", max_inodes=10, max_depth=10)
        assert [(n.rel, n.kind) for n in listing.nodes] == [("", "dir"), ("link", "symlink")]

    def test_a_missing_entry_refuses(self, root_fd: int) -> None:
        with pytest.raises(WalkRefused):
            fingerprint_at(root_fd, "absent", max_inodes=10)


class TestClaim:
    def test_claims_an_unchanged_entry(self, root: Path, root_fd: int) -> None:
        _entry(root)
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        result = claim(root_fd, "e1", expected, max_inodes=100)
        assert isinstance(result, Claimed)
        assert not (root / "e1").exists()
        assert (root / f"{CLAIM_PREFIX}e1" / "sub" / "b.txt").read_text() == "b"
        assert result.claimed_name == f"{CLAIM_PREFIX}e1"
        result.close()

    def test_claim_changes_the_root_ctime_and_the_fingerprint_ignores_it(
        self, root: Path, root_fd: int
    ) -> None:
        entry = _entry(root)
        before = entry.lstat().st_ctime_ns
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        time.sleep(0.02)
        result = claim(root_fd, "e1", expected, max_inodes=100)
        assert isinstance(result, Claimed)
        after = (root / result.claimed_name).lstat().st_ctime_ns
        assert after != before
        result.close()

    def test_a_write_after_classification_renames_back(self, root: Path, root_fd: int) -> None:
        entry = _entry(root)
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        (entry / "late.txt").write_text("late")
        result = claim(root_fd, "e1", expected, max_inodes=100)
        assert isinstance(result, RenamedBack)
        assert "fingerprint" in result.reason
        assert result.claimed_at_ns > 0
        assert (entry / "late.txt").read_text() == "late"
        assert not (root / f"{CLAIM_PREFIX}e1").exists()

    def test_liveness_failure_renames_back(self, root: Path, root_fd: int) -> None:
        _entry(root)
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        result = claim(root_fd, "e1", expected, max_inodes=100, liveness_ok=lambda: False)
        assert isinstance(result, RenamedBack)
        assert "live" in result.reason
        assert (root / "e1" / "a.txt").exists()

    def test_never_replaces_an_existing_claim_name_dir(self, root: Path, root_fd: int) -> None:
        _entry(root)
        (root / f"{CLAIM_PREFIX}e1").mkdir()
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        with pytest.raises(ClaimRefused):
            claim(root_fd, "e1", expected, max_inodes=100)
        assert (root / "e1" / "a.txt").exists()
        assert (root / f"{CLAIM_PREFIX}e1").is_dir()

    def test_never_replaces_an_existing_claim_name_file(self, root: Path, root_fd: int) -> None:
        (root / "n.txt").write_text("new")
        (root / f"{CLAIM_PREFIX}n.txt").write_text("old")
        expected = fingerprint_at(root_fd, "n.txt", max_inodes=10)
        with pytest.raises(ClaimRefused):
            claim(root_fd, "n.txt", expected, max_inodes=10)
        assert (root / "n.txt").read_text() == "new"
        assert (root / f"{CLAIM_PREFIX}n.txt").read_text() == "old"

    def test_refuses_without_no_replace_rename(
        self, root: Path, root_fd: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _entry(root)
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        monkeypatch.setattr(claim_mod, "_RENAMEAT2", None)
        with pytest.raises(ClaimRefused, match="no-replace"):
            claim(root_fd, "e1", expected, max_inodes=100)
        assert (root / "e1").is_dir()

    @pytest.mark.parametrize("name", ["", ".", "..", "a/b", "../x", f"{CLAIM_PREFIX}e1"])
    def test_refuses_bad_names(self, root: Path, root_fd: int, name: str) -> None:
        (root / "e1").mkdir()
        expected = fingerprint_at(root_fd, "e1", max_inodes=10)
        with pytest.raises(ValueError):
            claim(root_fd, name, expected, max_inodes=10)

    def test_dir_swapped_for_a_symlink_renames_back(
        self, root: Path, root_fd: int, tmp_path: Path
    ) -> None:
        entry = _entry(root)
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        moved = tmp_path / "moved"
        entry.rename(moved)
        (root / "e1").symlink_to(moved)
        result = claim(root_fd, "e1", expected, max_inodes=100)
        assert isinstance(result, RenamedBack)
        assert (root / "e1").is_symlink()
        assert (moved / "a.txt").read_text() == "a"

    def test_symlink_entry_claims_only_the_link(
        self, root: Path, root_fd: int, tmp_path: Path
    ) -> None:
        target = tmp_path / "target"
        target.mkdir()
        (target / "keep").write_text("k")
        (root / "ln").symlink_to(target)
        expected = fingerprint_at(root_fd, "ln", max_inodes=10)
        assert expected.root_kind == "symlink"
        result = claim(root_fd, "ln", expected, max_inodes=10)
        assert isinstance(result, Claimed)
        assert (root / f"{CLAIM_PREFIX}ln").is_symlink()
        assert (target / "keep").read_text() == "k"
        result.close()

    def test_release_renames_back_with_the_claimed_at_time(self, root: Path, root_fd: int) -> None:
        _entry(root)
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        result = claim(root_fd, "e1", expected, max_inodes=100)
        assert isinstance(result, Claimed)
        back = release(result, "pack failed")
        assert back.reason == "pack failed"
        assert back.claimed_at_ns == result.claimed_at_ns
        assert (root / "e1" / "a.txt").exists()

    def test_release_when_the_name_was_retaken_leaves_the_claim(
        self, root: Path, root_fd: int
    ) -> None:
        _entry(root)
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        result = claim(root_fd, "e1", expected, max_inodes=100)
        assert isinstance(result, Claimed)
        (root / "e1").mkdir()
        with pytest.raises(ClaimStuck):
            release(result, "pack failed")
        assert (root / f"{CLAIM_PREFIX}e1" / "a.txt").exists()
        assert (root / "e1").is_dir()

    def test_concurrent_claim_of_the_same_entry_loses(self, root: Path, root_fd: int) -> None:
        _entry(root)
        expected = fingerprint_at(root_fd, "e1", max_inodes=100)
        first = claim(root_fd, "e1", expected, max_inodes=100)
        assert isinstance(first, Claimed)
        with pytest.raises(ClaimRefused):
            claim(root_fd, "e1", expected, max_inodes=100)
        assert (root / f"{CLAIM_PREFIX}e1" / "a.txt").exists()
        first.close()
