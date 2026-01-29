"""Tests for cmd_start daemon fork/daemonization logic.

Covers the complex fork-based daemonization in cmd_start (lines 207-311),
which requires careful mocking of os.fork, os.setsid, and related syscalls.
"""

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_start


class TestCmdStartAlreadyRunning:
    """Tests for cmd_start when daemon is already running."""

    def test_already_running_returns_zero(self, tmp_path: Path) -> None:
        """cmd_start returns 0 if daemon already running (PID file exists)."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=9999,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
        ):
            result = cmd_start(args)
            assert result == 0


class TestCmdStartParentProcess:
    """Tests for the parent branch after first fork (pid > 0)."""

    def test_parent_success_pid_file_created(self, tmp_path: Path) -> None:
        """Parent process returns 0 when PID file is created after fork."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                side_effect=[None, 42],  # First: not running, second: daemon started
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch("os.fork", return_value=100),  # Parent gets child PID
            patch("time.sleep"),
        ):
            result = cmd_start(args)
            assert result == 0

    def test_parent_failure_no_pid_file(self, tmp_path: Path) -> None:
        """Parent process returns 1 when no PID file created after fork."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,  # Always None - daemon failed to start
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch("os.fork", return_value=100),
            patch("time.sleep"),
        ):
            result = cmd_start(args)
            assert result == 1

    def test_first_fork_oserror(self, tmp_path: Path) -> None:
        """cmd_start returns 1 when first fork fails with OSError."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch("os.fork", side_effect=OSError("fork failed")),
        ):
            result = cmd_start(args)
            assert result == 1


class TestCmdStartChildProcess:
    """Tests for the child branch after first fork (pid == 0)."""

    def test_child_second_fork_parent_exits(self, tmp_path: Path) -> None:
        """First child exits after second fork returns pid > 0."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch("os.fork", side_effect=[0, 200]),  # First fork: child, second fork: parent
            patch("os.chdir"),
            patch("os.setsid"),
            patch("os.umask"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cmd_start(args)
            assert exc_info.value.code == 0

    def test_child_second_fork_oserror(self, tmp_path: Path) -> None:
        """First child exits with error when second fork fails."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch("os.fork", side_effect=[0, OSError("second fork failed")]),
            patch("os.chdir"),
            patch("os.setsid"),
            patch("os.umask"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cmd_start(args)
            assert exc_info.value.code == 1

    def test_daemon_process_runs_server(self, tmp_path: Path) -> None:
        """Second child (daemon) sets up and runs the server."""
        args = argparse.Namespace(project_root=tmp_path)

        mock_config = MagicMock()
        mock_config.daemon.socket_path = None
        mock_config.daemon.pid_file_path = None
        mock_config.daemon.get_socket_path.return_value = tmp_path / "sock"
        mock_config.daemon.get_pid_file_path.return_value = tmp_path / "pid"
        # Set up handler configs
        for attr in [
            "pre_tool_use",
            "post_tool_use",
            "session_start",
            "session_end",
            "pre_compact",
            "user_prompt_submit",
            "permission_request",
            "notification",
            "stop",
            "subagent_stop",
        ]:
            getattr(mock_config.handlers, attr).items.return_value = []

        mock_daemon = MagicMock()
        mock_controller = MagicMock()

        mock_devnull = MagicMock()
        mock_devnull.fileno.return_value = 99

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch("os.fork", side_effect=[0, 0]),  # Both forks return 0 (child)
            patch("os.chdir"),
            patch("os.setsid"),
            patch("os.umask"),
            patch("os.dup2"),
            patch.object(sys, "stdin", MagicMock()),
            patch("pathlib.Path.open", return_value=mock_devnull),
            patch(
                "claude_code_hooks_daemon.config.models.Config.find_and_load",
                return_value=mock_config,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.controller.DaemonController",
                return_value=mock_controller,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.server.HooksDaemon",
                return_value=mock_daemon,
            ),
            patch("asyncio.run"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cmd_start(args)
            assert exc_info.value.code == 0

    def test_daemon_process_crash(self, tmp_path: Path) -> None:
        """Daemon exits with error when server crashes."""
        args = argparse.Namespace(project_root=tmp_path)

        mock_config = MagicMock()
        mock_config.daemon.socket_path = None
        mock_config.daemon.pid_file_path = None
        mock_config.daemon.get_socket_path.return_value = tmp_path / "sock"
        mock_config.daemon.get_pid_file_path.return_value = tmp_path / "pid"
        for attr in [
            "pre_tool_use",
            "post_tool_use",
            "session_start",
            "session_end",
            "pre_compact",
            "user_prompt_submit",
            "permission_request",
            "notification",
            "stop",
            "subagent_stop",
        ]:
            getattr(mock_config.handlers, attr).items.return_value = []

        mock_daemon = MagicMock()
        mock_controller = MagicMock()
        mock_devnull = MagicMock()
        mock_devnull.fileno.return_value = 99

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch("os.fork", side_effect=[0, 0]),
            patch("os.chdir"),
            patch("os.setsid"),
            patch("os.umask"),
            patch("os.dup2"),
            patch.object(sys, "stdin", MagicMock()),
            patch("pathlib.Path.open", return_value=mock_devnull),
            patch(
                "claude_code_hooks_daemon.config.models.Config.find_and_load",
                return_value=mock_config,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.controller.DaemonController",
                return_value=mock_controller,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.server.HooksDaemon",
                return_value=mock_daemon,
            ),
            patch("asyncio.run", side_effect=RuntimeError("Server crashed")),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cmd_start(args)
            assert exc_info.value.code == 1

    def test_daemon_process_with_existing_paths(self, tmp_path: Path) -> None:
        """Daemon process skips path setup when paths already configured."""
        args = argparse.Namespace(project_root=tmp_path)

        mock_config = MagicMock()
        # Paths already set - should NOT call getters
        mock_config.daemon.socket_path = "/existing/socket"
        mock_config.daemon.pid_file_path = "/existing/pid"
        for attr in [
            "pre_tool_use",
            "post_tool_use",
            "session_start",
            "session_end",
            "pre_compact",
            "user_prompt_submit",
            "permission_request",
            "notification",
            "stop",
            "subagent_stop",
        ]:
            getattr(mock_config.handlers, attr).items.return_value = []

        mock_daemon = MagicMock()
        mock_controller = MagicMock()
        mock_devnull = MagicMock()
        mock_devnull.fileno.return_value = 99

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch("os.fork", side_effect=[0, 0]),
            patch("os.chdir"),
            patch("os.setsid"),
            patch("os.umask"),
            patch("os.dup2"),
            patch.object(sys, "stdin", MagicMock()),
            patch("pathlib.Path.open", return_value=mock_devnull),
            patch(
                "claude_code_hooks_daemon.config.models.Config.find_and_load",
                return_value=mock_config,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.controller.DaemonController",
                return_value=mock_controller,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.server.HooksDaemon",
                return_value=mock_daemon,
            ),
            patch("asyncio.run"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                cmd_start(args)
            assert exc_info.value.code == 0
            # Verify getters were NOT called since paths were already set
            mock_config.daemon.get_socket_path.assert_not_called()
            mock_config.daemon.get_pid_file_path.assert_not_called()
