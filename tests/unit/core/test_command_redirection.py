"""Tests for command redirection utility module."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.command_redirection import (
    COMMAND_REDIRECTION_SUBDIR,
    DEFAULT_TIMEOUT_SECONDS,
    CommandRedirectionResult,
    cleanup_old_files,
    execute_and_save,
    format_redirection_context,
)


class TestCommandRedirectionResult:
    """Tests for CommandRedirectionResult dataclass."""

    def test_dataclass_fields(self) -> None:
        """Should have exit_code, output_path, and command fields."""
        result = CommandRedirectionResult(
            exit_code=0,
            output_path=Path("/tmp/test.txt"),
            command="echo hello",
        )
        assert result.exit_code == 0
        assert result.output_path == Path("/tmp/test.txt")
        assert result.command == "echo hello"

    def test_success_property(self) -> None:
        """Should report success when exit_code is 0."""
        result = CommandRedirectionResult(
            exit_code=0, output_path=Path("/tmp/test.txt"), command="echo hello"
        )
        assert result.success is True

    def test_failure_property(self) -> None:
        """Should report failure when exit_code is non-zero."""
        result = CommandRedirectionResult(
            exit_code=1, output_path=Path("/tmp/test.txt"), command="echo hello"
        )
        assert result.success is False


class TestExecuteAndSave:
    """Tests for execute_and_save function."""

    def test_runs_command_and_captures_output(self, tmp_path: Path) -> None:
        """Should run command, capture stdout, and write to file."""
        result = execute_and_save(
            command=["echo", "hello world"],
            output_dir=tmp_path,
            label="test_echo",
        )
        assert result.exit_code == 0
        assert result.output_path.exists()
        content = result.output_path.read_text()
        assert "hello world" in content

    def test_captures_stderr(self, tmp_path: Path) -> None:
        """Should capture stderr in the output file."""
        result = execute_and_save(
            command=["bash", "-c", "echo error_msg >&2"],
            output_dir=tmp_path,
            label="test_stderr",
        )
        content = result.output_path.read_text()
        assert "error_msg" in content

    def test_captures_exit_code_success(self, tmp_path: Path) -> None:
        """Should capture exit code 0 for successful commands."""
        result = execute_and_save(
            command=["true"],
            output_dir=tmp_path,
            label="test_success",
        )
        assert result.exit_code == 0

    def test_captures_exit_code_failure(self, tmp_path: Path) -> None:
        """Should capture non-zero exit code for failing commands."""
        result = execute_and_save(
            command=["false"],
            output_dir=tmp_path,
            label="test_failure",
        )
        assert result.exit_code != 0

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """Should create output directory if it doesn't exist."""
        output_dir = tmp_path / "nested" / "dir"
        assert not output_dir.exists()

        result = execute_and_save(
            command=["echo", "test"],
            output_dir=output_dir,
            label="test_mkdir",
        )
        assert output_dir.exists()
        assert result.output_path.exists()

    def test_output_file_naming(self, tmp_path: Path) -> None:
        """Should include label in the output filename."""
        result = execute_and_save(
            command=["echo", "test"],
            output_dir=tmp_path,
            label="my_handler",
        )
        assert "my_handler" in result.output_path.name
        assert result.output_path.suffix == ".txt"

    def test_stores_command_in_result(self, tmp_path: Path) -> None:
        """Should store the command string in the result."""
        result = execute_and_save(
            command=["echo", "hello"],
            output_dir=tmp_path,
            label="test",
        )
        assert result.command == "echo hello"

    def test_timeout_handling(self, tmp_path: Path) -> None:
        """Should handle command timeout gracefully."""
        result = execute_and_save(
            command=["sleep", "10"],
            output_dir=tmp_path,
            label="test_timeout",
            timeout_seconds=1,
        )
        # Should return non-zero exit code on timeout
        assert result.exit_code != 0
        assert result.output_path.exists()
        content = result.output_path.read_text()
        assert "timed out" in content.lower()

    def test_default_timeout(self) -> None:
        """Should have a sensible default timeout."""
        assert DEFAULT_TIMEOUT_SECONDS == 30

    def test_output_includes_header(self, tmp_path: Path) -> None:
        """Should include command and exit code in output file header."""
        result = execute_and_save(
            command=["echo", "test output"],
            output_dir=tmp_path,
            label="test_header",
        )
        content = result.output_path.read_text()
        assert "echo test output" in content
        assert "Exit code: 0" in content


class TestFormatRedirectionContext:
    """Tests for format_redirection_context function."""

    def test_produces_context_lines(self) -> None:
        """Should produce a list of context lines."""
        result = CommandRedirectionResult(
            exit_code=0,
            output_path=Path("/workspace/untracked/command-redirection/test.txt"),
            command="gh issue view 123 --comments",
        )
        context = format_redirection_context(result)
        assert isinstance(context, list)
        assert len(context) > 0

    def test_includes_redirected_marker(self) -> None:
        """Should include COMMAND REDIRECTED marker."""
        result = CommandRedirectionResult(
            exit_code=0,
            output_path=Path("/workspace/untracked/test.txt"),
            command="echo hello",
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "COMMAND REDIRECTED" in joined

    def test_includes_exit_code(self) -> None:
        """Should include exit code in context."""
        result = CommandRedirectionResult(
            exit_code=0,
            output_path=Path("/workspace/untracked/test.txt"),
            command="echo hello",
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "Exit code: 0" in joined

    def test_includes_output_path(self) -> None:
        """Should include output file path in context."""
        result = CommandRedirectionResult(
            exit_code=0,
            output_path=Path("/workspace/untracked/test.txt"),
            command="echo hello",
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "/workspace/untracked/test.txt" in joined

    def test_includes_read_instruction(self) -> None:
        """Should tell Claude to read the output file."""
        result = CommandRedirectionResult(
            exit_code=0,
            output_path=Path("/workspace/untracked/test.txt"),
            command="echo hello",
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "Read" in joined or "read" in joined


class TestCleanupOldFiles:
    """Tests for cleanup_old_files function."""

    def test_removes_files_older_than_max_age(self, tmp_path: Path) -> None:
        """Should remove files older than max_age_seconds."""
        old_file = tmp_path / "old_output.txt"
        old_file.write_text("old content")
        # Set mtime to 2 hours ago
        old_time = time.time() - 7200
        os.utime(old_file, (old_time, old_time))

        cleanup_old_files(tmp_path, max_age_seconds=3600)
        assert not old_file.exists()

    def test_keeps_recent_files(self, tmp_path: Path) -> None:
        """Should keep files newer than max_age_seconds."""
        recent_file = tmp_path / "recent_output.txt"
        recent_file.write_text("recent content")

        cleanup_old_files(tmp_path, max_age_seconds=3600)
        assert recent_file.exists()

    def test_handles_nonexistent_directory(self, tmp_path: Path) -> None:
        """Should handle nonexistent directory gracefully."""
        nonexistent = tmp_path / "does_not_exist"
        # Should not raise
        cleanup_old_files(nonexistent, max_age_seconds=3600)

    def test_only_removes_txt_files(self, tmp_path: Path) -> None:
        """Should only clean up .txt files (output files)."""
        old_txt = tmp_path / "old.txt"
        old_other = tmp_path / "old.log"
        old_txt.write_text("old")
        old_other.write_text("old")
        old_time = time.time() - 7200
        os.utime(old_txt, (old_time, old_time))
        os.utime(old_other, (old_time, old_time))

        cleanup_old_files(tmp_path, max_age_seconds=3600)
        assert not old_txt.exists()
        assert old_other.exists()


class TestConstants:
    """Tests for module constants."""

    def test_subdir_name(self) -> None:
        """Should have a defined subdirectory name constant."""
        assert COMMAND_REDIRECTION_SUBDIR == "command-redirection"

    def test_default_timeout(self) -> None:
        """Should have a 30-second default timeout."""
        assert DEFAULT_TIMEOUT_SECONDS == 30
