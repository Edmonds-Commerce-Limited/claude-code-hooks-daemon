"""Tests for CLI command implementations.

Focused tests covering critical CLI paths including:
- get_project_path and validation
- send_daemon_request
- cmd_status, cmd_stop
- cmd_config, cmd_init_config
- Error handling paths
"""

import argparse
import errno
import fcntl
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import psutil
import pytest
from tests.daemon_like_process import answering_daemon_socket, silent_socket

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon import paths, server
from claude_code_hooks_daemon.daemon.cli import (
    _await_started_daemon,
    cmd_config,
    cmd_init_config,
    cmd_status,
    cmd_stop,
    get_project_path,
    pid_is_this_projects_daemon,
    remove_stale_pid_file,
    send_daemon_request,
)
from claude_code_hooks_daemon.daemon.process_verification import RootProof
from claude_code_hooks_daemon.utils import safe_signal
from claude_code_hooks_daemon.utils.safe_signal import DaemonStop


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: Any) -> None:
    """Mock git repository checks for tests running in tmp directories."""

    def mock_get_git_repo_name(project_root: Path) -> str:
        return "test-repo"

    def mock_get_git_toplevel(project_root: Path) -> Path:
        return project_root

    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_repo_name",
        mock_get_git_repo_name,
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_toplevel",
        mock_get_git_toplevel,
    )


@pytest.fixture(autouse=True)
def reset_project_context() -> None:
    """Reset ProjectContext singleton between tests."""
    ProjectContext._initialized = False


#: Above Linux's default pid_max, so no process can have it: a PID file or
#: probe naming it can never reach a live process (Plan 00466 N59).
_UNREAL_PID = 2**22 + 7

#: The module whose names ``cmd_stop`` calls, for ``patch``.
_CLI = "claude_code_hooks_daemon.daemon.cli"


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """AF_UNIX paths are capped near 108 bytes; ``tmp_path`` nests deeper."""
    directory = Path(tempfile.mkdtemp(prefix="hd-stop-"))
    yield directory
    shutil.rmtree(directory)


class TestGetProjectPath:
    """Tests for get_project_path function."""

    def test_with_override_path_valid(self, tmp_path: Path) -> None:
        """get_project_path accepts valid override path."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        result = get_project_path(tmp_path)
        assert result == tmp_path

    def test_with_override_path_no_claude_dir(self, tmp_path: Path) -> None:
        """get_project_path fails if override path has no .claude directory."""
        with pytest.raises(SystemExit) as exc_info:
            get_project_path(tmp_path)
        assert exc_info.value.code == 1

    def test_finds_claude_in_current_dir(self, tmp_path: Path, monkeypatch: Any) -> None:
        """get_project_path finds .claude in current directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        monkeypatch.chdir(tmp_path)
        result = get_project_path()
        assert result == tmp_path

    def test_walks_up_tree_to_find_claude(self, tmp_path: Path, monkeypatch: Any) -> None:
        """get_project_path walks up directory tree to find .claude."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        # Create nested subdirectories
        subdir = tmp_path / "deep" / "nested" / "path"
        subdir.mkdir(parents=True)

        monkeypatch.chdir(subdir)
        result = get_project_path()
        assert result == tmp_path

    def test_fails_if_no_claude_found(self, tmp_path: Path, monkeypatch: Any) -> None:
        """get_project_path fails if no .claude directory found in tree."""
        subdir = tmp_path / "no" / "claude" / "here"
        subdir.mkdir(parents=True)

        monkeypatch.chdir(subdir)
        with pytest.raises(SystemExit) as exc_info:
            get_project_path()
        assert exc_info.value.code == 1

    def test_continues_search_when_validation_fails(self, tmp_path: Path, monkeypatch: Any) -> None:
        """get_project_path continues searching upward when validation fails.

        This tests the case where the first .claude directory found has an invalid
        installation (e.g., nested installation), so it continues searching for
        a valid installation higher in the tree.
        """
        # Create a valid installation in parent
        parent_claude = tmp_path / ".claude"
        parent_claude.mkdir()
        parent_hooks = parent_claude / "hooks-daemon"
        parent_hooks.mkdir()
        (parent_claude / "hooks-daemon.yaml").write_text(
            "version: '1.0'\ndaemon:\n  log_level: INFO\n"
        )

        # Create a nested/invalid installation in subdir
        subdir = tmp_path / "child"
        subdir.mkdir()
        child_claude = subdir / ".claude"
        child_claude.mkdir()
        # This .claude directory has no hooks-daemon and is invalid
        # Validation will fail and search should continue upward

        monkeypatch.chdir(subdir)
        result = get_project_path()
        # Should find the valid parent installation, not the invalid child
        assert result == tmp_path

    @staticmethod
    def _enclosing_install_with_nested_config(tmp_path: Path, child_config: str) -> Path:
        """A valid enclosing install, and a nested project carrying its own config."""
        parent_claude = tmp_path / ".claude"
        (parent_claude / "hooks-daemon").mkdir(parents=True)
        (parent_claude / "hooks-daemon.yaml").write_text(
            "version: '1.0'\ndaemon:\n  log_level: INFO\n"
        )
        child = tmp_path / "nested"
        (child / ".claude" / "hooks-daemon").mkdir(parents=True)
        (child / ".claude" / "hooks-daemon.yaml").write_text(child_config)
        return child

    def test_invalid_config_is_reported_not_replaced_by_the_enclosing_project(
        self, tmp_path: Path, monkeypatch: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A project's own broken config never falls through to an enclosing one.

        Plan 00466 N24 review 2 P2: the nested project's config failed the
        schema, so the search walked on upward and the daemon ran on the
        ENCLOSING repository's config, reporting that file's unrelated error.
        """
        child = self._enclosing_install_with_nested_config(
            tmp_path, "version: '1.0'\ndaemon:\n  log_level: NOT_A_LEVEL\n"
        )
        monkeypatch.chdir(child)

        with pytest.raises(SystemExit) as exc_info:
            get_project_path()

        assert exc_info.value.code == 1
        assert str(child / ".claude" / "hooks-daemon.yaml") in capsys.readouterr().err

    def test_unparseable_config_is_reported_not_replaced_by_the_enclosing_project(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A config that does not parse stops the search at its own project too."""
        child = self._enclosing_install_with_nested_config(tmp_path, "daemon: [unclosed\n")
        monkeypatch.chdir(child / ".claude")

        with pytest.raises(SystemExit) as exc_info:
            get_project_path()

        assert exc_info.value.code == 1

    def test_valid_nested_config_is_its_own_project(self, tmp_path: Path, monkeypatch: Any) -> None:
        """The nearest config wins when it is valid, as before."""
        child = self._enclosing_install_with_nested_config(
            tmp_path, "version: '1.0'\ndaemon:\n  log_level: INFO\n"
        )
        monkeypatch.chdir(child)

        assert get_project_path() == child


class TestSendDaemonRequest:
    """Tests for send_daemon_request function."""

    def test_successful_request(self, tmp_path: Path) -> None:
        """send_daemon_request successfully sends request and receives response."""
        socket_path = tmp_path / "test.sock"

        # Mock socket communication
        mock_sock = Mock()
        response_data = {"status": "ok", "result": {"test": "data"}}
        mock_sock.recv.side_effect = [json.dumps(response_data).encode("utf-8"), b""]

        with patch("socket.socket") as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            request = {"event": "test", "data": "test_data"}
            result = send_daemon_request(socket_path, request, timeout=Timeout.SOCKET_CONNECT)

            assert result == response_data
            mock_sock.connect.assert_called_once_with(str(socket_path))
            mock_sock.sendall.assert_called_once()
            mock_sock.shutdown.assert_called_once_with(socket.SHUT_WR)
            mock_sock.close.assert_called_once()

    def test_connection_failure(self, tmp_path: Path) -> None:
        """send_daemon_request returns None on connection failure."""
        socket_path = tmp_path / "nonexistent.sock"

        with patch("socket.socket") as mock_socket_class:
            mock_sock = Mock()
            mock_sock.connect.side_effect = ConnectionRefusedError("Connection refused")
            mock_socket_class.return_value = mock_sock

            request = {"event": "test"}
            result = send_daemon_request(socket_path, request)

            assert result is None

    def test_json_decode_failure(self, tmp_path: Path) -> None:
        """send_daemon_request handles invalid JSON response."""
        socket_path = tmp_path / "test.sock"

        mock_sock = Mock()
        mock_sock.recv.side_effect = [b"invalid json{", b""]

        with patch("socket.socket") as mock_socket_class:
            mock_socket_class.return_value = mock_sock

            request = {"event": "test"}
            result = send_daemon_request(socket_path, request)

            assert result is None

    def test_socket_timeout(self, tmp_path: Path) -> None:
        """send_daemon_request handles socket timeout."""
        socket_path = tmp_path / "test.sock"

        with patch("socket.socket") as mock_socket_class:
            mock_sock = Mock()
            mock_sock.connect.side_effect = TimeoutError("Connection timeout")
            mock_socket_class.return_value = mock_sock

            request = {"event": "test"}
            result = send_daemon_request(socket_path, request, timeout=Timeout.SOCKET_CONNECT)

            assert result is None


class TestCmdStatus:
    """Tests for cmd_status command."""

    def test_daemon_not_running(self, tmp_path: Path) -> None:
        """cmd_status returns 1 when daemon not running."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path)

        with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None):
            result = cmd_status(args)
            assert result == 1

    def test_daemon_running_with_socket(self, tmp_path: Path) -> None:
        """cmd_status returns 0 when daemon running with socket."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()
        untracked_dir = hooks_daemon_dir / "untracked" / "venv"
        untracked_dir.mkdir(parents=True)

        # Create socket file
        socket_path = untracked_dir / "socket"
        socket_path.touch()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
        ):
            result = cmd_status(args)
            assert result == 0

    def test_daemon_running_without_socket(self, tmp_path: Path) -> None:
        """cmd_status returns 1 when daemon running but socket missing."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        socket_path = tmp_path / "nonexistent" / "socket"

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=socket_path),
        ):
            result = cmd_status(args)
            assert result == 1


class TestCmdStop:
    """Tests for cmd_stop command."""

    def test_daemon_not_running(self, tmp_path: Path) -> None:
        """cmd_stop returns 0 when daemon not running."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path)

        with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None):
            result = cmd_stop(args)
            assert result == 0


def _stop_project(tmp_path: Path) -> argparse.Namespace:
    """A project root with a valid config, and ``cmd_stop``'s arguments for it."""
    claude_dir = tmp_path / ".claude"
    (claude_dir / "hooks-daemon").mkdir(parents=True)
    (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")
    return argparse.Namespace(project_root=tmp_path)


_SLEEP = "import time; time.sleep(600)"
_IGNORE_TERM = (
    "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "print('ready', flush=True); time.sleep(600)"
)


@pytest.fixture
def children() -> Iterator[list[subprocess.Popen[bytes]]]:
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for child in started:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=Timeout.PROCESS_SAMPLE)


def _spawn(
    children: list[subprocess.Popen[bytes]], code: str, *argv: str
) -> subprocess.Popen[bytes]:
    child = subprocess.Popen(
        [sys.executable, "-c", code, *argv], stdout=subprocess.PIPE, start_new_session=True
    )
    children.append(child)
    if code == _IGNORE_TERM:
        assert child.stdout is not None
        assert child.stdout.readline() == b"ready\n"
    return child


def _daemon_for(
    children: list[subprocess.Popen[bytes]], root: Path, code: str = _SLEEP
) -> subprocess.Popen[bytes]:
    """A real process whose command line is a daemon server for ``root``."""
    return _spawn(
        children, code, "claude_code_hooks_daemon.daemon.cli", "--project-root", str(root), "start"
    )


class TestCmdStopSignalsOnlyThisProjectsDaemon:
    """Plan 00466 N59: the PID file names a pid, and nothing but its command line proves it."""

    def test_stops_this_projects_daemon(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        args = _stop_project(tmp_path)
        daemon = _daemon_for(children, tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=daemon.pid),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_pid_file") as mock_cleanup_pid,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup_sock,
        ):
            assert cmd_stop(args) == 0
        assert not psutil.pid_exists(daemon.pid) or daemon.poll() is not None
        mock_cleanup_pid.assert_called_once()
        mock_cleanup_sock.assert_called_once()

    def test_refuses_another_projects_daemon(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        args = _stop_project(tmp_path / "mine")
        other = _daemon_for(children, tmp_path / "theirs")
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=other.pid),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_pid_file") as mock_cleanup_pid,
        ):
            assert cmd_stop(args) == 1
        assert other.poll() is None
        mock_cleanup_pid.assert_not_called()

    def test_refuses_a_live_process_that_is_not_a_daemon(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        args = _stop_project(tmp_path)
        bystander = _spawn(children, _SLEEP)
        with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=bystander.pid):
            assert cmd_stop(args) == 1
        assert bystander.poll() is None

    def test_refuses_a_mock_pid(self, tmp_path: Path) -> None:
        args = _stop_project(tmp_path)
        with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=Mock().pid):
            assert cmd_stop(args) == 1

    def test_a_daemon_gone_before_it_is_proven_keeps_its_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Plan 00466 N70: ``read_pid_file`` saw the pid live a moment ago, so
        the PID file and socket may already be a successor's; both are left.
        A merely stale PID file never reaches here: ``read_pid_file`` clears it."""
        args = _stop_project(tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=_UNREAL_PID),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_pid_file") as mock_cleanup_pid,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup_sock,
        ):
            assert cmd_stop(args) == 0
        mock_cleanup_pid.assert_not_called()
        mock_cleanup_sock.assert_not_called()
        assert "exited before it could be stopped" in capsys.readouterr().out

    def test_a_proven_daemon_that_exits_before_sigterm_keeps_its_files(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        """Plan 00466 N70: the proven daemon dies between the proof and
        SIGTERM. The proof attributed a live process to this project a moment
        ago, so the PID file and socket may already be a successor's."""
        args = _stop_project(tmp_path)
        daemon = _daemon_for(children, tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=daemon.pid),
            patch.object(psutil.Process, "terminate", side_effect=psutil.NoSuchProcess(daemon.pid)),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_pid_file") as mock_cleanup_pid,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup_sock,
        ):
            assert cmd_stop(args) == 0
        mock_cleanup_pid.assert_not_called()
        mock_cleanup_sock.assert_not_called()

    def test_a_daemon_that_ignores_sigterm_is_escalated_to_sigkill(
        self,
        tmp_path: Path,
        children: list[subprocess.Popen[bytes]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A process that survives SIGTERM's grace period gets SIGKILL'd
        (Plan 00466 N40 review 2 MA2).

        A wedged daemon that ignores SIGTERM (e.g. holding the GIL in a
        long-running C call) previously left ``stop``/``restart`` unable to
        recover it at all -- exactly the state MA2's GIL-holding-handler
        finding leaves the process in, and exactly the case ``init.sh``'s own
        advice ("this is fixed by restarting it") assumes works. The identity
        proof is re-checked by the SAME ``psutil.Process`` handle before the
        SIGKILL goes out (it pins the pid's start time), so a pid recycled
        during the grace cannot receive it -- no separate re-proof needed.
        """
        args = _stop_project(tmp_path)
        daemon = _daemon_for(children, tmp_path, _IGNORE_TERM)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=daemon.pid),
            patch.object(Timeout, "SOCKET_CONNECT", 0.2),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_pid_file") as mock_cleanup_pid,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup_sock,
        ):
            assert cmd_stop(args) == 0
        # psutil's own wait() (inside stop_verified_daemon) reaps the child via
        # waitpid before this test's subprocess.Popen handle can, so a strict
        # exit-code assertion here would race against psutil for the reap
        # (the existing pattern in test_stops_this_projects_daemon above) --
        # only that it is gone, or reports non-None, is available to check.
        assert not psutil.pid_exists(daemon.pid) or daemon.poll() is not None
        mock_cleanup_pid.assert_called_once()
        mock_cleanup_sock.assert_called_once()
        assert "escalated to SIGKILL" in capsys.readouterr().err

    def test_permission_denied(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        args = _stop_project(tmp_path)
        daemon = _daemon_for(children, tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=daemon.pid),
            patch.object(psutil.Process, "terminate", side_effect=psutil.AccessDenied(daemon.pid)),
        ):
            assert cmd_stop(args) == 1
        assert daemon.poll() is None


class TestCmdStopGenericException:
    """Tests for cmd_stop's generic exception path."""

    def test_stop_generic_exception(self, tmp_path: Path) -> None:
        """cmd_stop returns 1 on unexpected exception."""
        args = _stop_project(tmp_path)
        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=_UNREAL_PID),
            patch(
                "claude_code_hooks_daemon.daemon.cli.stop_verified_daemon",
                side_effect=RuntimeError("unexpected"),
            ),
        ):
            assert cmd_stop(args) == 1


class TestCmdStopCleansUpOnlyWhatItStillOwns:
    """Plan 00466 round 2 (S2): after the proven daemon exits, ``cmd_stop``
    deleted the PID file and socket unconditionally. A successor started in
    the meantime (a concurrent hook's ``ensure_daemon``) had written its own
    pid and bound its own socket there, and was orphaned. The PID file goes
    only while it still holds the stopped pid, and the socket only when a
    probe finds nothing listening on it."""

    daemon: subprocess.Popen[bytes]

    @pytest.fixture(autouse=True)
    def _daemon(self, tmp_path: Path, children: list[subprocess.Popen[bytes]]) -> None:
        """A real process this project's stop proves is its daemon."""
        self.daemon = _daemon_for(children, tmp_path)

    def _stop(self, tmp_path: Path, pid_path: Path, socket_path: Path, on_exit: Any) -> int:
        """Run ``cmd_stop`` against the real daemon; ``on_exit`` runs once
        ``stop_verified_daemon`` has seen it exit, which is where a
        successor's start lands."""
        claude_dir = tmp_path / ".claude"
        (claude_dir / "hooks-daemon").mkdir(parents=True)
        (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\n")
        args = argparse.Namespace(
            project_root=tmp_path, pid_file=str(pid_path), socket=str(socket_path)
        )

        def stop_then_succeed(pid: object, **kwargs: Any) -> DaemonStop:
            outcome = safe_signal.stop_verified_daemon(pid, **kwargs)
            on_exit()
            return outcome

        with (
            patch(f"{_CLI}.read_pid_file", return_value=self.daemon.pid),
            patch(f"{_CLI}.stop_verified_daemon", side_effect=stop_then_succeed),
        ):
            result = cmd_stop(args)
        assert self.daemon.poll() is not None or not psutil.pid_exists(self.daemon.pid)
        return result

    def test_the_stopped_daemons_files_are_removed(self, tmp_path: Path, short_dir: Path) -> None:
        pid_path, socket_path = self._stale_files(short_dir)

        assert self._stop(tmp_path, pid_path, socket_path, lambda: None) == 0

        assert not pid_path.exists()
        assert not socket_path.exists()

    def test_a_successors_pid_file_and_live_socket_are_left_alone(
        self, tmp_path: Path, short_dir: Path
    ) -> None:
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(str(self.daemon.pid))
        socket_path = short_dir / "daemon.sock"
        successor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        def successor_starts() -> None:
            if not socket_path.exists():
                pid_path.write_text(str(os.getpid()))
                successor.bind(str(socket_path))
                successor.listen(1)

        try:
            assert self._stop(tmp_path, pid_path, socket_path, successor_starts) == 0
            assert pid_path.read_text() == str(os.getpid())
            assert socket_path.exists()
        finally:
            successor.close()

    def _stale_files(self, short_dir: Path) -> tuple[Path, Path]:
        """The daemon's PID file and a bound, never-listening socket: what
        it leaves once stopped."""
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(str(self.daemon.pid))
        socket_path = short_dir / "daemon.sock"
        orphan = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        orphan.bind(str(socket_path))
        orphan.close()
        return pid_path, socket_path

    @staticmethod
    def _start_lock(socket_path: Path) -> int:
        """An fd open on the start lock a daemon start takes (``server.py``)."""
        return os.open(str(socket_path) + ".start.lock", os.O_RDWR | os.O_CREAT, 0o600)

    def test_the_probe_and_both_removals_hold_the_start_lock(
        self, tmp_path: Path, short_dir: Path
    ) -> None:
        """Plan 00466 round 3 (m-B): a starting daemon holds the start lock
        across its own probe, unlink and bind. A stop probing between that
        unlink and bind found no socket, then removed the one just bound."""
        pid_path, socket_path = self._stale_files(short_dir)
        seen: dict[str, bool] = {}

        def lock_is_held() -> bool:
            fd = self._start_lock(socket_path)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            finally:
                os.close(fd)
            return False

        def recording(name: str, real: Any) -> Any:
            def record(*args: Any) -> Any:
                seen[name] = lock_is_held()
                return real(*args)

            return record

        with (
            patch(f"{_CLI}.cleanup_pid_file", recording("pid", paths.cleanup_pid_file)),
            patch(
                f"{_CLI}._socket_liveness_sync", recording("probe", server._socket_liveness_sync)
            ),
            patch(f"{_CLI}.cleanup_socket", recording("socket", paths.cleanup_socket)),
        ):
            assert self._stop(tmp_path, pid_path, socket_path, lambda: None) == 0

        assert seen == {"pid": True, "probe": True, "socket": True}
        assert not pid_path.exists()
        assert not socket_path.exists()

    def test_a_start_that_keeps_the_lock_keeps_both_files(
        self, tmp_path: Path, short_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whatever a start holding the lock is doing to these paths, it is
        not provably done, so a stop that cannot take the lock removes
        neither file."""
        pid_path, socket_path = self._stale_files(short_dir)
        monkeypatch.setattr(Timeout, "FILE_LOCK", 0)
        holder = self._start_lock(socket_path)
        fcntl.flock(holder, fcntl.LOCK_EX)
        try:
            assert self._stop(tmp_path, pid_path, socket_path, lambda: None) == 0
        finally:
            os.close(holder)
        assert pid_path.exists()
        assert socket_path.exists()

    def test_a_start_lock_that_cannot_be_opened_keeps_both_files(
        self, tmp_path: Path, short_dir: Path
    ) -> None:
        """Plan 00466 round 4 (Sh-C): a symlink planted at the lock path is
        refused, and without the lock the stop removes neither file."""
        pid_path, socket_path = self._stale_files(short_dir)
        target = short_dir / "planted-target"
        Path(str(socket_path) + ".start.lock").symlink_to(target)
        assert self._stop(tmp_path, pid_path, socket_path, lambda: None) == 0
        assert pid_path.exists()
        assert socket_path.exists()
        assert not target.exists()


class TestTheStartLockRefusesWhatIsNotItsOwnFile:
    """Plan 00466 round 4 (Sh-C): ``O_CREAT`` through a link planted at the
    lock path created or opened the file it named."""

    def test_a_symlink_is_refused_and_its_target_never_created(self, short_dir: Path) -> None:
        socket_path = short_dir / "daemon.sock"
        target = short_dir / "target"
        server.start_lock_path(socket_path).symlink_to(target)
        with (
            pytest.raises(OSError) as raised,
            server.hold_start_lock(socket_path, Timeout.FILE_LOCK),
        ):
            pytest.fail("the lock was taken through a symlink")
        assert raised.value.errno == errno.ELOOP
        assert not target.exists()

    def test_a_lock_that_is_not_a_regular_file_is_refused(self, short_dir: Path) -> None:
        socket_path = short_dir / "daemon.sock"
        os.mkfifo(server.start_lock_path(socket_path))
        with (
            pytest.raises(OSError) as raised,
            server.hold_start_lock(socket_path, Timeout.FILE_LOCK),
        ):
            pytest.fail("the lock was taken on a FIFO")
        assert raised.value.errno == errno.EINVAL

    def test_a_regular_lock_file_is_taken(self, short_dir: Path) -> None:
        socket_path = short_dir / "daemon.sock"
        with server.hold_start_lock(socket_path, Timeout.FILE_LOCK):
            assert server.start_lock_path(socket_path).is_file()

    def test_only_its_owner_may_open_the_lock(self, short_dir: Path) -> None:
        """Round 5 (Sh-E): a lock another user can open is one another user
        can hold, and every start would wait on them."""
        socket_path = short_dir / "daemon.sock"
        with server.hold_start_lock(socket_path, Timeout.FILE_LOCK):
            mode = server.start_lock_path(socket_path).stat().st_mode
        assert mode & 0o077 == 0

    def test_another_users_lock_is_refused_by_name(self, short_dir: Path) -> None:
        """Root opens anything, so the EACCES a second user gets is the
        probe's. The refusal names both users, and nothing is removed."""
        socket_path = short_dir / "daemon.sock"
        lock_path = server.start_lock_path(socket_path)
        lock_path.touch()
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(str(_UNREAL_PID))
        real_open = os.open

        def refuse_the_lock(path: str, *args: Any, **kwargs: Any) -> int:
            if path == str(lock_path):
                raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
            return real_open(path, *args, **kwargs)

        with patch("os.open", side_effect=refuse_the_lock):
            with (
                pytest.raises(PermissionError) as raised,
                server.hold_start_lock(socket_path, Timeout.FILE_LOCK),
            ):
                pytest.fail("the lock was taken")
            assert not remove_stale_pid_file(pid_path, socket_path, str(_UNREAL_PID))
        message = str(raised.value)
        assert f"uid {lock_path.stat().st_uid}" in message
        assert f"uid {os.geteuid()} cannot open it" in message
        assert pid_path.exists()


class TestRemoveStalePidFile:
    """Plan 00466 round 4 (Sh-A, Sh-B): ``init.sh`` removes a stale or
    corrupt PID file through this, under the start lock a daemon start
    writes its pid under."""

    @pytest.mark.parametrize("text", [str(_UNREAL_PID), "0", "-1", "1", "", "junk"])
    def test_a_file_naming_no_live_process_is_removed(self, short_dir: Path, text: str) -> None:
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(text)
        assert remove_stale_pid_file(pid_path, short_dir / "daemon.sock", text)
        assert not pid_path.exists()

    def test_a_file_that_changed_since_it_was_read_stays(self, short_dir: Path) -> None:
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(str(os.getpid()))
        assert not remove_stale_pid_file(pid_path, short_dir / "daemon.sock", str(_UNREAL_PID))
        assert pid_path.read_text() == str(os.getpid())

    def test_a_file_whose_pid_is_alive_stays(self, short_dir: Path) -> None:
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(str(os.getpid()))
        assert not remove_stale_pid_file(pid_path, short_dir / "daemon.sock", str(os.getpid()))
        assert pid_path.exists()

    def test_it_holds_the_start_lock_while_it_removes(self, short_dir: Path) -> None:
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(str(_UNREAL_PID))
        socket_path = short_dir / "daemon.sock"
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
            assert remove_stale_pid_file(pid_path, socket_path, str(_UNREAL_PID))
        assert held == [True]

    def test_a_held_lock_leaves_the_file(
        self, short_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(str(_UNREAL_PID))
        socket_path = short_dir / "daemon.sock"
        monkeypatch.setattr(Timeout, "FILE_LOCK", 0)
        with server.hold_start_lock(socket_path, Timeout.FILE_LOCK):
            assert not remove_stale_pid_file(pid_path, socket_path, str(_UNREAL_PID))
        assert pid_path.exists()

    def test_a_lock_that_cannot_be_opened_leaves_the_file(self, short_dir: Path) -> None:
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(str(_UNREAL_PID))
        socket_path = short_dir / "daemon.sock"
        server.start_lock_path(socket_path).symlink_to(short_dir / "target")
        assert not remove_stale_pid_file(pid_path, socket_path, str(_UNREAL_PID))
        assert pid_path.exists()


class TestPidIsThisProjectsDaemon:
    """Plan 00466 round 4 (N139-A): EPERM proves a process, not this daemon."""

    def test_a_socket_answering_as_this_projects_daemon_proves_it(self, short_dir: Path) -> None:
        socket_path = short_dir / "daemon.sock"
        with answering_daemon_socket(socket_path, short_dir, _UNREAL_PID):
            assert pid_is_this_projects_daemon(_UNREAL_PID, socket_path, short_dir)

    def test_a_listener_that_does_not_answer_proves_nothing(self, short_dir: Path) -> None:
        """Round 6 (Sh-2): any listener accepted the probe, and under the /tmp
        socket fallback another user can bind the path first."""
        socket_path = short_dir / "daemon.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(socket_path))
            listener.listen(1)
            assert not pid_is_this_projects_daemon(_UNREAL_PID, socket_path, short_dir)

    def test_another_projects_daemon_answering_proves_nothing(
        self, short_dir: Path, tmp_path: Path
    ) -> None:
        socket_path = short_dir / "daemon.sock"
        with answering_daemon_socket(socket_path, tmp_path, _UNREAL_PID):
            assert not pid_is_this_projects_daemon(_UNREAL_PID, socket_path, short_dir)

    def test_a_command_line_serving_this_project_proves_a_pid_of_this_user(
        self, short_dir: Path
    ) -> None:
        """This test's own pid, whose owner is this user."""
        proof = RootProof(root=os.path.realpath(short_dir), refusal=None)
        with patch(f"{_CLI}.daemon_process_project_root", return_value=proof):
            assert pid_is_this_projects_daemon(os.getpid(), short_dir / "none.sock", short_dir)

    def test_a_command_line_never_proves_another_users_pid(self, short_dir: Path) -> None:
        """Round 6 (P5-1, Sh-G): the rule asked whether this user may signal
        the pid, and root may signal every process, so another user's process
        naming this project in its arguments was proven. The owner decides.
        Another uid's process is faked by changing the uid it is compared
        with, not by launching one, which would need root."""
        proof = RootProof(root=os.path.realpath(short_dir), refusal=None)
        with (
            patch(f"{_CLI}.daemon_process_project_root", return_value=proof),
            patch("os.geteuid", return_value=os.geteuid() + 4242),
        ):
            assert not pid_is_this_projects_daemon(os.getpid(), short_dir / "none.sock", short_dir)

    def test_a_gone_pid_is_not_proven_by_a_command_line(self, short_dir: Path) -> None:
        proof = RootProof(root=os.path.realpath(short_dir), refusal=None)
        with patch(f"{_CLI}.daemon_process_project_root", return_value=proof):
            assert not pid_is_this_projects_daemon(_UNREAL_PID, short_dir / "none.sock", short_dir)

    @pytest.mark.parametrize("pid", [0, 1, -1, True])
    def test_what_is_no_pid_is_never_probed(self, short_dir: Path, pid: int) -> None:
        """``kill(0, 0)`` succeeds against this process's own group."""
        with patch("os.kill") as kill:
            assert not pid_is_this_projects_daemon(pid, short_dir / "none.sock", short_dir)
        kill.assert_not_called()

    def test_another_projects_daemon_does_not(self, short_dir: Path, tmp_path: Path) -> None:
        proof = RootProof(root=os.path.realpath(tmp_path), refusal=None)
        with patch(f"{_CLI}.daemon_process_project_root", return_value=proof):
            assert not pid_is_this_projects_daemon(os.getpid(), short_dir / "none.sock", short_dir)

    def test_an_unprovable_process_does_not(self, short_dir: Path) -> None:
        assert not pid_is_this_projects_daemon(_UNREAL_PID, short_dir / "none.sock", short_dir)


class TestAwaitStartedDaemonIsBoundedByTheClock:
    """Round 6 (R5-1, P5-2): ``cmd_start``'s parent counted 50 ticks, and
    each tick's socket probe can take its whole timeout, so the poll could
    run six times its budget and take the PreToolUse deny path to the 60 s
    hook timeout. Nothing is stubbed: the PID file names a live process
    that is not a daemon (this test's own, read only), and the socket
    accepts every probe but never answers."""

    _BUDGET_SEC = 1.0

    def test_a_probe_that_takes_its_whole_timeout_cannot_stretch_the_poll(
        self, short_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Timeout, "DAEMON_PID_POLL_BUDGET_SEC", self._BUDGET_SEC, raising=False)
        pid_path = short_dir / "daemon.pid"
        pid_path.write_text(f"{os.getpid()}\n")
        socket_path = short_dir / "daemon.sock"
        with silent_socket(socket_path) as accepted:
            daemon_pid = _await_started_daemon(pid_path, socket_path, short_dir, None)
        assert daemon_pid is None
        # Each probe waits out its timeout, so a clock-bounded poll makes a
        # handful where a tick-counted one made one per tick.
        most = int(self._BUDGET_SEC / Timeout.SOCKET_LIVENESS_PROBE_SEC) + 1
        assert 1 <= len(accepted) <= most, len(accepted)


class TestCmdConfig:
    """Tests for cmd_config command."""

    def test_config_not_found(self, tmp_path: Path) -> None:
        """cmd_config returns 1 when config file not found."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        args = argparse.Namespace(project_root=tmp_path, json=False)

        result = cmd_config(args)
        assert result == 1

    def test_config_display_text(self, tmp_path: Path) -> None:
        """cmd_config displays config in text format."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("""version: '1.0'
daemon:
  log_level: INFO
  idle_timeout_seconds: 600
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
      priority: 10
""")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        result = cmd_config(args)
        assert result == 0

    def test_config_display_json(self, tmp_path: Path) -> None:
        """cmd_config displays config in JSON format."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("""version: '1.0'
daemon:
  log_level: INFO
""")

        args = argparse.Namespace(project_root=tmp_path, json=True)

        result = cmd_config(args)
        assert result == 0

    def test_config_load_error(self, tmp_path: Path) -> None:
        """cmd_config handles config load errors."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create invalid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("invalid: yaml: {{{}}")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        result = cmd_config(args)
        assert result == 1

    def test_config_load_exception_via_mock(self, tmp_path: Path) -> None:
        """cmd_config returns 1 when Config.load raises exception."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.Config.load",
            side_effect=ValueError("bad config"),
        ):
            result = cmd_config(args)
            assert result == 1

    def test_config_displays_plugins(self, tmp_path: Path, capsys: Any) -> None:
        """cmd_config displays plugin paths and plugins."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path, json=False)

        from unittest.mock import MagicMock

        mock_config = MagicMock()
        mock_config.version = "1.0"
        mock_config.daemon.idle_timeout_seconds = 600
        mock_config.daemon.log_level.value = "INFO"
        mock_config.daemon.log_buffer_size = 1000
        mock_config.daemon.request_timeout_seconds = 30
        mock_config.plugins.paths = ["/path/to/plugins"]
        mock_plugin = MagicMock()
        mock_plugin.path = "/path/to/plugin.py"
        mock_plugin.enabled = True
        mock_config.plugins.plugins = [mock_plugin]
        # Empty handler dicts
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
            setattr(mock_config.handlers, attr, {})

        with patch(
            "claude_code_hooks_daemon.daemon.cli.Config.load",
            return_value=mock_config,
        ):
            result = cmd_config(args)
            assert result == 0

        captured = capsys.readouterr()
        assert "[Plugins]" in captured.out
        assert "/path/to/plugins" in captured.out
        assert "/path/to/plugin.py" in captured.out


class TestCmdInitConfig:
    """Tests for cmd_init_config command."""

    def test_create_minimal_config(self, tmp_path: Path) -> None:
        """cmd_init_config creates minimal config."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        args = argparse.Namespace(project_root=tmp_path, minimal=True, force=False)

        result = cmd_init_config(args)
        assert result == 0

        config_file = claude_dir / "hooks-daemon.yaml"
        assert config_file.exists()
        content = config_file.read_text()
        assert "version:" in content

    def test_create_full_config(self, tmp_path: Path) -> None:
        """cmd_init_config creates full config."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        args = argparse.Namespace(project_root=tmp_path, minimal=False, force=False)

        result = cmd_init_config(args)
        assert result == 0

        config_file = claude_dir / "hooks-daemon.yaml"
        assert config_file.exists()

    def test_stdout_prints_template_without_writing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--stdout prints the template for review and writes nothing.

        LLM-INSTALL.md tells the reader to review every handler before enabling
        them, but init-config could only WRITE the config. So the doc reached
        past the CLI for a raw ``python -c`` import — the exact unrunnable shape
        Plan 00192 eliminated. The CLI has to be able to do this itself.
        """
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon").mkdir()

        args = argparse.Namespace(project_root=tmp_path, minimal=False, force=False, stdout=True)

        result = cmd_init_config(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "version:" in captured.out, "template must go to stdout"
        assert not (claude_dir / "hooks-daemon.yaml").exists(), "must not write the config file"

    def test_stdout_works_when_config_already_exists(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--stdout needs no --force: printing cannot destroy anything.

        Reviewing the available options is the common case on an EXISTING
        install, so requiring --force there would push the reader toward a
        destructive flag purely to read something.
        """
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon").mkdir()
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n# my customisations\n")

        args = argparse.Namespace(project_root=tmp_path, minimal=False, force=False, stdout=True)

        result = cmd_init_config(args)
        assert result == 0
        assert "# my customisations" in config_file.read_text(), "existing config untouched"

    def test_config_already_exists_no_force(self, tmp_path: Path) -> None:
        """cmd_init_config fails if config exists without --force."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create existing config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\n")

        args = argparse.Namespace(project_root=tmp_path, minimal=False, force=False)

        result = cmd_init_config(args)
        assert result == 1

    def test_config_overwrite_with_force(self, tmp_path: Path) -> None:
        """cmd_init_config overwrites config with --force."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create existing config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("old config\n")

        args = argparse.Namespace(project_root=tmp_path, minimal=False, force=True)

        result = cmd_init_config(args)
        assert result == 0

        # Verify new config was written
        content = config_file.read_text()
        assert "old config" not in content
        assert "version:" in content

    def test_write_failure(self, tmp_path: Path) -> None:
        """cmd_init_config returns 1 when config write fails."""
        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path",
            return_value=tmp_path,
        ):
            args = argparse.Namespace(project_root=tmp_path, minimal=True, force=False)

            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                result = cmd_init_config(args)
                assert result == 1

    def test_validation_fails_no_force(self, tmp_path: Path) -> None:
        """cmd_init_config returns 1 when validation fails without --force."""
        args = argparse.Namespace(project_root=tmp_path, minimal=True, force=False)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path",
            side_effect=SystemExit(1),
        ):
            result = cmd_init_config(args)
            assert result == 1

    def test_force_mode_with_project_root_arg(self, tmp_path: Path) -> None:
        """cmd_init_config with --force uses project_root from args when set."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        args = argparse.Namespace(project_root=tmp_path, minimal=True, force=True)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path",
            side_effect=SystemExit(1),
        ):
            result = cmd_init_config(args)
            assert result == 0
            assert (claude_dir / "hooks-daemon.yaml").exists()

    def test_force_mode_tree_walk(self, tmp_path: Path, monkeypatch: Any) -> None:
        """cmd_init_config with --force walks tree when validation fails."""
        # Create .claude dir somewhere up the tree
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        subdir = tmp_path / "sub"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        args = argparse.Namespace(project_root=None, minimal=True, force=True)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path",
            side_effect=SystemExit(1),
        ):
            result = cmd_init_config(args)
            assert result == 0
            assert (claude_dir / "hooks-daemon.yaml").exists()

    def test_force_mode_no_claude_dir_found(self, tmp_path: Path, monkeypatch: Any) -> None:
        """cmd_init_config with --force returns 1 when no .claude found."""
        subdir = tmp_path / "no_claude"
        subdir.mkdir()
        monkeypatch.chdir(subdir)

        args = argparse.Namespace(project_root=None, minimal=True, force=True)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.get_project_path",
            side_effect=SystemExit(1),
        ):
            result = cmd_init_config(args)
            assert result == 1

    def test_create_claude_dir_if_missing(self, tmp_path: Path) -> None:
        """cmd_init_config creates .claude directory if missing."""
        # Don't create .claude directory, but still needs hooks-daemon for validation
        # to pass in get_project_path
        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            args = argparse.Namespace(project_root=tmp_path, minimal=False, force=False)

            result = cmd_init_config(args)
            assert result == 0

            config_file = tmp_path / ".claude" / "hooks-daemon.yaml"
            assert config_file.exists()
