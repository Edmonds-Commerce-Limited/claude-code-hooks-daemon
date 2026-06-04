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
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
            self._create_mock_process(pid=300, name="bash", cmdline=["bash"]),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert result == [200]

    def test_multiple_daemon_processes_exist(self) -> None:
        """Returns all server PIDs; transient CLI helpers are excluded."""
        mock_processes = [
            self._create_mock_process(
                pid=100,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
            self._create_mock_process(pid=200, name="bash", cmdline=["bash"]),
            self._create_mock_process(
                pid=300,
                name="python",
                cmdline=[
                    "/usr/bin/python3",
                    "-m",
                    "claude_code_hooks_daemon.daemon.cli",
                    "restart",
                ],
            ),
            # Transient CLI helper — NOT a daemon server, must be excluded.
            self._create_mock_process(
                pid=400,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "status"],
            ),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert sorted(result) == [100, 300]

    def test_broad_substring_matches_are_rejected(self) -> None:
        """The old name/substring matching is gone: only a cli module + launch
        subcommand cmdline counts as a daemon server."""
        mock_processes = [
            # NOT a server: package string only in the process name.
            self._create_mock_process(pid=100, name="claude_code_hooks_daemon", cmdline=["daemon"]),
            # NOT a server: package string only as a wrapper-script substring.
            self._create_mock_process(
                pid=400,
                name="python",
                cmdline=["python", "my_claude_code_hooks_daemon_wrapper.py"],
            ),
            # NOT a server: bare package module, no .daemon.cli, no subcommand.
            self._create_mock_process(
                pid=500,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon"],
            ),
            # The only real server in the set.
            self._create_mock_process(
                pid=600,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
        ]

        with patch("psutil.process_iter", return_value=mock_processes):
            result = find_all_daemon_processes()

        assert result == [600]

    def test_handles_permission_errors_gracefully(self) -> None:
        """Ignores processes whose cmdline() raises AccessDenied."""
        mock_process_ok = self._create_mock_process(
            pid=100,
            name="python",
            cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
        )
        mock_process_denied = MagicMock(spec=psutil.Process)
        mock_process_denied.pid = 200
        mock_process_denied.cmdline.side_effect = psutil.AccessDenied(pid=200)

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
            cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
        )
        mock_process_gone = MagicMock(spec=psutil.Process)
        mock_process_gone.pid = 200
        mock_process_gone.cmdline.side_effect = psutil.NoSuchProcess(pid=200)

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
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
            ),
            self._create_mock_process(
                pid=current_pid + 1,
                name="python",
                cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
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


class TestFindAllDaemonProcessesProjectRootFilter:
    """Tests for project-root scoping of find_all_daemon_processes().

    Regression for the cross-project daemon-kill outage: a container daemon's
    single-process enforcement must NEVER kill a daemon serving a DIFFERENT
    project root, even when PID namespaces are shared and the other project's
    daemon is visible. Scoping the search to our own project root prevents that.
    """

    @staticmethod
    def _proc(pid: int, cmdline: list[str], name: str = "python") -> MagicMock:
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = pid
        mock_proc.name.return_value = name
        mock_proc.cmdline.return_value = cmdline
        return mock_proc

    def test_filter_excludes_other_project_daemon_by_venv_path(self) -> None:
        """Daemons whose venv path is under a different project root are excluded."""
        ours = self._proc(
            pid=100,
            cmdline=[
                "/workspace/untracked/venv-py311-28fb230b/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "start",
            ],
        )
        other = self._proc(
            pid=200,
            cmdline=[
                "/home/user/project/.claude/hooks-daemon/untracked/"
                "venv-py314-fefc85e6/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "restart",
            ],
        )

        with patch("psutil.process_iter", return_value=[ours, other]):
            result = find_all_daemon_processes(project_root="/workspace")

        assert result == [100]

    def test_filter_excludes_other_project_normal_install(self) -> None:
        """A normal-install daemon's project root is derived before .claude/."""
        other = self._proc(
            pid=300,
            cmdline=[
                "/home/user/project/.claude/hooks-daemon/untracked/"
                "venv-py314-fefc85e6/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "start",
            ],
        )

        with patch("psutil.process_iter", return_value=[other]):
            ours = find_all_daemon_processes(project_root="/home/user/project")
            stranger = find_all_daemon_processes(project_root="/workspace")

        assert ours == [300]
        assert stranger == []

    def test_filter_matches_via_project_root_flag(self) -> None:
        """The --project-root cmdline flag identifies the daemon's project."""
        proc = self._proc(
            pid=400,
            cmdline=[
                "python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "--project-root",
                "/workspace",
                "start",
            ],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/workspace") == [400]
            assert find_all_daemon_processes(project_root="/other") == []

    def test_filter_matches_via_project_root_flag_equals_form(self) -> None:
        """The --project-root=PATH form is also recognised."""
        proc = self._proc(
            pid=500,
            cmdline=[
                "python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "--project-root=/workspace",
                "start",
            ],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/workspace") == [500]

    def test_filter_excludes_daemon_with_undeterminable_root(self) -> None:
        """When a daemon's project root cannot be determined, it is NOT killed.

        Conservative default: never terminate a daemon we cannot positively
        attribute to our own project.
        """
        # A real server cmdline (bare "python", no venv path, no --project-root)
        # whose project root cannot be determined → conservatively NOT killed.
        proc = self._proc(
            pid=600,
            cmdline=["python", "-m", "claude_code_hooks_daemon.daemon.cli", "start"],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/workspace") == []

    def test_filter_normalizes_trailing_slash(self) -> None:
        """Trailing-slash differences in the project root still match."""
        proc = self._proc(
            pid=700,
            cmdline=[
                "/workspace/untracked/venv-py311-28fb230b/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "start",
            ],
        )

        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes(project_root="/workspace/") == [700]

    def test_no_filter_returns_all_daemons(self) -> None:
        """Passing no project_root preserves the legacy system-wide behaviour."""
        ours = self._proc(
            pid=100,
            cmdline=[
                "/workspace/untracked/venv-py311-28fb230b/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "start",
            ],
        )
        other = self._proc(
            pid=200,
            cmdline=[
                "/home/user/project/.claude/hooks-daemon/untracked/"
                "venv-py314-fefc85e6/bin/python",
                "-m",
                "claude_code_hooks_daemon.daemon.cli",
                "start",
            ],
        )

        with patch("psutil.process_iter", return_value=[ours, other]):
            assert sorted(find_all_daemon_processes()) == [100, 200]


class TestDaemonServerMatching:
    """find_all_daemon_processes must match ONLY genuine daemon SERVER
    processes — those launched via ``cli start`` / ``cli restart`` — and never
    transient CLI helpers (status/stop/logs/...) or hook forwarders. Plan 00119.

    Verified in daemon/cli.py: daemonization (os.fork/os.setsid/HooksDaemon/
    asyncio.run) happens only in cmd_start, reachable only from the ``start``
    subcommand and from cmd_restart (the ``restart`` subcommand). os.fork does
    not rewrite argv, so the detached daemon's cmdline carries ``start`` or
    ``restart``.
    """

    _MODULE = "claude_code_hooks_daemon.daemon.cli"

    @staticmethod
    def _proc(pid: int, cmdline: list[str], name: str = "python") -> MagicMock:
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = pid
        mock_proc.name.return_value = name
        mock_proc.cmdline.return_value = cmdline
        return mock_proc

    def test_start_launched_daemon_matches(self) -> None:
        proc = self._proc(700, ["python", "-m", self._MODULE, "start"])
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == [700]

    def test_restart_launched_daemon_matches(self) -> None:
        proc = self._proc(701, ["python", "-m", self._MODULE, "restart"])
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == [701]

    def test_start_with_global_project_root_flag_matches(self) -> None:
        proc = self._proc(
            702, ["python", "-m", self._MODULE, "--project-root", "/workspace", "start"]
        )
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == [702]

    def test_transient_cli_helpers_not_matched(self) -> None:
        transient = [
            "status",
            "stop",
            "logs",
            "health",
            "repair",
            "check-truth-changes",
            "generate-docs",
        ]
        procs = [
            self._proc(800 + i, ["python", "-m", self._MODULE, sub])
            for i, sub in enumerate(transient)
        ]
        with patch("psutil.process_iter", return_value=procs):
            assert find_all_daemon_processes() == []

    def test_hook_forwarder_not_matched(self) -> None:
        proc = self._proc(900, ["python", "-m", "claude_code_hooks_daemon.hooks.pre_tool_use"])
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == []

    def test_bare_cli_without_subcommand_not_matched(self) -> None:
        proc = self._proc(901, ["python", "-m", self._MODULE])
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == []

    def test_name_substring_alone_not_matched(self) -> None:
        proc = self._proc(
            902,
            ["python", "my_claude_code_hooks_daemon_wrapper.py"],
            name="claude_code_hooks_daemon",
        )
        with patch("psutil.process_iter", return_value=[proc]):
            assert find_all_daemon_processes() == []

    def test_launch_subcommands_allowlist_is_exactly_start_and_restart(self) -> None:
        """Guard: the allowlist is provably complete (only start/restart reach
        cmd_start). If a future subcommand daemonizes, add it here AND update
        this guard — do not silently widen the match."""
        from claude_code_hooks_daemon.daemon.process_verification import (
            _DAEMON_LAUNCH_SUBCOMMANDS,
        )

        assert _DAEMON_LAUNCH_SUBCOMMANDS == ("start", "restart")


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
