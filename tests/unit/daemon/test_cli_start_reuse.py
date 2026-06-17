"""Plan 00127: daemon lifecycle REUSE fix — cli.cmd_start layer.

cmd_start must REUSE a live, healthy same-root incumbent (Decision 1):
  - The already-running-AND-healthy check (PID alive AND socket live) runs FIRST,
    before enforce_single_daemon — so a healthy incumbent is never killed.
  - On reuse, cmd_start returns 0 without forking, without touching the socket,
    and without calling enforce_single_daemon.
  - A genuinely stale socket (no live PID, dead socket) is still cleaned up and
    the normal fork/start path proceeds.
"""

import argparse
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_start
from claude_code_hooks_daemon.daemon.server import DaemonAlreadyRunningError, _SocketLiveness


class TestCmdStartReuse:
    """Reuse path: a live, healthy same-root incumbent."""

    def test_reuses_live_healthy_daemon(self, tmp_path: Path) -> None:
        """Live PID + live socket => return 0, no fork, no enforcement, no cleanup."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=4242,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.LIVE,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon") as mock_enforce,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup,
            patch("os.fork") as mock_fork,
        ):
            result = cmd_start(args)

        assert result == 0
        mock_enforce.assert_not_called()
        mock_cleanup.assert_not_called()
        mock_fork.assert_not_called()

    def test_already_running_check_runs_before_enforcement(self, tmp_path: Path) -> None:
        """With a live incumbent, enforce_single_daemon must never be reached."""
        args = argparse.Namespace(project_root=tmp_path)

        def _fail_if_called(*a: object, **k: object) -> None:
            raise AssertionError("enforce_single_daemon must not run for live reuse")

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=4242,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.LIVE,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.enforce_single_daemon",
                side_effect=_fail_if_called,
            ),
        ):
            result = cmd_start(args)

        assert result == 0


class TestCmdStartStaleSocket:
    """Stale path: no live PID and a dead socket => clean up and proceed."""

    def test_cleans_stale_socket_and_proceeds_to_fork(self, tmp_path: Path) -> None:
        """read_pid_file None + socket not live => cleanup_socket then fork path."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                side_effect=[None, 42],  # not running, then daemon came up
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_stale_daemon_files", return_value=0),
            patch("claude_code_hooks_daemon.daemon.cli.write_cleanup_status"),
            patch("os.fork", return_value=100),  # parent branch
            patch("time.sleep"),
        ):
            result = cmd_start(args)

        assert result == 0
        mock_cleanup.assert_called_once()


class TestCmdStartContendedSocket:
    """Degenerate: live socket but no/foreign matching PID => fail fast."""

    def test_live_socket_without_matching_pid_fails_fast(self, tmp_path: Path) -> None:
        """No live PID but socket is live (foreign owner) => non-zero, no unlink."""
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.LIVE,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup,
            patch("os.fork") as mock_fork,
        ):
            result = cmd_start(args)

        assert result != 0
        mock_cleanup.assert_not_called()
        mock_fork.assert_not_called()


class TestCmdStartChildReuseExitZero:
    """Forked-child backstop: daemon.start() raising DaemonAlreadyRunningError
    is a benign REUSE => the child exits 0, not 1 (crash)."""

    def test_child_reuse_exits_zero(self, tmp_path: Path) -> None:
        """asyncio.run(daemon.start()) raising DaemonAlreadyRunningError => exit 0."""
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

        patchers = [
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cleanup_stale_daemon_files",
                return_value=0,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.write_cleanup_status"),
            patch("os.fork", side_effect=[0, 0]),  # both forks => child
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
            patch(
                "asyncio.run",
                side_effect=DaemonAlreadyRunningError("already running"),
            ),
        ]
        with ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            with pytest.raises(SystemExit) as exc_info:
                cmd_start(args)
            assert exc_info.value.code == 0

    def test_child_reuse_does_not_delete_incumbent_discovery_file(self, tmp_path: Path) -> None:
        """Plan 00127 Finding 2: a reuse-race loser (DaemonAlreadyRunningError)
        must NOT delete the SHARED socket-discovery file the live incumbent owns.

        Drives the in-loop child path. ``asyncio.run(daemon.start())`` raises
        DaemonAlreadyRunningError (a live incumbent won the race). The reuse
        branch must exit 0 WITHOUT calling ``cleanup_socket_discovery_file`` —
        on long-path setups init.sh relies on that file to locate the
        incumbent's socket, and the incumbent only writes it once at its own
        startup. The blanket ``finally`` cleanup that deleted it is the bug.
        """
        args = argparse.Namespace(project_root=tmp_path)

        sock_path = tmp_path / "daemon.sock"
        mock_config = MagicMock()
        mock_config.daemon.socket_path = str(sock_path)
        mock_config.daemon.pid_file_path = str(tmp_path / "daemon.pid")
        mock_config.daemon.get_socket_path.return_value = sock_path
        mock_config.daemon.get_pid_file_path.return_value = tmp_path / "daemon.pid"
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

        mock_devnull = MagicMock()
        mock_devnull.fileno.return_value = 99

        patchers = [
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cleanup_stale_daemon_files",
                return_value=0,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.write_cleanup_status"),
            patch("os.fork", side_effect=[0, 0]),  # both forks => child
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
                return_value=MagicMock(),
            ),
            patch(
                "claude_code_hooks_daemon.daemon.server.HooksDaemon",
                return_value=MagicMock(),
            ),
            # The discovery-file helpers are imported inside cmd_start from the
            # paths module — patch them there. write is a harmless no-op; cleanup
            # is the call that must NOT happen on the reuse branch.
            patch(
                "claude_code_hooks_daemon.daemon.paths.write_socket_discovery_file",
            ),
            patch(
                "asyncio.run",
                side_effect=DaemonAlreadyRunningError("already running"),
            ),
        ]
        with ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            mock_cleanup_discovery = stack.enter_context(
                patch("claude_code_hooks_daemon.daemon.paths.cleanup_socket_discovery_file")
            )
            with pytest.raises(SystemExit) as exc_info:
                cmd_start(args)
            assert exc_info.value.code == 0

            # The reuse-race loser must NOT delete the incumbent's discovery file.
            mock_cleanup_discovery.assert_not_called()

    def test_child_owner_cleans_up_discovery_file_on_normal_exit(self, tmp_path: Path) -> None:
        """When this process actually OWNED the daemon (start() returns normally),
        the discovery file IS cleaned up on the way out (no leak)."""
        args = argparse.Namespace(project_root=tmp_path)

        sock_path = tmp_path / "daemon.sock"
        mock_config = MagicMock()
        mock_config.daemon.socket_path = str(sock_path)
        mock_config.daemon.pid_file_path = str(tmp_path / "daemon.pid")
        mock_config.daemon.get_socket_path.return_value = sock_path
        mock_config.daemon.get_pid_file_path.return_value = tmp_path / "daemon.pid"
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

        mock_devnull = MagicMock()
        mock_devnull.fileno.return_value = 99

        patchers = [
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cleanup_stale_daemon_files",
                return_value=0,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.write_cleanup_status"),
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
                return_value=MagicMock(),
            ),
            patch(
                "claude_code_hooks_daemon.daemon.server.HooksDaemon",
                return_value=MagicMock(),
            ),
            patch("claude_code_hooks_daemon.daemon.paths.write_socket_discovery_file"),
            patch("asyncio.run", return_value=None),  # owned + clean shutdown
        ]
        with ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            mock_cleanup_discovery = stack.enter_context(
                patch("claude_code_hooks_daemon.daemon.paths.cleanup_socket_discovery_file")
            )
            with pytest.raises(SystemExit) as exc_info:
                cmd_start(args)
            assert exc_info.value.code == 0

            mock_cleanup_discovery.assert_called_once()


class TestCmdStartIndeterminateLiveness:
    """Re-review fix: INDETERMINATE liveness must never cause socket unlink."""

    def test_cmd_start_reuses_busy_but_live_incumbent(self, tmp_path: Path) -> None:
        """INDETERMINATE liveness + live PID => reuse (return 0), no unlink.

        Plan 00127 re-review fix: a busy-but-live daemon probes INDETERMINATE
        (its event loop is mid-dispatch so the probe times out). The parent must
        treat it as healthy and return 0 WITHOUT calling cleanup_socket,
        enforce_single_daemon, or os.fork — the incumbent's socket must never
        be unlinked.
        """
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=os.getpid(),  # a live PID (this process)
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.INDETERMINATE,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon") as mock_enforce,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup,
            patch("os.fork") as mock_fork,
        ):
            result = cmd_start(args)

        assert result == 0
        assert "already running" in str(result) or result == 0  # confirmed by return value
        mock_enforce.assert_not_called()
        mock_cleanup.assert_not_called()
        mock_fork.assert_not_called()

    def test_cmd_start_fails_fast_on_indeterminate_without_live_pid(self, tmp_path: Path) -> None:
        """INDETERMINATE liveness + no live PID => return 1, no socket unlink.

        Plan 00127 re-review fix: no PID file means we cannot confirm a live
        incumbent, but INDETERMINATE means we cannot confirm the socket is dead
        either. The safe choice is to fail fast (return 1) rather than unlink a
        possibly-live socket. cleanup_socket must NOT be called.
        """
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=None,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.INDETERMINATE,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup,
            patch("os.fork") as mock_fork,
        ):
            result = cmd_start(args)

        assert result == 1
        mock_cleanup.assert_not_called()
        mock_fork.assert_not_called()
