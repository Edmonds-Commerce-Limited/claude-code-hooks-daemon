"""Tests for the managed ``.gitattributes`` block (Plan 00552 Task 2.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.git_attributes import (
    BEGIN_MARKER,
    END_MARKER,
    MANAGED_PATTERNS,
    ensure_managed_block,
    main,
)

CONFLICT_MARKER_PREFIXES = ("<<<<<<<", "=======", ">>>>>>>")


def _attrs(root: Path) -> str:
    return (root / ".gitattributes").read_text()


class TestManagedBlockContent:
    """What the block says."""

    def test_patterns_cover_hooks_and_init(self) -> None:
        assert ".claude/hooks/**" in MANAGED_PATTERNS
        assert ".claude/init.sh" in MANAGED_PATTERNS

    def test_settings_json_is_not_covered(self) -> None:
        assert not any("settings.json" in p for p in MANAGED_PATTERNS)

    def test_markers_do_not_resemble_conflict_markers(self) -> None:
        for marker in (BEGIN_MARKER, END_MARKER):
            assert marker.startswith("#")
            assert not marker.startswith(CONFLICT_MARKER_PREFIXES)

    def test_created_block_has_merge_unset_for_each_pattern(self, tmp_path: Path) -> None:
        ensure_managed_block(tmp_path)
        text = _attrs(tmp_path)
        for pattern in MANAGED_PATTERNS:
            assert f"{pattern} -merge" in text.splitlines()

    def test_no_line_resembles_a_conflict_marker(self, tmp_path: Path) -> None:
        ensure_managed_block(tmp_path)
        for line in _attrs(tmp_path).splitlines():
            assert not line.startswith(CONFLICT_MARKER_PREFIXES)


class TestCreateAndIdempotence:
    """Create, re-run, report change."""

    def test_creates_file_and_reports_change(self, tmp_path: Path) -> None:
        assert ensure_managed_block(tmp_path) is True
        text = _attrs(tmp_path)
        assert text.splitlines()[0] == BEGIN_MARKER
        assert text.splitlines()[-1] == END_MARKER
        assert text.endswith("\n")

    def test_reinstall_changes_nothing(self, tmp_path: Path) -> None:
        ensure_managed_block(tmp_path)
        first = _attrs(tmp_path)
        assert ensure_managed_block(tmp_path) is False
        assert _attrs(tmp_path) == first


class TestUserLinesSurvive:
    """Lines outside the block are never touched."""

    def test_existing_lines_kept_before_new_block(self, tmp_path: Path) -> None:
        (tmp_path / ".gitattributes").write_text("*.png binary\n")
        ensure_managed_block(tmp_path)
        text = _attrs(tmp_path)
        assert text.startswith("*.png binary\n")
        assert BEGIN_MARKER in text

    def test_missing_trailing_newline_is_handled(self, tmp_path: Path) -> None:
        (tmp_path / ".gitattributes").write_text("*.png binary")
        ensure_managed_block(tmp_path)
        lines = _attrs(tmp_path).splitlines()
        assert lines[0] == "*.png binary"
        assert BEGIN_MARKER in lines

    def test_lines_before_and_after_existing_block_survive_update(self, tmp_path: Path) -> None:
        stale = f"before line\n{BEGIN_MARKER}\n.claude/old -merge\n{END_MARKER}\nafter line\n"
        (tmp_path / ".gitattributes").write_text(stale)
        assert ensure_managed_block(tmp_path) is True
        text = _attrs(tmp_path)
        assert text.startswith("before line\n")
        assert text.endswith("after line\n")
        assert ".claude/old" not in text
        assert text.count(BEGIN_MARKER) == 1
        assert ".claude/hooks/** -merge" in text

    def test_updated_block_is_then_idempotent(self, tmp_path: Path) -> None:
        stale = f"a\n{BEGIN_MARKER}\nx\n{END_MARKER}\nb\n"
        (tmp_path / ".gitattributes").write_text(stale)
        ensure_managed_block(tmp_path)
        first = _attrs(tmp_path)
        assert ensure_managed_block(tmp_path) is False
        assert _attrs(tmp_path) == first


class TestFailFast:
    """A half-written block is an error, not a guess."""

    def test_begin_without_end_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".gitattributes").write_text(f"{BEGIN_MARKER}\nstuff\n")
        with pytest.raises(ValueError, match="end marker"):
            ensure_managed_block(tmp_path)

    def test_end_without_begin_raises(self, tmp_path: Path) -> None:
        (tmp_path / ".gitattributes").write_text(f"stuff\n{END_MARKER}\n")
        with pytest.raises(ValueError, match="begin marker"):
            ensure_managed_block(tmp_path)

    def test_missing_project_root_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            ensure_managed_block(tmp_path / "absent")


class TestCli:
    """The shell installer calls the module's entry point."""

    def test_main_writes_block(self, tmp_path: Path) -> None:
        assert main(["--project-root", str(tmp_path)]) == 0
        assert BEGIN_MARKER in _attrs(tmp_path)

    def test_main_reports_error_with_exit_one(self, tmp_path: Path) -> None:
        (tmp_path / ".gitattributes").write_text(f"{BEGIN_MARKER}\n")
        assert main(["--project-root", str(tmp_path)]) == 1
