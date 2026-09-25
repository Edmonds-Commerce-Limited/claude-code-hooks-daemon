"""Tests for daemon single-process enforcement logic."""

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.enforcement import enforce_single_daemon
from claude_code_hooks_daemon.utils.safe_signal import DaemonStop, RefusedSignalTarget

_STOP = "claude_code_hooks_daemon.daemon.enforcement.stop_verified_daemon"
_PROJECT_ROOT = Path("/workspace")


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

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[current_pid],
            ),
            patch(_STOP) as mock_stop,
        ):
            enforce_single_daemon(
                config=mock_config, pid_path=Path("/tmp/test.pid"), project_root=_PROJECT_ROOT
            )

        # Should not stop anything (only daemon is current process)
        mock_stop.assert_not_called()

    def test_multiple_daemons_in_container_cleanup_triggered(self) -> None:
        """In container with multiple daemons, stops all except current."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        current_pid = os.getpid()
        other_pid_1 = current_pid + 1000
        other_pid_2 = current_pid + 2000

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[current_pid, other_pid_1, other_pid_2],
            ),
            patch(_STOP, return_value=DaemonStop.TERMINATED) as mock_stop,
        ):
            enforce_single_daemon(
                config=mock_config, pid_path=Path("/tmp/test.pid"), project_root=_PROJECT_ROOT
            )

        # Each peer is re-proven against THIS project root before it is signalled.
        assert mock_stop.call_args_list == [
            call(other_pid_1, project_root=_PROJECT_ROOT, grace_seconds=Timeout.PROCESS_KILL_WAIT),
            call(other_pid_2, project_root=_PROJECT_ROOT, grace_seconds=Timeout.PROCESS_KILL_WAIT),
        ]

    def test_stale_pid_file_cleanup_triggered(self) -> None:
        """When PID file exists but process not running, cleanup triggered."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        pid_path = Path("/tmp/test.pid")
        stale_pid = 99999

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=False,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.read_pid_file", return_value=stale_pid
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_process_running", return_value=False
            ),
            patch("claude_code_hooks_daemon.daemon.enforcement.cleanup_pid_file") as mock_cleanup,
        ):
            enforce_single_daemon(config=mock_config, pid_path=pid_path)

        # Should clean up stale PID file
        mock_cleanup.assert_called_once_with(str(pid_path))

    def test_enforcement_disabled_in_non_container(self) -> None:
        """Outside container with enforcement enabled, uses conservative cleanup."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        current_pid = os.getpid()
        other_pid = current_pid + 1000

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=False,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[current_pid, other_pid],
            ),
            patch(_STOP) as mock_stop,
        ):
            enforce_single_daemon(
                config=mock_config, pid_path=Path("/tmp/test.pid"), project_root=_PROJECT_ROOT
            )

        # Outside container: should NOT stop other daemons (could be other projects)
        mock_stop.assert_not_called()

    def test_no_daemon_processes_found(self) -> None:
        """When no daemon processes exist, do nothing."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[],
            ),
            patch(_STOP) as mock_stop,
        ):
            enforce_single_daemon(
                config=mock_config, pid_path=Path("/tmp/test.pid"), project_root=_PROJECT_ROOT
            )

        # No daemons to stop
        mock_stop.assert_not_called()


class TestEnforceSingleDaemonProjectScoping:
    """Enforcement must scope its process search to our own project root.

    Regression for the cross-project daemon-kill outage (H2): a container
    daemon must not SIGTERM a daemon serving a different project root.
    """

    def test_project_root_passed_to_process_search(self) -> None:
        """enforce_single_daemon forwards project_root to find_all_daemon_processes."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[],
            ) as mock_find,
            patch(_STOP),
        ):
            enforce_single_daemon(
                config=mock_config,
                pid_path=Path("/workspace/untracked/daemon-x.pid"),
                project_root=_PROJECT_ROOT,
            )

        mock_find.assert_called_once_with(project_root=_PROJECT_ROOT)

    def test_no_project_root_signals_nothing(self) -> None:
        """Plan 00466 N59: without a project root no peer can be proven ours."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[os.getpid() + 1000],
            ),
            patch(_STOP) as mock_stop,
            patch("claude_code_hooks_daemon.daemon.enforcement.logger") as mock_logger,
        ):
            enforce_single_daemon(config=mock_config, pid_path=Path("/tmp/test.pid"))

        mock_stop.assert_not_called()
        mock_logger.error.assert_called_once()


class TestEnforceSingleDaemonKillFailure:
    """A peer that is refused, unpermitted or survives is logged as an error."""

    def _enforce_with(self, **stop_behaviour: object) -> MagicMock:
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True
        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[12345],
            ),
            patch(_STOP, **stop_behaviour),
            patch("claude_code_hooks_daemon.daemon.enforcement.logger") as mock_logger,
        ):
            enforce_single_daemon(
                config=mock_config, pid_path=Path("/tmp/test.pid"), project_root=_PROJECT_ROOT
            )
        return mock_logger

    def test_a_peer_that_survives_logs_error(self) -> None:
        mock_logger = self._enforce_with(return_value=DaemonStop.SURVIVED)

        mock_logger.error.assert_called_once()
        assert "12345" in str(mock_logger.error.call_args)

    def test_a_refused_peer_logs_error(self) -> None:
        mock_logger = self._enforce_with(side_effect=RefusedSignalTarget("not a daemon"))

        mock_logger.error.assert_called_once()
        assert "12345" in str(mock_logger.error.call_args)

    def test_an_unpermitted_peer_logs_error(self) -> None:
        mock_logger = self._enforce_with(side_effect=PermissionError("denied"))

        mock_logger.error.assert_called_once()
        assert "12345" in str(mock_logger.error.call_args)
