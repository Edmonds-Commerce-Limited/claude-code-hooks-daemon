"""Tests for daemon process verification logic."""

import os
from unittest.mock import MagicMock, patch

import psutil

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.process_verification import (
    find_all_daemon_processes,
    is_process_running,
    kill_daemon_process,
)


class TestFindAllDaemonProcesses:
    """Tests for find_all_daemon_processes()."""

    def test_no_daemon_processes_exist(self) -> None:
        """Returns empty list when no daemon processes found."""
        mock_processes = [
            self._create_mock_process(pid=100, name="python", cmdline=["python", "script.py"]),
            self._create_mock_process(pid=200, name="bash", cmdline=["bash"]),
            self._create_mock_process(pid=300, name="systemd", cmdline=["systemd"]),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert result == []

    def test_single_daemon_process_exists(self) -> None:
        """Returns single PID when one daemon process found."""
        mock_processes = [
            self._create_mock_process(pid=100, name="python", cmdline=["python", "script.py"]),
            self._create_mock_process(
                pid=200,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.server"],
            ),
            self._create_mock_process(pid=300, name="bash", cmdline=["bash"]),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert result == [200]

    def test_multiple_daemon_processes_exist(self) -> None:
        """Returns all PIDs when multiple daemon processes found."""
        mock_processes = [
            self._create_mock_process(
                pid=100,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.server"],
            ),
            self._create_mock_process(pid=200, name="bash", cmdline=["bash"]),
            self._create_mock_process(
                pid=300,
                name="python",
                cmdline=["/usr/bin/python3", "-m", "claude_code_hooks_daemon.daemon.cli"],
            ),
            self._create_mock_process(
                pid=400,
                name="claude_code_hooks_daemon",
                cmdline=["claude_code_hooks_daemon"],
            ),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert sorted(result) == [100, 300, 400]

    def test_process_name_matching_works_correctly(self) -> None:
        """Matches daemon processes by name and cmdline correctly."""
        mock_processes = [
            # Should match: daemon in process name
            self._create_mock_process(pid=100, name="claude_code_hooks_daemon", cmdline=["daemon"]),
            # Should match: daemon in cmdline
            self._create_mock_process(
                pid=200,
                name="python3",
                cmdline=["python3", "-m", "claude_code_hooks_daemon.daemon.server"],
            ),
            # Should NOT match: similar but not exact name
            self._create_mock_process(pid=300, name="daemon", cmdline=["daemon", "start"]),
            # Should match: daemon name in filename (substring matching)
            self._create_mock_process(
                pid=400,
                name="python",
                cmdline=["python", "my_claude_code_hooks_daemon_wrapper.py"],
            ),
            # Should match: exact module name in cmdline
            self._create_mock_process(
                pid=500,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon"],
            ),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        # PIDs 100, 200, 400, 500 should match ("claude_code_hooks_daemon" substring present)
        assert sorted(result) == [100, 200, 400, 500]

    def test_handles_permission_errors_gracefully(self) -> None:
        """Ignores processes that raise AccessDenied errors."""
        mock_process_ok = self._create_mock_process(
            pid=100,
            name="python",
            cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.server"],
        )
        mock_process_denied = MagicMock(spec=psutil.Process)
        mock_process_denied.pid = 200
        mock_process_denied.name.side_effect = psutil.AccessDenied(pid=200)

        mock_processes = [mock_process_ok, mock_process_denied]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        # Should only find the accessible process
        assert result == [100]

    def test_handles_no_such_process_errors_gracefully(self) -> None:
        """Ignores processes that disappeared during iteration."""
        mock_process_ok = self._create_mock_process(
            pid=100,
            name="python",
            cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.server"],
        )
        mock_process_gone = MagicMock(spec=psutil.Process)
        mock_process_gone.pid = 200
        mock_process_gone.name.side_effect = psutil.NoSuchProcess(pid=200)

        mock_processes = [mock_process_ok, mock_process_gone]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        # Should only find the still-existing process
        assert result == [100]

    def test_excludes_current_process(self) -> None:
        """Does not include the current process PID in results."""
        current_pid = os.getpid()
        mock_processes = [
            self._create_mock_process(
                pid=current_pid,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli"],
            ),
            self._create_mock_process(
                pid=current_pid + 1,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.server"],
            ),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        # Should only include the other process, not current
        assert result == [current_pid + 1]

    @staticmethod
    def _create_mock_process(pid: int, name: str, cmdline: list[str]) -> MagicMock:
        """Create a mock psutil.Process with given attributes."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = pid
        mock_proc.name.return_value = name
        mock_proc.cmdline.return_value = cmdline
        return mock_proc


class TestKillDaemonProcess:
    """Tests for kill_daemon_process()."""

    def test_kill_process_succeeds(self) -> None:
        """Successfully terminates process with SIGTERM."""
        mock_process = MagicMock(spec=psutil.Process)
        mock_process.is_running.return_value = False  # Process terminated

        with patch("psutil.Process", return_value=mock_process):
            result = kill_daemon_process(pid=12345)

        assert result is True
        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once_with(timeout=Timeout.PROCESS_KILL_WAIT)

    def test_kill_process_uses_sigkill_if_sigterm_fails(self) -> None:
        """Uses SIGKILL if process doesn't respond to SIGTERM."""
        mock_process = MagicMock(spec=psutil.Process)
        mock_process.wait.side_effect = psutil.TimeoutExpired(seconds=2)
        mock_process.is_running.return_value = False  # Process eventually terminated

        with patch("psutil.Process", return_value=mock_process):
            result = kill_daemon_process(pid=12345)

        assert result is True
        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once_with(timeout=Timeout.PROCESS_KILL_WAIT)
        mock_process.kill.assert_called_once()

    def test_kill_process_handles_non_existent_pid(self) -> None:
        """Returns False when PID does not exist."""
        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(pid=99999)):
            result = kill_daemon_process(pid=99999)

        assert result is False

    def test_kill_process_handles_permission_denied(self) -> None:
        """Returns False when lacking permission to kill process."""
        mock_process = MagicMock(spec=psutil.Process)
        mock_process.terminate.side_effect = psutil.AccessDenied(pid=12345)

        with patch("psutil.Process", return_value=mock_process):
            result = kill_daemon_process(pid=12345)

        assert result is False

    def test_refuses_to_kill_current_process(self) -> None:
        """Returns False and does not kill if PID is current process."""
        current_pid = os.getpid()

        with patch("psutil.Process") as mock_process_cls:
            result = kill_daemon_process(pid=current_pid)

        assert result is False
        mock_process_cls.assert_not_called()  # Should never create Process object


class TestIsProcessRunning:
    """Tests for is_process_running()."""

    def test_process_is_running(self) -> None:
        """Returns True when process exists and is running."""
        mock_process = MagicMock(spec=psutil.Process)
        mock_process.is_running.return_value = True

        with patch("psutil.Process", return_value=mock_process):
            result = is_process_running(pid=12345)

        assert result is True

    def test_process_is_not_running(self) -> None:
        """Returns False when process exists but is not running."""
        mock_process = MagicMock(spec=psutil.Process)
        mock_process.is_running.return_value = False

        with patch("psutil.Process", return_value=mock_process):
            result = is_process_running(pid=12345)

        assert result is False

    def test_process_does_not_exist(self) -> None:
        """Returns False when PID does not exist."""
        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(pid=99999)):
            result = is_process_running(pid=99999)

        assert result is False

    def test_handles_permission_denied(self) -> None:
        """Returns False when lacking permission to check process."""
        with patch("psutil.Process", side_effect=psutil.AccessDenied(pid=12345)):
            result = is_process_running(pid=12345)

        assert result is False
