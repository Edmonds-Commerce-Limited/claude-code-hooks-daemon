"""Tests for daemon single-process enforcement logic."""

import errno
import fcntl
import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import psutil
import pytest
from tests.daemon_like_process import daemon_like_process

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon import server
from claude_code_hooks_daemon.daemon.enforcement import enforce_single_daemon
from claude_code_hooks_daemon.daemon.paths import PID_MAX_LIMIT
from claude_code_hooks_daemon.utils.safe_signal import DaemonStop, RefusedSignalTarget

_STOP = "claude_code_hooks_daemon.daemon.enforcement.stop_verified_daemon"
_SERVES = "claude_code_hooks_daemon.daemon.enforcement._serves_a_socket"
_BOUND_SOCKETS = "claude_code_hooks_daemon.daemon.enforcement.bound_socket_paths"
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
            patch(_SERVES, return_value=True),
            patch(_STOP, return_value=DaemonStop.TERMINATED) as mock_stop,
        ):
            enforce_single_daemon(
                config=mock_config, pid_path=Path("/tmp/test.pid"), project_root=_PROJECT_ROOT
            )

        # Each peer is re-proven against THIS project root before it is signalled.
        assert mock_stop.call_args_list == [
            call(
                pid,
                project_root=_PROJECT_ROOT,
                grace_seconds=Timeout.PROCESS_KILL_WAIT,
                logical_root=None,
            )
            for pid in (other_pid_1, other_pid_2)
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

        mock_find.assert_called_once_with(project_root=_PROJECT_ROOT, logical_root=None)

    def test_the_callers_logical_root_finds_and_proves_a_peer(self) -> None:
        """Review 10, R10-2: a daemon an older version started through a
        link names the link, so the scan and the stop's proof both take the
        caller's spelling of its root."""
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True
        peer = 2**22 + 7

        with (
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                return_value=True,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                return_value=[peer],
            ) as mock_find,
            patch(_SERVES, return_value=True),
            patch(_STOP, return_value=DaemonStop.TERMINATED) as mock_stop,
        ):
            enforce_single_daemon(
                config=mock_config,
                pid_path=Path("/tmp/test.pid"),
                project_root=_PROJECT_ROOT,
                logical_root="/link/to/workspace",
            )

        mock_find.assert_called_once_with(
            project_root=_PROJECT_ROOT, logical_root="/link/to/workspace"
        )
        mock_stop.assert_called_once_with(
            peer,
            project_root=_PROJECT_ROOT,
            grace_seconds=Timeout.PROCESS_KILL_WAIT,
            logical_root="/link/to/workspace",
        )

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
            patch(_SERVES, return_value=True),
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

    def test_an_unreadable_file_stays_and_is_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An error reading the file is no proof it names no process."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_bytes(b"\xff\xfe")
        with caplog.at_level(logging.WARNING, logger="claude_code_hooks_daemon.daemon.enforcement"):
            self._enforce(pid_path, tmp_path / "daemon.sock")

        assert pid_path.read_bytes() == b"\xff\xfe"
        assert any(
            "Cannot read PID file" in record.getMessage() and str(pid_path) in record.getMessage()
            for record in caplog.records
        )

    def test_no_file_is_nothing_to_remove(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="claude_code_hooks_daemon.daemon.enforcement"):
            self._enforce(tmp_path / "daemon.pid", tmp_path / "daemon.sock")

        assert not (tmp_path / "daemon.pid").exists()
        assert not caplog.records


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
            patch(_SERVES, return_value=True),
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

    def test_a_peer_that_cannot_be_pinned_logs_error_and_is_not_signalled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review 8, R8-4: a ``pidfd_open`` error outside the no-pidfd list
        escaped ``enforce_single_daemon`` and aborted ``cmd_start``. Only the
        pin fails here; the stop and the peer are real."""

        def failing(pid: int, flags: int = 0) -> int:
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))

        monkeypatch.setattr(os, "pidfd_open", failing)
        mock_config = MagicMock()
        mock_config.daemon.enforce_single_daemon_process = True
        with (
            tempfile.TemporaryDirectory(prefix="hd-enf-") as short,
            daemon_like_process(tmp_path, binds=Path(short) / "s") as peer,
        ):
            with (
                patch(
                    "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
                    return_value=True,
                ),
                patch(
                    "claude_code_hooks_daemon.daemon.enforcement.find_all_daemon_processes",
                    return_value=[peer],
                ),
                patch("claude_code_hooks_daemon.daemon.enforcement.logger") as mock_logger,
            ):
                enforce_single_daemon(
                    config=mock_config, pid_path=tmp_path / "daemon.pid", project_root=tmp_path
                )

            assert psutil.Process(peer).status() != psutil.STATUS_ZOMBIE
        mock_logger.error.assert_called_once()
        assert os.strerror(errno.EINVAL) in str(mock_logger.error.call_args)


class TestOnlyADaemonThatServesIsStopped:
    """Ledger 00466 N232 (lifecycle round 9): a launcher's command line is
    its daemon's, since the daemon is its fork. Enforcement stopped a
    concurrent start's launcher waiting on the launch lock, and a daemon
    still starting. Only a process that has bound a socket serves; the rest
    are starts under way. The stop and the peers are real."""

    @staticmethod
    def _enforce(project_root: Path) -> None:
        config = MagicMock()
        config.daemon.enforce_single_daemon_process = True
        with patch(
            "claude_code_hooks_daemon.daemon.enforcement.is_container_environment",
            return_value=True,
        ):
            enforce_single_daemon(
                config=config, pid_path=project_root / "daemon.pid", project_root=project_root
            )

    def test_a_start_under_way_is_never_stopped(self, tmp_path: Path) -> None:
        with daemon_like_process(tmp_path) as launcher:
            self._enforce(tmp_path)

            assert psutil.Process(launcher).status() != psutil.STATUS_ZOMBIE

    def test_a_daemon_that_serves_is_stopped(self, tmp_path: Path) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="hd-enf-") as short,
            daemon_like_process(tmp_path, binds=Path(short) / "s") as serving,
        ):
            self._enforce(tmp_path)

            assert not psutil.pid_exists(serving) or (
                psutil.Process(serving).status() == psutil.STATUS_ZOMBIE
            )

    def test_a_daemon_whose_socket_path_holds_whitespace_is_stopped(self, tmp_path: Path) -> None:
        """Review 10, R10-1: psutil read such a path as no path, so the
        daemon was spared as a start under way."""
        with (
            tempfile.TemporaryDirectory(prefix="hd-enf-") as short,
            daemon_like_process(tmp_path, binds=Path(short) / "s p") as serving,
        ):
            self._enforce(tmp_path)

            assert not psutil.pid_exists(serving) or (
                psutil.Process(serving).status() == psutil.STATUS_ZOMBIE
            )

    def test_a_process_whose_sockets_cannot_be_read_is_not_stopped(self, tmp_path: Path) -> None:
        """Nor is one in another network namespace whose table cannot be
        read: it is not proven to serve, so it is spared."""
        with (
            tempfile.TemporaryDirectory(prefix="hd-enf-") as short,
            daemon_like_process(tmp_path, binds=Path(short) / "s") as serving,
            patch(_BOUND_SOCKETS, side_effect=PermissionError("denied")),
        ):
            self._enforce(tmp_path)

            assert psutil.Process(serving).status() != psutil.STATUS_ZOMBIE
