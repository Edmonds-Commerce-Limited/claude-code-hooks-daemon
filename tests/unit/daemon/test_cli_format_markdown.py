"""Tests for the ``format-markdown`` CLI subcommand."""

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_format_markdown

_UNALIGNED_TABLE = (
    "# Test\n"
    "\n"
    "| Field | Key | Type |\n"
    "|-------|-----|------|\n"
    "| A | `x` | int |\n"
    "| Long Name | `y_long` | string |\n"
)

_ALIGNED_MARKER = "| A         |"  # Unaligned source has `| A |`; aligned pads to 9


class TestCmdFormatMarkdownSingleFile:
    def test_formats_single_file_in_place(self, tmp_path: Path) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        args = argparse.Namespace(path=test_file, check=False)

        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in test_file.read_text()

    def test_returns_zero_when_already_formatted(self, tmp_path: Path) -> None:
        test_file = tmp_path / "already.md"
        test_file.write_text("# Heading\n\nJust prose, no tables.\n")
        args = argparse.Namespace(path=test_file, check=False)

        result = cmd_format_markdown(args)

        assert result == 0

    def test_rejects_non_markdown_extension(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        test_file = tmp_path / "notmarkdown.txt"
        test_file.write_text("some text\n")
        args = argparse.Namespace(path=test_file, check=False)

        result = cmd_format_markdown(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not a markdown file" in captured.err.lower()

    def test_rejects_missing_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "nope.md"
        args = argparse.Namespace(path=missing, check=False)

        result = cmd_format_markdown(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err.lower()


class TestCmdFormatMarkdownDirectory:
    def test_formats_all_markdown_files_in_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text(_UNALIGNED_TABLE)
        (tmp_path / "b.md").write_text(_UNALIGNED_TABLE)
        (tmp_path / "skip.txt").write_text("not markdown\n")
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "c.markdown").write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)

        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in (tmp_path / "a.md").read_text()
        assert _ALIGNED_MARKER in (tmp_path / "b.md").read_text()
        assert _ALIGNED_MARKER in (nested / "c.markdown").read_text()
        assert (tmp_path / "skip.txt").read_text() == "not markdown\n"

    def test_empty_directory_returns_zero(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        args = argparse.Namespace(path=empty, check=False)

        result = cmd_format_markdown(args)

        assert result == 0


class TestCmdFormatMarkdownCheckMode:
    def test_check_mode_returns_one_when_formatting_needed(self, tmp_path: Path) -> None:
        test_file = tmp_path / "doc.md"
        original = _UNALIGNED_TABLE
        test_file.write_text(original)
        args = argparse.Namespace(path=test_file, check=True)

        result = cmd_format_markdown(args)

        assert result == 1
        # Check mode must NOT modify the file
        assert test_file.read_text() == original

    def test_check_mode_returns_zero_when_already_formatted(self, tmp_path: Path) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text("# Heading\n\nNothing to format.\n")
        args = argparse.Namespace(path=test_file, check=True)

        result = cmd_format_markdown(args)

        assert result == 0

    def test_check_mode_directory_flags_any_unformatted_file(self, tmp_path: Path) -> None:
        (tmp_path / "clean.md").write_text("# Clean\n\nProse only.\n")
        (tmp_path / "dirty.md").write_text(_UNALIGNED_TABLE)
        args = argparse.Namespace(path=tmp_path, check=True)

        result = cmd_format_markdown(args)

        assert result == 1
        # Neither file should have been modified
        assert _ALIGNED_MARKER not in (tmp_path / "dirty.md").read_text()


class TestCmdFormatMarkdownMdformatErrors:
    def test_single_file_mdformat_exception_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        args = argparse.Namespace(path=test_file, check=False)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.mdformat.text",
            side_effect=RuntimeError("boom"),
        ):
            result = cmd_format_markdown(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "boom" in captured.err

    def test_directory_mdformat_exception_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.md").write_text(_UNALIGNED_TABLE)
        args = argparse.Namespace(path=tmp_path, check=False)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.mdformat.text",
            side_effect=RuntimeError("kaboom"),
        ):
            result = cmd_format_markdown(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "kaboom" in captured.err
