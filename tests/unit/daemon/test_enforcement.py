"""Tests for daemon single-process enforcement logic."""

import fcntl
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import psutil
import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon import server
from claude_code_hooks_daemon.daemon.enforcement import enforce_single_daemon
from claude_code_hooks_daemon.daemon.paths import PID_MAX_LIMIT
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

    @pytest.mark.parametrize(
        "caller_root",
        [["--project-root", "/srv/b"], ["--project-r", "/srv/b"], ["--project-root=/srv/b"]],
    )
    def test_a_daemon_launched_for_b_through_as_wrapper_is_never_stopped_by_a(
        self, caller_root: list[str]
    ) -> None:
        """Plan 00466 N203: ``/srv/a``'s ``bin/hooks-daemon --project-root
        /srv/b start`` launches a daemon serving B whose command line names A
        first. Only the process search is real here."""
        daemon_for_b = MagicMock(spec=psutil.Process)
        daemon_for_b.pid = 2**22 + 7
        daemon_for_b.cmdline.return_value = [
            "/usr/bin/python3",
            "-m",
            "claude_code_hooks_daemon.daemon.cli",
            "--project-root",
            "/srv/a",
            *caller_root,
            "start",
        ]
        daemon_for_b.environ.return_value = {}
        daemon_for_b.net_connections.return_value = []
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch("psutil.process_iter", return_value=[daemon_for_b]),
            patch(_STOP) as mock_stop,
        ):
            enforce_single_daemon(
                config=mock_config, pid_path=Path("/tmp/test.pid"), project_root=Path("/srv/a")
            )

        mock_stop.assert_not_called()


class TestAStalePidFileGoesOnlyUnderTheStartLock:
    """Plan 00466 N204: outside a container a stale PID file was removed
    with no start lock, so a successor's pid written between the read and
    the unlink went with it, and another user's live pid, which psutil may
    not inspect, was taken for dead."""

    # A pid a PID file may hold that no process can: pid_max never exceeds
    # PID_MAX_LIMIT, so the largest pid is one below it.
    _UNREAL_PID = PID_MAX_LIMIT

    @staticmethod
    def _enforce(pid_path: Path, socket_path: Path | None) -> None:
        config = MagicMock()
        config.daemon.enforce_single_daemon_process = True
        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=False,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[],
            ),
        ):
            enforce_single_daemon(config=config, pid_path=pid_path, socket_path=socket_path)

    def test_a_file_naming_no_process_is_removed_while_the_lock_is_held(
        self, tmp_path: Path
    ) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(f"{self._UNREAL_PID}\n")
        socket_path = tmp_path / "daemon.sock"
        held: list[bool] = []
        real_unlink = Path.unlink

        def unlink(path: Path, missing_ok: bool = False) -> None:
            fd = os.open(server.start_lock_path(socket_path), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
            except BlockingIOError:
                held.append(True)
            finally:
                os.close(fd)
            real_unlink(path, missing_ok=missing_ok)

        with patch.object(Path, "unlink", unlink):
            self._enforce(pid_path, socket_path)

        assert not pid_path.exists()
        assert held == [True]

    def test_a_start_holding_the_lock_keeps_its_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(f"{self._UNREAL_PID}\n")
        socket_path = tmp_path / "daemon.sock"
        monkeypatch.setattr(Timeout, "FILE_LOCK", 0)
        with server.hold_start_lock(socket_path, Timeout.FILE_LOCK):
            self._enforce(pid_path, socket_path)

        assert pid_path.exists()

    def test_another_users_live_pid_is_not_dead(self, tmp_path: Path) -> None:
        """Tests run as root, so the refusals another user's process meets
        are made to happen: psutil may not read it, and ``kill(pid, 0)`` is
        not permitted."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(f"{self._UNREAL_PID}\n")
        with (
            patch("psutil.Process", side_effect=psutil.AccessDenied(pid=self._UNREAL_PID)),
            patch("os.kill", side_effect=PermissionError(1, "Operation not permitted")),
        ):
            self._enforce(pid_path, tmp_path / "daemon.sock")

        assert pid_path.exists()

    def test_without_a_socket_there_is_no_lock_to_take_so_the_file_stays(
        self, tmp_path: Path
    ) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(f"{self._UNREAL_PID}\n")
        self._enforce(pid_path, None)

        assert pid_path.exists()


class TestEnforceSingleDaemonKillFailure:
    """A peer that is refused, unpermitted or survives is logged as an error."""

    def _enforce_with(self, stop: MagicMock) -> MagicMock:
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
            patch(_STOP, new=stop),
            patch("claude_code_hooks_daemon.daemon.enforcement.logger") as mock_logger,
        ):
            enforce_single_daemon(
                config=mock_config, pid_path=Path("/tmp/test.pid"), project_root=_PROJECT_ROOT
            )
        return mock_logger

    def test_a_peer_that_survives_logs_error(self) -> None:
        mock_logger = self._enforce_with(MagicMock(return_value=DaemonStop.SURVIVED))

        mock_logger.error.assert_called_once()
        assert "12345" in str(mock_logger.error.call_args)

    def test_a_refused_peer_logs_error(self) -> None:
        mock_logger = self._enforce_with(MagicMock(side_effect=RefusedSignalTarget("not a daemon")))

        mock_logger.error.assert_called_once()
        assert "12345" in str(mock_logger.error.call_args)

    def test_an_unpermitted_peer_logs_error(self) -> None:
        mock_logger = self._enforce_with(MagicMock(side_effect=PermissionError("denied")))

        mock_logger.error.assert_called_once()
        assert "12345" in str(mock_logger.error.call_args)
