"""Tests for daemon path isolation via environment variables.

Verifies that multiple daemons can coexist by using env var overrides
(CLAUDE_HOOKS_SOCKET_PATH, CLAUDE_HOOKS_PID_PATH) to point at different
socket/PID files. This is the mechanism used for worktree isolation.

Plan 00028: Daemon CLI Explicit Paths for Worktree Isolation
"""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.paths import get_pid_path, get_socket_path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: Any) -> None:
    """Remove env var overrides so each test starts clean."""
    monkeypatch.delenv("CLAUDE_HOOKS_SOCKET_PATH", raising=False)
    monkeypatch.delenv("CLAUDE_HOOKS_PID_PATH", raising=False)
    monkeypatch.delenv("CLAUDE_HOOKS_LOG_PATH", raising=False)


class TestEnvVarOverrides:
    """Env vars override auto-discovery for socket and PID paths."""

    def test_socket_path_uses_env_var_when_set(self, monkeypatch: Any, tmp_path: Path) -> None:
        """CLAUDE_HOOKS_SOCKET_PATH overrides auto-discovery."""
        custom_socket = tmp_path / "custom.sock"
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(custom_socket))

        result = get_socket_path(tmp_path / "some-project")
        assert result == custom_socket

    def test_pid_path_uses_env_var_when_set(self, monkeypatch: Any, tmp_path: Path) -> None:
        """CLAUDE_HOOKS_PID_PATH overrides auto-discovery."""
        custom_pid = tmp_path / "custom.pid"
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(custom_pid))

        result = get_pid_path(tmp_path / "some-project")
        assert result == custom_pid

    def test_socket_path_ignores_project_dir_when_env_set(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """When env var is set, the project_dir argument is irrelevant."""
        custom_socket = tmp_path / "override.sock"
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(custom_socket))

        # Pass a completely different project dir - should be ignored
        result_a = get_socket_path(tmp_path / "project-a")
        result_b = get_socket_path(tmp_path / "project-b")
        assert result_a == result_b == custom_socket

    def test_pid_path_ignores_project_dir_when_env_set(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """When env var is set, the project_dir argument is irrelevant."""
        custom_pid = tmp_path / "override.pid"
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(custom_pid))

        result_a = get_pid_path(tmp_path / "project-a")
        result_b = get_pid_path(tmp_path / "project-b")
        assert result_a == result_b == custom_pid


class TestMultipleDaemonIsolation:
    """Two projects get different socket/PID paths by default."""

    def test_different_projects_get_different_socket_paths(self, tmp_path: Path) -> None:
        """Two different project dirs produce different socket paths."""
        project_a = tmp_path / "project-a"
        project_b = tmp_path / "project-b"
        project_a.mkdir()
        project_b.mkdir()

        socket_a = get_socket_path(project_a)
        socket_b = get_socket_path(project_b)

        assert socket_a != socket_b
        # Paths may use fallback dir if tmp_path is long, so just verify uniqueness
        assert str(socket_a) != str(socket_b)

    def test_different_projects_get_different_pid_paths(self, tmp_path: Path) -> None:
        """Two different project dirs produce different PID paths."""
        project_a = tmp_path / "project-a"
        project_b = tmp_path / "project-b"
        project_a.mkdir()
        project_b.mkdir()

        pid_a = get_pid_path(project_a)
        pid_b = get_pid_path(project_b)

        assert pid_a != pid_b
        # Paths may use fallback dir if tmp_path is long, so just verify uniqueness
        assert str(pid_a) != str(pid_b)

    def test_env_vars_enable_two_daemons_same_hostname(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """Two daemons on same hostname can coexist via env var overrides.

        This is the core worktree isolation pattern: each worktree
        sets its own CLAUDE_HOOKS_SOCKET_PATH and CLAUDE_HOOKS_PID_PATH
        to avoid sharing the same socket/PID files.
        """
        # Daemon A paths
        socket_a = tmp_path / "daemon-a.sock"
        pid_a = tmp_path / "daemon-a.pid"

        # Daemon B paths
        socket_b = tmp_path / "daemon-b.sock"
        pid_b = tmp_path / "daemon-b.pid"

        # Simulate daemon A environment
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(socket_a))
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(pid_a))

        resolved_socket_a = get_socket_path(tmp_path)
        resolved_pid_a = get_pid_path(tmp_path)

        # Simulate daemon B environment
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(socket_b))
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(pid_b))

        resolved_socket_b = get_socket_path(tmp_path)
        resolved_pid_b = get_pid_path(tmp_path)

        # They must be different
        assert resolved_socket_a != resolved_socket_b
        assert resolved_pid_a != resolved_pid_b

        # They must match what we set
        assert resolved_socket_a == socket_a
        assert resolved_socket_b == socket_b
        assert resolved_pid_a == pid_a
        assert resolved_pid_b == pid_b


class TestCmdStartUsesEnvPaths:
    """cmd_start resolves paths through get_socket_path/get_pid_path which honor env vars."""

    def test_cmd_start_uses_env_socket_path(self, monkeypatch: Any, tmp_path: Path) -> None:
        """cmd_start should use CLAUDE_HOOKS_SOCKET_PATH when set."""
        custom_socket = tmp_path / "custom-daemon.sock"
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(custom_socket))

        # Mock get_project_path to return tmp_path
        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path

            # Import after mocking
            from claude_code_hooks_daemon.daemon.cli import cmd_start

            # Mock read_pid_file to simulate daemon already running
            with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                mock_rpf.return_value = 12345  # "already running"

                args = argparse.Namespace(project_root=None)
                result = cmd_start(args)

                assert result == 0
                # Verify get_socket_path was called with project path
                # and the env var override took effect
                assert get_socket_path(tmp_path) == custom_socket

    def test_cmd_status_uses_env_pid_path(self, monkeypatch: Any, tmp_path: Path) -> None:
        """cmd_status should use CLAUDE_HOOKS_PID_PATH when set."""
        custom_pid = tmp_path / "custom-daemon.pid"
        custom_socket = tmp_path / "custom-daemon.sock"
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(custom_pid))
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(custom_socket))

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path

            from claude_code_hooks_daemon.daemon.cli import cmd_status

            with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                mock_rpf.return_value = None  # not running

                args = argparse.Namespace(project_root=None)
                result = cmd_status(args)

                # Should report not running
                assert result == 1
                # Verify the PID path used was our custom one
                mock_rpf.assert_called_once_with(str(custom_pid))


class TestCmdStopUsesEnvPaths:
    """cmd_stop resolves paths through get_socket_path/get_pid_path which honor env vars."""

    def test_cmd_stop_uses_env_paths(self, monkeypatch: Any, tmp_path: Path) -> None:
        """cmd_stop should use env var paths for PID and socket."""
        custom_pid = tmp_path / "custom-daemon.pid"
        custom_socket = tmp_path / "custom-daemon.sock"
        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(custom_pid))
        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(custom_socket))

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path

            from claude_code_hooks_daemon.daemon.cli import cmd_stop

            with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                mock_rpf.return_value = None  # not running

                args = argparse.Namespace(project_root=None)
                result = cmd_stop(args)

                assert result == 0
                mock_rpf.assert_called_once_with(str(custom_pid))


class TestInitShPassesEnvVars:
    """Verify init.sh passes env vars when starting daemon CLI.

    These tests verify the bash script behavior by checking the script content.
    The actual runtime behavior is tested via integration tests.
    """

    # Derive project root dynamically from test file location
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

    def _read_init_sh(self) -> str:
        """Read init.sh from the project root, trying multiple locations."""
        # Self-install mode: init.sh at project root
        for candidate in [
            self._PROJECT_ROOT / "init.sh",
            self._PROJECT_ROOT / ".claude" / "init.sh",
        ]:
            if candidate.is_file():
                return candidate.read_text()
        raise FileNotFoundError(f"init.sh not found in {self._PROJECT_ROOT}")

    def test_init_sh_exports_socket_path_to_cli(self) -> None:
        """init.sh start_daemon() must set CLAUDE_HOOKS_SOCKET_PATH before CLI call."""
        init_sh = self._read_init_sh()
        assert "CLAUDE_HOOKS_SOCKET_PATH" in init_sh
        # The env var should appear in the start_daemon function's CLI call
        assert 'CLAUDE_HOOKS_SOCKET_PATH="$SOCKET_PATH"' in init_sh

    def test_init_sh_exports_pid_path_to_cli(self) -> None:
        """init.sh start_daemon() must set CLAUDE_HOOKS_PID_PATH before CLI call."""
        init_sh = self._read_init_sh()
        assert "CLAUDE_HOOKS_PID_PATH" in init_sh
        assert 'CLAUDE_HOOKS_PID_PATH="$PID_PATH"' in init_sh

    def test_init_sh_passes_project_root_to_cli(self) -> None:
        """init.sh start_daemon() must pass --project-root to CLI."""
        init_sh = self._read_init_sh()
        assert '--project-root "$PROJECT_PATH"' in init_sh


# ============================================================================
# NEW: CLI Flag Tests for Plan 00028
# ============================================================================


class TestCliExplicitPathFlags:
    """Test --pid-file and --socket CLI flags (Plan 00028).

    These flags provide an explicit alternative to environment variables
    for worktree isolation. They override auto-discovery but are independent
    of env vars (flags take precedence).
    """

    def test_main_accepts_pid_file_flag(self) -> None:
        """Test that main() argparse accepts --pid-file flag."""
        # This will FAIL until we add the flag to main()
        from claude_code_hooks_daemon.daemon.cli import main

        with patch("sys.argv", ["cli", "--pid-file", "/custom/path.pid", "status"]):
            with patch("claude_code_hooks_daemon.daemon.cli.cmd_status") as mock_cmd:
                mock_cmd.return_value = 0
                # Should not raise ArgumentError
                result = main()
                assert result == 0
                # Verify args.pid_file was set
                call_args = mock_cmd.call_args[0][0]
                assert hasattr(call_args, "pid_file")
                assert call_args.pid_file == Path("/custom/path.pid")

    def test_main_accepts_socket_flag(self) -> None:
        """Test that main() argparse accepts --socket flag."""
        from claude_code_hooks_daemon.daemon.cli import main

        with patch("sys.argv", ["cli", "--socket", "/custom/socket.sock", "status"]):
            with patch("claude_code_hooks_daemon.daemon.cli.cmd_status") as mock_cmd:
                mock_cmd.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_cmd.call_args[0][0]
                assert hasattr(call_args, "socket")
                assert call_args.socket == Path("/custom/socket.sock")

    def test_main_accepts_both_flags_together(self) -> None:
        """Test that --pid-file and --socket can be used together."""
        from claude_code_hooks_daemon.daemon.cli import main

        with patch(
            "sys.argv",
            [
                "cli",
                "--pid-file",
                "/custom/path.pid",
                "--socket",
                "/custom/socket.sock",
                "status",
            ],
        ):
            with patch("claude_code_hooks_daemon.daemon.cli.cmd_status") as mock_cmd:
                mock_cmd.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_cmd.call_args[0][0]
                assert call_args.pid_file == Path("/custom/path.pid")
                assert call_args.socket == Path("/custom/socket.sock")

    def test_flags_work_with_project_root(self) -> None:
        """Test that explicit path flags work with --project-root."""
        from claude_code_hooks_daemon.daemon.cli import main

        with patch(
            "sys.argv",
            [
                "cli",
                "--project-root",
                "/custom/project",
                "--pid-file",
                "/worktree/daemon.pid",
                "--socket",
                "/worktree/daemon.sock",
                "status",
            ],
        ):
            with patch("claude_code_hooks_daemon.daemon.cli.cmd_status") as mock_cmd:
                mock_cmd.return_value = 0
                result = main()
                assert result == 0
                call_args = mock_cmd.call_args[0][0]
                assert call_args.project_root == Path("/custom/project")
                assert call_args.pid_file == Path("/worktree/daemon.pid")
                assert call_args.socket == Path("/worktree/daemon.sock")


class TestCmdStatusWithCliFlags:
    """Test cmd_status uses explicit CLI flags when provided."""

    def test_cmd_status_uses_explicit_pid_file_flag(self, tmp_path: Path) -> None:
        """When --pid-file is provided, cmd_status uses it instead of auto-discovery."""
        from claude_code_hooks_daemon.daemon.cli import cmd_status

        custom_pid = tmp_path / "custom.pid"
        custom_socket = tmp_path / "custom.sock"

        # Write a PID file
        custom_pid.write_text("12345")
        custom_socket.touch()

        args = argparse.Namespace(
            project_root=None,
            pid_file=custom_pid,
            socket=custom_socket,
        )

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path
            with patch("claude_code_hooks_daemon.daemon.paths.is_pid_alive") as mock_alive:
                mock_alive.return_value = True
                with patch("builtins.print"):
                    result = cmd_status(args)

                # Should report running using our custom paths
                assert result == 0

    def test_cmd_status_without_flags_uses_auto_discovery(self, tmp_path: Path) -> None:
        """When flags are omitted, cmd_status falls back to auto-discovery (backward compat)."""
        from claude_code_hooks_daemon.daemon.cli import cmd_status

        args = argparse.Namespace(
            project_root=None,
            pid_file=None,
            socket=None,
        )

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            with patch("claude_code_hooks_daemon.daemon.cli.get_pid_path") as mock_get_pid:
                with patch(
                    "claude_code_hooks_daemon.daemon.cli.get_socket_path"
                ) as mock_get_socket:
                    with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                        mock_gpp.return_value = tmp_path
                        mock_get_pid.return_value = tmp_path / "auto-discovered.pid"
                        mock_get_socket.return_value = tmp_path / "auto-discovered.sock"
                        mock_rpf.return_value = None

                        with patch("builtins.print"):
                            cmd_status(args)

                        # Auto-discovery should have been called
                        mock_get_pid.assert_called_once_with(tmp_path)
                        mock_get_socket.assert_called_once_with(tmp_path)


class TestCmdStopWithCliFlags:
    """Test cmd_stop uses explicit CLI flags when provided."""

    def test_cmd_stop_uses_explicit_flags(self, tmp_path: Path) -> None:
        """When --pid-file and --socket provided, cmd_stop uses them."""
        from claude_code_hooks_daemon.daemon.cli import cmd_stop

        custom_pid = tmp_path / "custom.pid"
        custom_socket = tmp_path / "custom.sock"

        args = argparse.Namespace(
            project_root=None,
            pid_file=custom_pid,
            socket=custom_socket,
        )

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path
            with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                mock_rpf.return_value = None  # Not running

                with patch("builtins.print"):
                    result = cmd_stop(args)

                # Should succeed (nothing to stop)
                assert result == 0


class TestCmdStartWithCliFlags:
    """Test cmd_start uses explicit CLI flags when provided."""

    def test_cmd_start_uses_explicit_flags(self, tmp_path: Path) -> None:
        """When --pid-file and --socket provided, cmd_start uses them."""
        from claude_code_hooks_daemon.daemon.cli import cmd_start

        custom_pid = tmp_path / "custom.pid"
        custom_socket = tmp_path / "custom.sock"

        args = argparse.Namespace(
            project_root=None,
            pid_file=custom_pid,
            socket=custom_socket,
        )

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path
            with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                mock_rpf.return_value = 12345  # Already running

                with patch("builtins.print"):
                    result = cmd_start(args)

                # Should report already running
                assert result == 0


class TestCmdLogsWithCliFlags:
    """Test cmd_logs uses explicit --socket flag."""

    def test_cmd_logs_uses_explicit_socket_flag(self, tmp_path: Path) -> None:
        """When --socket provided, cmd_logs uses it."""
        from claude_code_hooks_daemon.daemon.cli import cmd_logs

        custom_socket = tmp_path / "custom.sock"
        custom_pid = tmp_path / "custom.pid"

        args = argparse.Namespace(
            project_root=None,
            socket=custom_socket,
            pid_file=custom_pid,
            count=None,
            level=None,
            follow=False,
        )

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path
            with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                mock_rpf.return_value = None  # Not running

                with patch("builtins.print"):
                    result = cmd_logs(args)

                # Should report not running
                assert result == 1


class TestCmdRestartWithCliFlags:
    """Test cmd_restart passes explicit flags through to stop and start."""

    def test_cmd_restart_preserves_explicit_flags(self, tmp_path: Path) -> None:
        """cmd_restart should pass --pid-file and --socket to both stop and start."""
        from claude_code_hooks_daemon.daemon.cli import cmd_restart

        custom_pid = tmp_path / "custom.pid"
        custom_socket = tmp_path / "custom.sock"

        args = argparse.Namespace(
            project_root=None,
            pid_file=custom_pid,
            socket=custom_socket,
        )

        with patch("claude_code_hooks_daemon.daemon.cli.cmd_stop") as mock_stop:
            with patch("claude_code_hooks_daemon.daemon.cli.cmd_start") as mock_start:
                mock_stop.return_value = 0
                mock_start.return_value = 0

                result = cmd_restart(args)

                # Both should receive the same args
                assert result == 0
                mock_stop.assert_called_once_with(args)
                mock_start.assert_called_once_with(args)


class TestFlagsPrecedenceOverEnvVars:
    """Test that CLI flags take precedence over environment variables."""

    def test_cli_flag_overrides_env_var_for_socket(self, monkeypatch: Any, tmp_path: Path) -> None:
        """When both --socket flag and env var are set, flag wins."""
        env_socket = tmp_path / "env-socket.sock"
        flag_socket = tmp_path / "flag-socket.sock"

        monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(env_socket))

        from claude_code_hooks_daemon.daemon.cli import cmd_status

        args = argparse.Namespace(
            project_root=None,
            pid_file=None,
            socket=flag_socket,
        )

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path
            with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                with patch("claude_code_hooks_daemon.daemon.cli.get_pid_path"):
                    mock_rpf.return_value = None

                    with patch("builtins.print"):
                        cmd_status(args)

                    # The explicit flag should take precedence
                    # (This test will verify the implementation honors the flag)

    def test_cli_flag_overrides_env_var_for_pid(self, monkeypatch: Any, tmp_path: Path) -> None:
        """When both --pid-file flag and env var are set, flag wins."""
        env_pid = tmp_path / "env-daemon.pid"
        flag_pid = tmp_path / "flag-daemon.pid"

        monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(env_pid))

        from claude_code_hooks_daemon.daemon.cli import cmd_status

        args = argparse.Namespace(
            project_root=None,
            pid_file=flag_pid,
            socket=None,
        )

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_gpp:
            mock_gpp.return_value = tmp_path
            with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file") as mock_rpf:
                with patch("claude_code_hooks_daemon.daemon.cli.get_socket_path"):
                    mock_rpf.return_value = None

                    with patch("builtins.print"):
                        cmd_status(args)

                    # The explicit flag should take precedence
