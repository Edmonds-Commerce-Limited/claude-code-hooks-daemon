"""Tests for the QA walkers' shared scope helpers (00466 N26).

A QA check that excludes a file because a directory NAME appears in the file's
ABSOLUTE path excludes everything when the checkout itself lives under such a
directory: every agent worktree sits under ``untracked/worktrees/``. And a
check that then reports success after examining nothing is a gate that is
open exactly where branches are verified.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.scan_scope import relative_parts, vacuous_scan_failure


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

    def test_an_empty_tree_is_genuinely_clean(self) -> None:
        assert vacuous_scan_failure(examined=0, candidates=0, noun="files") is None
