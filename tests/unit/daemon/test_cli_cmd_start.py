"""Tests for cmd_start daemon fork/daemonization logic.

Covers the complex fork-based daemonization in cmd_start (lines 207-311),
which requires careful mocking of os.fork, os.setsid, and related syscalls.
"""

import argparse
import contextlib
import io
import os
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.cli import cmd_start
from claude_code_hooks_daemon.daemon.paths import PID_MAX_LIMIT
from claude_code_hooks_daemon.daemon.process_verification import RootProof
from claude_code_hooks_daemon.daemon.server import (
    LaunchLock,
    StartUnderWay,
    _SocketLiveness,
    launch_lock_path,
    start_under_way,
)

# Parseable, yet above the largest pid pid_max allows, so it names no process.
_DEAD_PID = PID_MAX_LIMIT


@contextlib.contextmanager
def _proven_to_serve(project: Path, proven: bool = True) -> Iterator[None]:
    """The started daemon, a process of this user's, is (or is not) proven
    by its command line to serve ``project``."""
    proof = RootProof(
        root=os.path.realpath(project) if proven else None,
        refusal=None if proven else "not a daemon server",
    )
    with (
        patch(
            "claude_code_hooks_daemon.daemon.cli.daemon_process_project_root", return_value=proof
        ),
        patch("claude_code_hooks_daemon.daemon.cli.is_this_users_process", return_value=True),
    ):
        yield


def _poll_clock() -> Any:
    """``cli``'s clock, advanced only by its own sleeps, so the start poll's
    wall-clock budget (Plan 00466 round 6, R5-1) runs out in as many ticks
    as it takes seconds, at once."""
    now = [0.0]
    clock = MagicMock(wraps=time)
    clock.monotonic.side_effect = lambda: now[0]
    clock.sleep.side_effect = lambda seconds: now.__setitem__(0, now[0] + seconds)
    return patch("claude_code_hooks_daemon.daemon.cli.time", clock)


@contextlib.contextmanager
def _starting_child() -> Iterator[list[int]]:
    """Hold the daemon child's end of the start pipe open, as a child that
    is still running holds it, so the parent reads no end of file.

    Yields the list the held write end lands in once ``cmd_start`` opens
    the pipe; a test writes the child's progress to it.
    """
    held: list[int] = []
    real_pipe = os.pipe

    def pipe() -> tuple[int, int]:
        read_fd, write_fd = real_pipe()
        held.append(os.dup(write_fd))
        return read_fd, write_fd

    with patch("os.pipe", side_effect=pipe):
        yield held
    for fd in held:
        os.close(fd)


class TestCmdStartAlreadyRunning:
    """Tests for cmd_start when daemon is already running."""

    def test_already_running_returns_zero(self, tmp_path: Path) -> None:
        """cmd_start returns 0 if a live, healthy daemon is already running.

        Plan 00127: reuse requires BOTH a live PID file AND a live socket.
        """
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
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.LIVE,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
        ):
            result = cmd_start(args)
            assert result == 0


class TestCmdStartReportsTheDaemonItStarted:
    """Plan 00466 round 5: a PID file left naming a live process (a pid
    since reused, or another user's) made the parent report that pid as the
    daemon it had just started, before the child wrote its own."""

    _DISPLACED = 4242
    _STARTED = 5555

    def _start(
        self, tmp_path: Path, pid_file_reads: list[int | None], proven: bool
    ) -> tuple[int, str]:
        args = argparse.Namespace(project_root=tmp_path)
        stdout = io.StringIO()
        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                side_effect=[*pid_file_reads, *[pid_file_reads[-1]] * 1000],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            _proven_to_serve(tmp_path, proven),
            patch("os.fork", return_value=100),
            _poll_clock(),
            _starting_child(),
            patch.object(sys, "stdout", stdout),
        ):
            result = cmd_start(args)
        return result, stdout.getvalue()

    def test_the_pid_the_file_held_before_the_fork_is_not_the_started_daemon(
        self, tmp_path: Path
    ) -> None:
        result, output = self._start(tmp_path, [self._DISPLACED, self._DISPLACED], proven=True)
        assert result == 1
        assert "started successfully" not in output

    def test_the_new_pid_is_reported_once_proven(self, tmp_path: Path) -> None:
        result, output = self._start(
            tmp_path, [self._DISPLACED, self._DISPLACED, self._STARTED], proven=True
        )
        assert result == 0
        assert f"Daemon started successfully (PID: {self._STARTED})" in output

    def test_a_new_pid_nothing_proves_is_not_reported(self, tmp_path: Path) -> None:
        result, output = self._start(tmp_path, [None, self._STARTED], proven=False)
        assert result == 1
        assert "started successfully" not in output


class TestTheStartWaitFollowsTheDaemonsProgress:
    """Plan 00466 N202: the parent gave the daemon a fixed 5 s to write its
    PID file, which comes only after controller init, so a loaded host saw
    "failed to start (no PID file)" while the daemon came up. The wait now
    lasts while the child is alive and advancing, and says which of "exited",
    "no progress" and "still starting" ended it, and whether a PID file was
    waiting on its proof."""

    _STARTED = 5555

    def _start(
        self,
        tmp_path: Path,
        pid_file: Callable[[int, int | None], int | None],
        *,
        child_alive: bool,
        proven: bool = True,
        pid_path: Path | None = None,
    ) -> tuple[int, str, str]:
        """Run ``cmd_start``'s parent. ``pid_file(tick, progress_fd)`` answers
        each poll's PID-file read after the first, the pre-fork one, as
        ``read_pid_file`` does: a live pid or None. ``pid_path`` is the file
        itself, for what it records whatever its pid's state."""
        args = argparse.Namespace(project_root=tmp_path)
        stdout, stderr = io.StringIO(), io.StringIO()
        reads = [0]
        held: list[int] = []

        def read_pid_file(*_args: Any, **_kwargs: Any) -> int | None:
            reads[0] += 1
            if reads[0] == 1:
                return None
            return pid_file(reads[0] - 1, held[0] if held else None)

        child: contextlib.AbstractContextManager[list[int]] = (
            _starting_child() if child_alive else contextlib.nullcontext([])
        )
        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", side_effect=read_pid_file),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                return_value=pid_path or tmp_path / "no-daemon.pid",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            _proven_to_serve(tmp_path, proven),
            patch("os.fork", return_value=100),
            _poll_clock(),
            child as held_fds,
            patch.object(sys, "stdout", stdout),
            patch.object(sys, "stderr", stderr),
        ):
            held = held_fds
            result = cmd_start(args)
        return result, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def _ticks(seconds: float) -> int:
        return int(seconds / Timeout.DAEMON_PID_POLL_INTERVAL_SEC)

    @staticmethod
    def _advance(progress_fd: int | None) -> None:
        """The child reports progress, once ``cmd_start`` has given it a pipe."""
        if progress_fd is not None:
            os.write(progress_fd, b".")

    def test_a_daemon_still_advancing_past_five_seconds_is_reported_started(
        self, tmp_path: Path
    ) -> None:
        """Its PID file appears after 8 s, with progress on every tick."""
        started_at = self._ticks(8.0)

        def advancing(tick: int, progress_fd: int | None) -> int | None:
            self._advance(progress_fd)
            return self._STARTED if tick >= started_at else None

        result, output, _ = self._start(tmp_path, advancing, child_alive=True)

        assert result == 0
        assert f"Daemon started successfully (PID: {self._STARTED})" in output

    def test_a_daemon_that_exits_is_reported_at_once(self, tmp_path: Path) -> None:
        polls: list[int] = []

        def never(tick: int, progress_fd: int | None) -> int | None:
            polls.append(tick)
            return None

        result, _, errors = self._start(tmp_path, never, child_alive=False)

        assert result == 1
        assert "exited" in errors
        assert "no PID file" in errors
        assert len(polls) == 1

    def test_a_daemon_making_no_progress_is_reported_when_it_stalls(self, tmp_path: Path) -> None:
        polls: list[int] = []

        def silent(tick: int, progress_fd: int | None) -> int | None:
            polls.append(tick)
            return None

        result, _, errors = self._start(tmp_path, silent, child_alive=True)

        assert result == 1
        assert "no progress" in errors
        assert "no PID file" in errors
        assert len(polls) < self._ticks(Timeout.DAEMON_START_BUDGET_SEC)

    def test_a_pid_file_waiting_on_its_proof_is_named_not_called_missing(
        self, tmp_path: Path
    ) -> None:
        def unproven(tick: int, progress_fd: int | None) -> int | None:
            self._advance(progress_fd)
            return self._STARTED

        result, _, errors = self._start(tmp_path, unproven, child_alive=True, proven=False)

        assert result == 1
        assert f"PID {self._STARTED}" in errors
        assert "pending" in errors
        assert "no PID file" not in errors

    def test_a_daemon_advancing_for_ever_is_bounded_by_the_outer_budget(
        self, tmp_path: Path
    ) -> None:
        polls: list[int] = []

        def endless(tick: int, progress_fd: int | None) -> int | None:
            polls.append(tick)
            self._advance(progress_fd)
            return None

        result, _, errors = self._start(tmp_path, endless, child_alive=True)

        assert result == 1
        assert "still starting" in errors
        assert "no PID file" in errors
        assert len(polls) <= self._ticks(Timeout.DAEMON_START_BUDGET_SEC) + 1

    def test_a_daemon_that_wrote_its_pid_file_then_crashed_is_not_called_fileless(
        self, tmp_path: Path
    ) -> None:
        """Review 8, R8-2: ``read_pid_file`` answers None for a pid that is
        not running, so a daemon that wrote its PID file and then crashed was
        reported to have created none."""
        pid_path = tmp_path / "daemon.pid"

        def crashed(tick: int, progress_fd: int | None) -> int | None:
            pid_path.write_text(f"{_DEAD_PID}\n")
            return None

        result, _, errors = self._start(tmp_path, crashed, child_alive=False, pid_path=pid_path)

        assert result == 1
        assert "exited" in errors
        assert f"PID {_DEAD_PID}" in errors
        assert "no PID file" not in errors
        assert "pending" not in errors

    def test_a_daemon_that_exited_is_not_called_pending(self, tmp_path: Path) -> None:
        """Review 8, R8-2: an exit with a live pid in the PID file said the
        proof was pending, for a daemon that could no longer be proven."""
        result, _, errors = self._start(
            tmp_path, lambda tick, progress_fd: self._STARTED, child_alive=False, proven=False
        )

        assert result == 1
        assert "exited" in errors
        assert f"PID {self._STARTED}" in errors
        assert "pending" not in errors

    def test_a_daemon_waiting_on_another_starts_lock_is_not_called_stalled(
        self, tmp_path: Path
    ) -> None:
        """Review 8, R8-2: a daemon blocked on the start lock another start
        holds spends no CPU and reports nothing, and was given up on as
        making no progress. It says it is waiting, once."""
        polls: list[int] = []

        def waiting(tick: int, progress_fd: int | None) -> int | None:
            polls.append(tick)
            if tick == 1 and progress_fd is not None:
                os.write(progress_fd, b"w")
            return None

        result, _, errors = self._start(tmp_path, waiting, child_alive=True)

        assert result == 1
        assert "no progress" not in errors
        assert "start lock" in errors
        assert len(polls) >= self._ticks(Timeout.DAEMON_START_BUDGET_SEC)


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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("os.fork", return_value=100),  # Parent gets child PID
            _poll_clock(),
            _proven_to_serve(tmp_path),
        ):
            result = cmd_start(args)
            assert result == 0

    def test_stdio_is_flushed_before_forking(self, tmp_path: Path) -> None:
        """cmd_start must flush stdout/stderr BEFORE os.fork().

        Regression test: fork duplicates the parent's unflushed stdio buffer.
        The first child inherits it and flushes on sys.exit(0), so every line
        printed before the fork is emitted TWICE.

        Visible as `hooks-daemon restart` printing "Sent SIGTERM to daemon
        (PID: N) / Daemon stopped" twice for a single stop — with the SAME pid,
        which reads as two daemons having been killed. It only reproduces when
        stdout is block-buffered (redirected to a file or pipe), so it is
        invisible at an interactive terminal and hits captured output only —
        exactly the tooling that parses it.
        """
        args = argparse.Namespace(project_root=tmp_path)
        call_order: list[str] = []

        def fork() -> int:
            call_order.append("fork")
            return 100

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                side_effect=[None, 42],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch.object(sys.stdout, "flush", side_effect=lambda: call_order.append("flush")),
            patch("os.fork", side_effect=fork),
            _poll_clock(),
            _proven_to_serve(tmp_path),
        ):
            cmd_start(args)

        assert "fork" in call_order, "Test did not exercise the fork path"
        assert (
            "flush" in call_order
        ), "stdout was never flushed; the fork will duplicate buffered output"
        assert call_order.index("flush") < call_order.index(
            "fork"
        ), f"stdout must be flushed BEFORE fork, got order: {call_order}"

    def test_parent_does_not_unlink_socket_outside_lock(self, tmp_path: Path) -> None:
        """cmd_start must NOT unlink the daemon socket in the parent.

        Regression (Plan 00127, Finding 3): the parent took a liveness probe
        BEFORE the start lock, then unconditionally called cleanup_socket()
        outside the lock. A peer binding its socket in that probe->fork window
        had its LIVE socket unlinked, violating 'a LIVE socket is NEVER
        unlinked'. The child daemon clears stale sockets under the flock; the
        parent must never unlink.
        """
        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                side_effect=[None, 42],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup,
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("os.fork", return_value=100),
            _poll_clock(),
            _proven_to_serve(tmp_path),
        ):
            result = cmd_start(args)

        assert result == 0
        mock_cleanup.assert_not_called()

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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("os.fork", return_value=100),
            _poll_clock(),
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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
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
        # Startup hashes the loaded config (Plan 00415); a mock has no model.
        mock_config.model_dump.return_value = {}
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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
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
        # Startup hashes the loaded config (Plan 00415); a mock has no model.
        mock_config.model_dump.return_value = {}
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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
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

    def test_daemon_process_passes_project_handlers_config(self, tmp_path: Path) -> None:
        """cmd_start passes project_handlers_config to controller.initialise().

        Regression test for C1 bug: cmd_start() called controller.initialise()
        without project_handlers_config, so project handlers were never loaded
        at runtime.
        """
        args = argparse.Namespace(project_root=tmp_path)

        mock_config = MagicMock()
        # Startup hashes the loaded config (Plan 00415); a mock has no model.
        mock_config.model_dump.return_value = {}
        mock_config.daemon.socket_path = None
        mock_config.daemon.pid_file_path = None
        mock_config.daemon.get_socket_path.return_value = tmp_path / "sock"
        mock_config.daemon.get_pid_file_path.return_value = tmp_path / "pid"
        mock_project_handlers = MagicMock()
        mock_config.project_handlers = mock_project_handlers
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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
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

            # Verify project_handlers_config was passed to initialise()
            mock_controller.initialise.assert_called_once()
            call_kwargs = mock_controller.initialise.call_args
            assert (
                "project_handlers_config" in call_kwargs.kwargs
            ), "project_handlers_config must be passed to controller.initialise()"
            assert call_kwargs.kwargs["project_handlers_config"] is mock_project_handlers

    def test_daemon_process_with_existing_paths(self, tmp_path: Path) -> None:
        """Daemon process skips path setup when paths already configured."""
        args = argparse.Namespace(project_root=tmp_path)

        mock_config = MagicMock()
        # Startup hashes the loaded config (Plan 00415); a mock has no model.
        mock_config.model_dump.return_value = {}
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
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
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


class TestAStartUnderWayIsWaitedOnNotRepeated:
    """Plan 00466 lifecycle round 8b: a hook retried while a daemon was
    still initialising found no PID file and started again, and that start's
    single-daemon enforcement stopped the daemon still starting. A start now
    waits on one under way, and launches only once that has ended or died."""

    _INCUMBENT = 4242
    #: Sleeps of the lock wait before the start under way ends.
    _TICKS_TO_END = 3

    def _start(
        self,
        tmp_path: Path,
        *,
        pid: int | None,
        liveness: _SocketLiveness,
        ends: bool,
    ) -> tuple[int, MagicMock, MagicMock, str]:
        """``cmd_start`` while another start holds the launch lock; returns
        its result, the enforcement and fork mocks, and its stderr."""
        sock_path = tmp_path / "d.sock"
        under_way = LaunchLock.take(sock_path, Timeout.FILE_LOCK)
        now = [0.0]
        ticks = [0]

        def sleep(seconds: float) -> None:
            now[0] += seconds
            ticks[0] += 1
            if ends and ticks[0] == self._TICKS_TO_END:
                under_way.release()

        clock = MagicMock(wraps=time)
        clock.monotonic.side_effect = lambda: now[0]
        clock.sleep.side_effect = sleep
        stderr = io.StringIO()
        try:
            with (
                patch(
                    "claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path
                ),
                patch(
                    "claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=sock_path
                ),
                patch(
                    "claude_code_hooks_daemon.daemon.cli.get_pid_path",
                    return_value=tmp_path / "d.pid",
                ),
                patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=pid),
                patch(
                    "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                    return_value=liveness,
                ),
                patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon") as enforce,
                patch("os.fork", side_effect=OSError("no fork in this test")) as fork,
                patch("claude_code_hooks_daemon.daemon.server.time", clock),
                patch.object(sys, "stderr", stderr),
            ):
                result = cmd_start(argparse.Namespace(project_root=tmp_path))
        finally:
            under_way.release()
        return result, enforce, fork, stderr.getvalue()

    def test_a_start_still_under_way_at_the_budget_is_left_alone(self, tmp_path: Path) -> None:
        result, enforce, fork, stderr = self._start(
            tmp_path, pid=None, liveness=_SocketLiveness.NOT_LIVE, ends=False
        )
        assert result == 1
        enforce.assert_not_called()
        fork.assert_not_called()
        assert "still under way" in stderr, stderr

    def test_a_start_that_ends_serving_is_reused(self, tmp_path: Path) -> None:
        result, enforce, fork, _ = self._start(
            tmp_path, pid=self._INCUMBENT, liveness=_SocketLiveness.LIVE, ends=True
        )
        assert result == 0
        enforce.assert_not_called()
        fork.assert_not_called()
        assert start_under_way(tmp_path / "d.sock") is None

    def test_a_start_that_died_without_a_pid_file_is_replaced(self, tmp_path: Path) -> None:
        result, enforce, fork, _ = self._start(
            tmp_path, pid=None, liveness=_SocketLiveness.NOT_LIVE, ends=True
        )
        assert result == 1
        enforce.assert_called_once()
        fork.assert_called_once()
        assert start_under_way(tmp_path / "d.sock") is None

    def test_a_lock_it_cannot_open_starts_nothing(self, tmp_path: Path) -> None:
        launch_lock_path(tmp_path / "d.sock").symlink_to(tmp_path / "planted")
        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path),
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_socket_path",
                return_value=tmp_path / "d.sock",
            ),
            patch("claude_code_hooks_daemon.daemon.cli.enforce_single_daemon") as enforce,
            patch("os.fork") as fork,
        ):
            result = cmd_start(argparse.Namespace(project_root=tmp_path))
        assert result == 1
        enforce.assert_not_called()
        fork.assert_not_called()

    def test_the_daemon_holds_it_named_until_it_serves(self, tmp_path: Path) -> None:
        """The forked daemon names itself in the lock, and releases it only
        through ``serving``, which the server calls once it is bound."""
        sock_path = tmp_path / "d.sock"
        seen: dict[str, object] = {}

        def run_server(coroutine: Any) -> None:
            coroutine.close()
            seen["starting"] = start_under_way(sock_path)
            serving = daemon_class.call_args.kwargs["serving"]
            serving()
            seen["served"] = start_under_way(sock_path)

        mock_config = MagicMock()
        mock_config.daemon.socket_path = str(sock_path)
        mock_config.daemon.pid_file_path = str(tmp_path / "d.pid")
        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path),
            patch("claude_code_hooks_daemon.daemon.cli.get_socket_path", return_value=sock_path),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch(
                "claude_code_hooks_daemon.daemon.cli._socket_liveness_sync",
                return_value=_SocketLiveness.NOT_LIVE,
            ),
            patch("os.fork", side_effect=[0, 0]),
            patch("os.chdir"),
            patch("os.setsid"),
            patch("os.umask"),
            patch("os.dup2"),
            patch.object(sys, "stdin", MagicMock()),
            patch(
                "claude_code_hooks_daemon.config.models.Config.find_and_load",
                return_value=mock_config,
            ),
            patch("claude_code_hooks_daemon.daemon.cli._build_initialised_controller"),
            patch("claude_code_hooks_daemon.daemon.server.HooksDaemon") as daemon_class,
            patch("claude_code_hooks_daemon.daemon.paths.write_socket_discovery_file"),
            patch("claude_code_hooks_daemon.daemon.paths.cleanup_socket_discovery_file"),
            patch("asyncio.run", side_effect=run_server),
            pytest.raises(SystemExit) as exit_info,
        ):
            cmd_start(argparse.Namespace(project_root=tmp_path))
        assert exit_info.value.code == 0
        assert seen == {"starting": StartUnderWay(pid=os.getpid()), "served": None}
