"""Tests for daemon single-process enforcement logic."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.daemon.enforcement import enforce_single_daemon


class TestEnforceSingleDaemon:
    """Tests for enforce_single_daemon()."""

    def test_enforcement_disabled_does_nothing(self) -> None:
        """When enforcement disabled, no cleanup happens."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = False

        # Should return immediately without checking anything
        with patch(
            "claude_code_hooks_daemon.daemon.enforcement.is_container_environment"
        ) as mock_container:
            enforce_single_daemon(config=mock_config, pid_path=Path("/tmp/test.pid"))

        # Container check should NOT be called when disabled
        mock_container.assert_not_called()

    def test_single_healthy_daemon_no_action(self) -> None:
        """When only one daemon exists (current process), no action taken."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        current_pid = os.getpid()

        with patch(
            "claude_code_hooks_daemon.daemon.enforcement.is_container_environment", return_value=True
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
            return_value=[current_pid],
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.kill_daemon_process"
        ) as mock_kill:
            enforce_single_daemon(config=mock_config, pid_path=Path("/tmp/test.pid"))

        # Should not kill anything (only daemon is current process)
        mock_kill.assert_not_called()

    def test_multiple_daemons_in_container_cleanup_triggered(self) -> None:
        """In container with multiple daemons, kills all except current."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        current_pid = os.getpid()
        other_pid_1 = current_pid + 1000
        other_pid_2 = current_pid + 2000

        with patch(
            "claude_code_hooks_daemon.daemon.enforcement.is_container_environment", return_value=True
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
            return_value=[current_pid, other_pid_1, other_pid_2],
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.kill_daemon_process"
        ) as mock_kill:
            enforce_single_daemon(config=mock_config, pid_path=Path("/tmp/test.pid"))

        # Should kill the other daemons
        assert mock_kill.call_count == 2
        mock_kill.assert_any_call(other_pid_1)
        mock_kill.assert_any_call(other_pid_2)

    def test_stale_pid_file_cleanup_triggered(self) -> None:
        """When PID file exists but process not running, cleanup triggered."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        pid_path = Path("/tmp/test.pid")
        stale_pid = 99999

        with patch(
            "claude_code_hooks_daemon.daemon.enforcement.is_container_environment", return_value=False
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
            return_value=[],
        ), patch("claude_code_hooks_daemon.daemon.enforcement.read_pid_file", return_value=stale_pid), patch(
            "claude_code_hooks_daemon.daemon.enforcement.is_process_running", return_value=False
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.cleanup_pid_file"
        ) as mock_cleanup:
            enforce_single_daemon(config=mock_config, pid_path=pid_path)

        # Should clean up stale PID file
        mock_cleanup.assert_called_once_with(str(pid_path))

    def test_enforcement_disabled_in_non_container(self) -> None:
        """Outside container with enforcement enabled, uses conservative cleanup."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        current_pid = os.getpid()
        other_pid = current_pid + 1000

        with patch(
            "claude_code_hooks_daemon.daemon.enforcement.is_container_environment", return_value=False
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
            return_value=[current_pid, other_pid],
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.kill_daemon_process"
        ) as mock_kill:
            enforce_single_daemon(config=mock_config, pid_path=Path("/tmp/test.pid"))

        # Outside container: should NOT kill other daemons (could be other projects)
        mock_kill.assert_not_called()

    def test_no_daemon_processes_found(self) -> None:
        """When no daemon processes exist, do nothing."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        with patch(
            "claude_code_hooks_daemon.daemon.enforcement.is_container_environment", return_value=True
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes", return_value=[]
        ), patch(
            "claude_code_hooks_daemon.daemon.enforcement.kill_daemon_process"
        ) as mock_kill:
            enforce_single_daemon(config=mock_config, pid_path=Path("/tmp/test.pid"))

        # No daemons to kill
        mock_kill.assert_not_called()
