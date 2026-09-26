"""Tests for the QA walkers' shared scope helpers (00466 N26).

A QA check that excludes a file because a directory NAME appears in the file's
ABSOLUTE path excludes everything when the checkout itself lives under such a
directory: every agent worktree sits under ``untracked/worktrees/``. And a
check that then reports success after examining nothing is a gate that is
open exactly where branches are verified.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from claude_code_hooks_daemon.utils import scan_scope
from claude_code_hooks_daemon.utils.scan_scope import (
    relative_parts,
    vacuous_scan_failure,
    walk_files,
)


def _touch(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_the_module_imports_only_the_standard_library() -> None:
    """audit_capture_corruption loads it by path under a bare python3, with no
    third-party packages available, so one non-stdlib import breaks that audit."""
    source = Path(scan_scope.__file__).read_text(encoding="utf-8")
    imported = {
        name.split(".")[0]
        for node in ast.walk(ast.parse(source))
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        )
    }
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


class TestWalkFiles:
    def test_yields_matching_files_in_sorted_order(self, tmp_path: Path) -> None:
        _touch(tmp_path / "b.py")
        _touch(tmp_path / "pkg" / "a.py")
        _touch(tmp_path / "notes.md")
        assert [p.relative_to(tmp_path).as_posix() for p in walk_files(tmp_path, "*.py")] == [
            "b.py",
            "pkg/a.py",
        ]

    def test_every_file_by_default(self, tmp_path: Path) -> None:
        _touch(tmp_path / "a.txt")
        _touch(tmp_path / "d" / "b.md")
        assert len(walk_files(tmp_path)) == 2

    def test_the_roots_own_git_directory_is_skipped(self, tmp_path: Path) -> None:
        _touch(tmp_path / ".git" / "hooks" / "pre-commit.py")
        _touch(tmp_path / "real.py")
        assert walk_files(tmp_path, "*.py") == [tmp_path / "real.py"]

    def test_a_nested_repository_is_skipped(self, tmp_path: Path) -> None:
        _touch(tmp_path / "vendor" / "lib" / ".git" / "HEAD")
        _touch(tmp_path / "vendor" / "lib" / "mod.py")
        _touch(tmp_path / "vendor" / "own.py")
        assert walk_files(tmp_path, "*.py") == [tmp_path / "vendor" / "own.py"]

    def test_a_linked_worktree_marked_by_a_git_file_is_skipped(self, tmp_path: Path) -> None:
        _touch(tmp_path / "wt" / ".git", "gitdir: /elsewhere\n")
        _touch(tmp_path / "wt" / "mod.py")
        _touch(tmp_path / "own.py")
        assert walk_files(tmp_path, "*.py") == [tmp_path / "own.py"]

    def test_a_root_that_is_itself_a_checkout_is_still_walked(self, tmp_path: Path) -> None:
        _touch(tmp_path / ".git", "gitdir: /elsewhere\n")
        _touch(tmp_path / "mod.py")
        assert walk_files(tmp_path) == [tmp_path / "mod.py"]

    def test_a_missing_root_yields_nothing(self, tmp_path: Path) -> None:
        assert walk_files(tmp_path / "absent") == []


class TestRelativeParts:
    def test_the_checkout_location_is_not_part_of_the_answer(self, tmp_path: Path) -> None:
        root = tmp_path / "untracked" / "worktrees" / "wt"
        path = root / "src" / "pkg" / "module.py"
        assert relative_parts(path, root) == ("src", "pkg", "module.py")

    def test_a_directory_name_inside_the_tree_still_counts(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        path = root / "untracked" / "scratch" / "notes.md"
        assert relative_parts(path, root) == ("untracked", "scratch", "notes.md")

    def test_a_relative_path_is_taken_as_already_relative(self) -> None:
        assert relative_parts(Path("src/a.py"), Path("/anywhere")) == ("src", "a.py")

    def test_a_symlinked_root_is_matched_on_its_real_location(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        (real / "src").mkdir(parents=True)
        link = tmp_path / "link"
        link.symlink_to(real)
        assert relative_parts(real / "src" / "a.py", link) == ("src", "a.py")

    def test_a_path_outside_the_root_keeps_its_own_parts_below_the_anchor(
        self, tmp_path: Path
    ) -> None:
        outside = tmp_path / "elsewhere" / "a.py"
        parts = relative_parts(outside, tmp_path / "repo")
        assert parts[-2:] == ("elsewhere", "a.py")
        assert "/" not in parts


class TestVacuousScanFailure:
    def test_examining_nothing_when_candidates_exist_fails(self) -> None:
        message = vacuous_scan_failure(examined=0, candidates=12, noun="files")
        assert message is not None
        assert "0 of 12 files" in message

    def test_examining_something_is_not_vacuous(self) -> None:
        assert vacuous_scan_failure(examined=3, candidates=12, noun="files") is None

    def test_an_empty_scan_root_fails(self) -> None:
        message = vacuous_scan_failure(examined=0, candidates=0, noun="files")
        assert message is not None
        assert "found no files" in message

    def test_the_failure_names_the_scan_root(self, tmp_path: Path) -> None:
        root = tmp_path / "absent"
        message = vacuous_scan_failure(examined=0, candidates=0, noun="files", root=root)
        assert message is not None
        assert str(root) in message
        assert "does not exist" in message

    def test_an_existing_empty_root_is_named_as_empty(self, tmp_path: Path) -> None:
        message = vacuous_scan_failure(examined=0, candidates=0, noun="files", root=tmp_path)
        assert message is not None
        assert f"found no files under {tmp_path}" in message

    def test_candidates_default_to_what_was_examined(self) -> None:
        assert vacuous_scan_failure(examined=4, noun="files") is None
        assert vacuous_scan_failure(examined=0, noun="files") is not None
