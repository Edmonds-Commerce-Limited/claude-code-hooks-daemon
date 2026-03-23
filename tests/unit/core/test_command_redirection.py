"""Tests for command redirection utility module."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.core.command_redirection import (
    COMMAND_REDIRECTION_SUBDIR,
    DEFAULT_TIMEOUT_SECONDS,
    CommandRedirectionResult,
    _reap_background_process,
    cleanup_old_files,
    execute_and_save,
    format_redirection_context,
    launch_and_save,
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

    def test_pid_default_none(self) -> None:
        """Should default pid to None for sync results."""
        result = CommandRedirectionResult(
            exit_code=0, output_path=Path("/tmp/test.txt"), command="echo hello"
        )
        assert result.pid is None

    def test_pid_set_for_async(self) -> None:
        """Should accept pid for async results."""
        result = CommandRedirectionResult(
            exit_code=-1, output_path=Path("/tmp/test.txt"), command="echo hello", pid=12345
        )
        assert result.pid == 12345


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

    def test_async_includes_pid(self) -> None:
        """Should include PID in context for async results."""
        result = CommandRedirectionResult(
            exit_code=-1,
            output_path=Path("/workspace/untracked/test.txt"),
            command="pytest tests/",
            pid=12345,
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "PID 12345" in joined

    def test_async_includes_status_check_command(self) -> None:
        """Should include kill -0 status check for async results."""
        result = CommandRedirectionResult(
            exit_code=-1,
            output_path=Path("/workspace/untracked/test.txt"),
            command="pytest tests/",
            pid=99999,
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "kill -0 99999" in joined

    def test_async_warns_not_to_rerun(self) -> None:
        """Should tell Claude not to re-run the command for async results."""
        result = CommandRedirectionResult(
            exit_code=-1,
            output_path=Path("/workspace/untracked/test.txt"),
            command="npm test",
            pid=54321,
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "DO NOT re-run" in joined

    def test_async_includes_output_path(self) -> None:
        """Should include output file path for async results."""
        result = CommandRedirectionResult(
            exit_code=-1,
            output_path=Path("/workspace/untracked/test.txt"),
            command="pytest tests/",
            pid=12345,
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "/workspace/untracked/test.txt" in joined

    def test_sync_does_not_include_pid(self) -> None:
        """Should NOT include PID info for sync results (pid=None)."""
        result = CommandRedirectionResult(
            exit_code=0,
            output_path=Path("/workspace/untracked/test.txt"),
            command="echo hello",
        )
        context = format_redirection_context(result)
        joined = "\n".join(context)
        assert "PID" not in joined
        assert "kill -0" not in joined


class TestLaunchAndSave:
    """Tests for launch_and_save function (non-blocking async execution)."""

    @staticmethod
    def _kill_if_running(pid: int) -> None:
        """Send SIGTERM to a process if it is still running."""
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return  # Process already exited — nothing to clean up

    def test_returns_immediately_for_slow_command(self, tmp_path: Path) -> None:
        """Should return without waiting for slow commands (the whole point of this fix)."""
        import time as time_mod

        start = time_mod.monotonic()
        result = launch_and_save(
            command=["sleep", "10"],
            output_dir=tmp_path,
            label="test_async",
        )
        elapsed = time_mod.monotonic() - start

        # Must return in under 2 seconds (command sleeps for 10)
        assert elapsed < 2.0
        assert result.pid is not None

        # Clean up the background process
        self._kill_if_running(result.pid)

    def test_returns_result_with_pid(self, tmp_path: Path) -> None:
        """Should return a result with PID set and exit_code -1 (unknown)."""
        result = launch_and_save(
            command=["echo", "hello"],
            output_dir=tmp_path,
            label="test_pid",
        )
        assert result.pid is not None
        assert result.pid > 0
        # exit_code is -1 since we don't wait for completion
        assert result.exit_code == -1

    def test_output_file_created_with_header(self, tmp_path: Path) -> None:
        """Should create output file with command header immediately."""
        result = launch_and_save(
            command=["echo", "test"],
            output_dir=tmp_path,
            label="test_header",
        )
        assert result.output_path.exists()
        content = result.output_path.read_text()
        assert "Command: echo test" in content

    def test_output_file_has_content_after_completion(self, tmp_path: Path) -> None:
        """After process completes, file should have output and exit code."""
        result = launch_and_save(
            command=["echo", "hello world"],
            output_dir=tmp_path,
            label="test_content",
        )
        # Wait for fast command to complete
        time.sleep(1.0)

        content = result.output_path.read_text()
        assert "hello world" in content
        assert "Exit code: 0" in content

    def test_captures_nonzero_exit_code(self, tmp_path: Path) -> None:
        """Should capture non-zero exit code after process completes."""
        result = launch_and_save(
            command=["false"],
            output_dir=tmp_path,
            label="test_fail",
        )
        time.sleep(1.0)

        content = result.output_path.read_text()
        assert "Exit code: 1" in content

    def test_captures_stderr_in_output(self, tmp_path: Path) -> None:
        """Should capture stderr in the output file (2>&1 in wrapper)."""
        result = launch_and_save(
            command=["bash", "-c", "echo error_msg >&2"],
            output_dir=tmp_path,
            label="test_stderr",
        )
        time.sleep(1.0)

        content = result.output_path.read_text()
        assert "error_msg" in content

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """Should create output directory if it doesn't exist."""
        output_dir = tmp_path / "nested" / "dir"
        assert not output_dir.exists()

        result = launch_and_save(
            command=["echo", "test"],
            output_dir=output_dir,
            label="test_mkdir",
        )
        assert output_dir.exists()
        assert result.output_path.exists()

    def test_output_file_naming(self, tmp_path: Path) -> None:
        """Should include label in the output filename."""
        result = launch_and_save(
            command=["echo", "test"],
            output_dir=tmp_path,
            label="my_handler",
        )
        assert "my_handler" in result.output_path.name
        assert result.output_path.suffix == ".txt"

    def test_stores_command_in_result(self, tmp_path: Path) -> None:
        """Should store the command string in the result."""
        result = launch_and_save(
            command=["echo", "hello"],
            output_dir=tmp_path,
            label="test",
        )
        assert result.command == "echo hello"

    def test_cwd_parameter(self, tmp_path: Path) -> None:
        """Should execute command in specified working directory."""
        result = launch_and_save(
            command=["pwd"],
            output_dir=tmp_path,
            label="test_cwd",
            cwd=tmp_path,
        )
        time.sleep(1.0)

        content = result.output_path.read_text()
        assert str(tmp_path) in content


class TestReapBackgroundProcess:
    """Tests for _reap_background_process helper."""

    def test_reaps_completed_process(self) -> None:
        """Should call wait() on the process to reap it."""
        import subprocess

        # Launch a quick process and reap it
        proc = subprocess.Popen(["true"])  # nosec B603 B607
        _reap_background_process(proc)
        assert proc.returncode is not None

    def test_handles_exception_without_crashing(self) -> None:
        """Should log and continue when wait() raises an exception."""
        from unittest.mock import MagicMock

        mock_proc = MagicMock()
        mock_proc.wait.side_effect = OSError("process gone")
        mock_proc.pid = 99999

        # Should not raise
        _reap_background_process(mock_proc)


class TestExecuteAndSaveErrorPaths:
    """Tests for execute_and_save error handling paths."""

    def test_file_not_found_error(self, tmp_path: Path) -> None:
        """Should handle FileNotFoundError when command binary doesn't exist."""
        result = execute_and_save(
            command=["nonexistent_binary_xyz_12345"],
            output_dir=tmp_path,
            label="test_fnf",
        )
        assert result.exit_code == 127
        content = result.output_path.read_text()
        assert "not found" in content.lower() or "No such file" in content

    def test_os_error_handling(self, tmp_path: Path) -> None:
        """Should handle OSError during command execution."""
        with patch(
            "claude_code_hooks_daemon.core.command_redirection.subprocess.run",
            side_effect=OSError("Permission denied"),
        ):
            result = execute_and_save(
                command=["echo", "test"],
                output_dir=tmp_path,
                label="test_oserror",
            )
            assert result.exit_code == 1
            content = result.output_path.read_text()
            assert "Permission denied" in content


class TestLaunchAndSaveErrorPaths:
    """Tests for launch_and_save error handling paths."""

    def test_file_not_found_when_bash_missing(self, tmp_path: Path) -> None:
        """Should handle FileNotFoundError when bash is not found."""
        with patch(
            "claude_code_hooks_daemon.core.command_redirection.subprocess.Popen",
            side_effect=FileNotFoundError("bash not found"),
        ):
            result = launch_and_save(
                command=["echo", "test"],
                output_dir=tmp_path,
                label="test_no_bash",
            )
            assert result.exit_code == 127
            assert result.pid is None
            content = result.output_path.read_text()
            assert "bash not found" in content.lower()

    def test_os_error_handling(self, tmp_path: Path) -> None:
        """Should handle OSError during Popen."""
        with patch(
            "claude_code_hooks_daemon.core.command_redirection.subprocess.Popen",
            side_effect=OSError("Permission denied"),
        ):
            result = launch_and_save(
                command=["echo", "test"],
                output_dir=tmp_path,
                label="test_oserror",
            )
            assert result.exit_code == 1
            assert result.pid is None
            content = result.output_path.read_text()
            assert "Permission denied" in content


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
