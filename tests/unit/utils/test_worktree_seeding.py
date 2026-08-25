"""Tests for worktree seeding execution (Plan 00267 Phase 3).

Validation and placement are deliberately SEPARATE functions. ``git worktree
add`` happens between them, so every content error must be raised by
:func:`validate_seed_sources` *before* the worktree exists — a half-seeded
worktree is worse than none, because the agent inside it cannot tell which of
its files are missing.

The relocation test is the important one. An earlier attempt at this feature
wrote ABSOLUTE symlink targets, which dangle whenever the same tree is viewed
at two prefixes — a host at ``/home/user/project`` and a container at
``/workspace`` sharing one bind mount, which this project explicitly supports.
That is strictly worse than the problem being solved: the agent gets a BROKEN
link rather than an absent file, and most loaders raise on a dangling link
instead of treating it as absent.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.worktree_seed import (
    SEED_MODE_COPY,
    SEED_MODE_SYMLINK,
    SeedEntry,
)
from claude_code_hooks_daemon.utils.worktree_seeding import (
    WorktreeSeedError,
    seed_worktree,
    validate_seed_sources,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A project root holding the git-ignored local files a worktree wants."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env.local").write_text("SECRET=canonical\n", encoding="utf-8")
    secrets = project / ".secrets"
    secrets.mkdir()
    (secrets / "key.txt").write_text("key-one\n", encoding="utf-8")
    (secrets / "nested").mkdir()
    (secrets / "nested" / "deep.txt").write_text("deep\n", encoding="utf-8")
    return project


@pytest.fixture
def worktree(root: Path) -> Path:
    """A freshly-created worktree directory, as git would have left it."""
    path = root / ".claude" / "worktrees" / "alpha-1234abcd"
    path.mkdir(parents=True)
    return path


class TestValidateSeedSources:
    """Content errors raise BEFORE the worktree is created."""

    def test_valid_entries_pass(self, root: Path) -> None:
        validate_seed_sources(
            root,
            [
                SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
                SeedEntry(path=".secrets", mode=SEED_MODE_COPY),
            ],
        )

    def test_no_entries_passes(self, root: Path) -> None:
        validate_seed_sources(root, [])

    def test_absent_source_raises(self, root: Path) -> None:
        with pytest.raises(WorktreeSeedError, match=r"\.env\.missing"):
            validate_seed_sources(root, [SeedEntry(path=".env.missing", mode=SEED_MODE_SYMLINK)])

    def test_absolute_path_raises(self, root: Path) -> None:
        with pytest.raises(WorktreeSeedError, match="absolute"):
            validate_seed_sources(root, [SeedEntry(path="/etc/passwd", mode=SEED_MODE_COPY)])

    def test_parent_traversal_raises(self, root: Path) -> None:
        with pytest.raises(WorktreeSeedError, match=r"\.\."):
            validate_seed_sources(root, [SeedEntry(path="../outside.env", mode=SEED_MODE_SYMLINK)])

    def test_nested_parent_traversal_raises(self, root: Path) -> None:
        with pytest.raises(WorktreeSeedError, match=r"\.\."):
            validate_seed_sources(root, [SeedEntry(path="a/../../etc/passwd", mode=SEED_MODE_COPY)])

    def test_target_escaping_the_root_via_a_symlinked_component_raises(
        self, root: Path, tmp_path: Path
    ) -> None:
        """The path guard bounds where a link is WRITTEN; this bounds where it POINTS."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "loot.txt").write_text("stolen\n", encoding="utf-8")
        (root / "linkdir").symlink_to(outside)

        with pytest.raises(WorktreeSeedError, match="outside the repository"):
            validate_seed_sources(root, [SeedEntry(path="linkdir/loot.txt", mode=SEED_MODE_COPY)])

    def test_error_names_every_offending_entry(self, root: Path) -> None:
        """One run should report all problems, not just the first."""
        with pytest.raises(WorktreeSeedError) as excinfo:
            validate_seed_sources(
                root,
                [
                    SeedEntry(path=".env.missing", mode=SEED_MODE_SYMLINK),
                    SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
                    SeedEntry(path="/etc/passwd", mode=SEED_MODE_COPY),
                ],
            )
        message = str(excinfo.value)
        assert ".env.missing" in message
        assert "/etc/passwd" in message


class TestSeedSymlinkMode:
    def test_creates_a_link_to_the_canonical_file(self, root: Path, worktree: Path) -> None:
        seed_worktree(root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)])

        dest = worktree / ".env.local"
        assert dest.is_symlink()
        assert dest.read_text(encoding="utf-8") == "SECRET=canonical\n"

    def test_link_target_is_relative(self, root: Path, worktree: Path) -> None:
        seed_worktree(root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)])

        target = (worktree / ".env.local").readlink()
        assert not target.is_absolute(), f"absolute target dangles across prefixes: {target}"

    def test_link_is_live_so_the_main_checkout_stays_the_source_of_truth(
        self, root: Path, worktree: Path
    ) -> None:
        seed_worktree(root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)])

        (root / ".env.local").write_text("SECRET=rotated\n", encoding="utf-8")

        assert (worktree / ".env.local").read_text(encoding="utf-8") == "SECRET=rotated\n"

    def test_link_survives_relocation_to_a_different_prefix(
        self, root: Path, worktree: Path, tmp_path: Path
    ) -> None:
        """The host-vs-container bind-mount case that an absolute target breaks."""
        seed_worktree(root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)])

        relocated = tmp_path / "elsewhere" / "proj"
        relocated.parent.mkdir()
        shutil.copytree(root, relocated, symlinks=True)
        shutil.rmtree(root)

        moved_link = relocated / ".claude" / "worktrees" / "alpha-1234abcd" / ".env.local"
        assert moved_link.is_symlink()
        assert moved_link.read_text(encoding="utf-8") == "SECRET=canonical\n"

    def test_nested_entry_creates_its_parent_directories(self, root: Path, worktree: Path) -> None:
        nested_dir = root / "config"
        nested_dir.mkdir()
        (nested_dir / "local.env").write_text("NESTED=1\n", encoding="utf-8")

        seed_worktree(root, worktree, [SeedEntry(path="config/local.env", mode=SEED_MODE_SYMLINK)])

        dest = worktree / "config" / "local.env"
        assert dest.is_symlink()
        assert dest.read_text(encoding="utf-8") == "NESTED=1\n"

    def test_directory_entry_is_linked_as_one_link(self, root: Path, worktree: Path) -> None:
        seed_worktree(root, worktree, [SeedEntry(path=".secrets", mode=SEED_MODE_SYMLINK)])

        dest = worktree / ".secrets"
        assert dest.is_symlink()
        assert (dest / "nested" / "deep.txt").read_text(encoding="utf-8") == "deep\n"


class TestSeedCopyMode:
    def test_file_copy_is_independent_of_the_source(self, root: Path, worktree: Path) -> None:
        seed_worktree(root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)])

        (root / ".env.local").write_text("SECRET=rotated\n", encoding="utf-8")

        dest = worktree / ".env.local"
        assert not dest.is_symlink()
        assert dest.read_text(encoding="utf-8") == "SECRET=canonical\n"

    def test_writing_the_copy_does_not_touch_the_main_checkout(
        self, root: Path, worktree: Path
    ) -> None:
        """The isolation that makes copy the safe mode for anything writable."""
        seed_worktree(root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)])

        (worktree / ".env.local").write_text("SECRET=clobbered\n", encoding="utf-8")

        assert (root / ".env.local").read_text(encoding="utf-8") == "SECRET=canonical\n"

    def test_directory_copy_is_recursive(self, root: Path, worktree: Path) -> None:
        seed_worktree(root, worktree, [SeedEntry(path=".secrets", mode=SEED_MODE_COPY)])

        dest = worktree / ".secrets"
        assert dest.is_dir()
        assert not dest.is_symlink()
        assert (dest / "key.txt").read_text(encoding="utf-8") == "key-one\n"
        assert (dest / "nested" / "deep.txt").read_text(encoding="utf-8") == "deep\n"

    def test_nested_entry_creates_its_parent_directories(self, root: Path, worktree: Path) -> None:
        nested_dir = root / "config"
        nested_dir.mkdir()
        (nested_dir / "local.env").write_text("NESTED=1\n", encoding="utf-8")

        seed_worktree(root, worktree, [SeedEntry(path="config/local.env", mode=SEED_MODE_COPY)])

        assert (worktree / "config" / "local.env").read_text(encoding="utf-8") == "NESTED=1\n"


class TestNeverClobber:
    def test_existing_file_at_the_destination_is_left_alone(
        self, root: Path, worktree: Path
    ) -> None:
        dest = worktree / ".env.local"
        dest.write_text("SECRET=worktree-own\n", encoding="utf-8")

        seed_worktree(root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)])

        assert dest.read_text(encoding="utf-8") == "SECRET=worktree-own\n"
        assert not dest.is_symlink()

    def test_dangling_destination_symlink_is_left_alone(self, root: Path, worktree: Path) -> None:
        """``exists()`` is False for a dangling link, so is_symlink() must be checked first."""
        dest = worktree / ".env.local"
        dest.symlink_to("nowhere-at-all")
        assert not dest.exists()

        seed_worktree(root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)])

        assert dest.is_symlink()
        assert str(dest.readlink()) == "nowhere-at-all"

    def test_existing_directory_at_the_destination_is_left_alone(
        self, root: Path, worktree: Path
    ) -> None:
        dest = worktree / ".secrets"
        dest.mkdir()
        (dest / "own.txt").write_text("mine\n", encoding="utf-8")

        seed_worktree(root, worktree, [SeedEntry(path=".secrets", mode=SEED_MODE_COPY)])

        assert (dest / "own.txt").read_text(encoding="utf-8") == "mine\n"
        assert not (dest / "key.txt").exists()


class TestSeedReporting:
    def test_returns_the_paths_it_placed(self, root: Path, worktree: Path) -> None:
        placed = seed_worktree(
            root,
            worktree,
            [
                SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
                SeedEntry(path=".secrets", mode=SEED_MODE_COPY),
            ],
        )
        assert placed == [worktree / ".env.local", worktree / ".secrets"]

    def test_skipped_destinations_are_not_reported_as_placed(
        self, root: Path, worktree: Path
    ) -> None:
        (worktree / ".env.local").write_text("own\n", encoding="utf-8")

        placed = seed_worktree(
            root,
            worktree,
            [
                SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
                SeedEntry(path=".secrets", mode=SEED_MODE_COPY),
            ],
        )
        assert placed == [worktree / ".secrets"]

    def test_no_entries_places_nothing(self, root: Path, worktree: Path) -> None:
        assert seed_worktree(root, worktree, []) == []
