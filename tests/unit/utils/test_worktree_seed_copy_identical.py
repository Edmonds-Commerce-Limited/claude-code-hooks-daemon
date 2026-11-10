"""Tests for ``seed_copy_is_identical`` and ``configured_seed_entries`` (Plan 00579)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.worktree_seed_report import configured_seed_entries
from claude_code_hooks_daemon.utils.worktree_seeding import seed_copy_is_identical


class TestSeedCopyIsIdentical:
    def test_equal_files(self, tmp_path: Path) -> None:
        (tmp_path / "a").write_bytes(b"x" * 200_000)
        (tmp_path / "b").write_bytes(b"x" * 200_000)
        assert seed_copy_is_identical(tmp_path / "a", tmp_path / "b") is True

    def test_late_difference_in_a_large_file(self, tmp_path: Path) -> None:
        (tmp_path / "a").write_bytes(b"x" * 200_000)
        (tmp_path / "b").write_bytes(b"x" * 199_999 + b"y")
        assert seed_copy_is_identical(tmp_path / "a", tmp_path / "b") is False

    def test_size_mismatch(self, tmp_path: Path) -> None:
        (tmp_path / "a").write_bytes(b"x")
        (tmp_path / "b").write_bytes(b"xx")
        assert seed_copy_is_identical(tmp_path / "a", tmp_path / "b") is False

    def test_missing_source(self, tmp_path: Path) -> None:
        (tmp_path / "b").write_bytes(b"x")
        assert seed_copy_is_identical(tmp_path / "a", tmp_path / "b") is False

    def test_unreadable_file_is_not_identical(self, tmp_path: Path) -> None:
        (tmp_path / "a").write_bytes(b"x")
        (tmp_path / "b").write_bytes(b"x")
        (tmp_path / "b").chmod(0)
        try:
            readable = (tmp_path / "b").open("rb")
        except PermissionError:
            assert seed_copy_is_identical(tmp_path / "a", tmp_path / "b") is False
        else:
            readable.close()
            pytest.skip("running as a user that ignores file modes")

    def test_symlinks_compare_by_target(self, tmp_path: Path) -> None:
        (tmp_path / "t").write_text("x")
        (tmp_path / "s1").symlink_to("t")
        (tmp_path / "s2").symlink_to("t")
        (tmp_path / "s3").symlink_to("other")
        assert seed_copy_is_identical(tmp_path / "s1", tmp_path / "s2") is True
        assert seed_copy_is_identical(tmp_path / "s1", tmp_path / "s3") is False
        assert seed_copy_is_identical(tmp_path / "s1", tmp_path / "t") is False

    def test_directory_with_a_symlinked_subdirectory(self, tmp_path: Path) -> None:
        for name, target in (("src", "d1"), ("cp", "d2")):
            (tmp_path / name).mkdir()
            (tmp_path / name / "link").symlink_to(target)
        assert seed_copy_is_identical(tmp_path / "src", tmp_path / "cp") is False
        (tmp_path / "cp" / "link").unlink()
        (tmp_path / "cp" / "link").symlink_to("d1")
        assert seed_copy_is_identical(tmp_path / "src", tmp_path / "cp") is True

    def test_file_against_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a").write_text("x")
        (tmp_path / "b").mkdir()
        assert seed_copy_is_identical(tmp_path / "a", tmp_path / "b") is False
        assert seed_copy_is_identical(tmp_path / "b", tmp_path / "a") is False


class TestConfiguredSeedEntries:
    def test_no_config(self, tmp_path: Path) -> None:
        assert configured_seed_entries(tmp_path) == []

    def test_yml_spelling_is_read(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yml").write_text(
            "handlers:\n  worktree_create:\n    worktree_create:\n      options:\n"
            "        seed:\n          entries:\n            - .env\n",
            encoding="utf-8",
        )
        assert [entry.path for entry in configured_seed_entries(tmp_path)] == [".env"]

    def test_non_mapping_config_gives_nothing(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text("- a\n- b\n", encoding="utf-8")
        assert configured_seed_entries(tmp_path) == []


class TestComparisonBudget:
    def test_a_file_over_the_byte_budget_counts_as_differing(self, tmp_path: Path) -> None:
        (tmp_path / "a").write_bytes(b"x" * 100)
        (tmp_path / "b").write_bytes(b"x" * 100)
        assert seed_copy_is_identical(tmp_path / "a", tmp_path / "b", max_bytes=99) is False
        assert seed_copy_is_identical(tmp_path / "a", tmp_path / "b", max_bytes=100) is True

    def _tree(self, root: Path) -> None:
        root.mkdir()
        for name in ("one", "two", "three"):
            (root / name).write_bytes(b"x" * 10)

    def test_a_directory_over_the_file_budget_counts_as_differing(self, tmp_path: Path) -> None:
        self._tree(tmp_path / "s")
        self._tree(tmp_path / "c")
        assert seed_copy_is_identical(tmp_path / "s", tmp_path / "c", max_files=2) is False
        assert seed_copy_is_identical(tmp_path / "s", tmp_path / "c", max_files=3) is True

    def test_a_directory_over_the_byte_budget_counts_as_differing(self, tmp_path: Path) -> None:
        self._tree(tmp_path / "s")
        self._tree(tmp_path / "c")
        assert seed_copy_is_identical(tmp_path / "s", tmp_path / "c", max_bytes=29) is False
        assert seed_copy_is_identical(tmp_path / "s", tmp_path / "c", max_bytes=30) is True

    def test_a_self_referencing_symlink_compares_by_target(self, tmp_path: Path) -> None:
        (tmp_path / "s").mkdir()
        (tmp_path / "c").mkdir()
        (tmp_path / "s" / "f").symlink_to(tmp_path / "s" / "f")
        (tmp_path / "c" / "f").symlink_to(tmp_path / "s" / "f")
        assert seed_copy_is_identical(tmp_path / "s", tmp_path / "c") is True
