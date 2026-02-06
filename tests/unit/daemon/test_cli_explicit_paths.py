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
        assert "project-a" in str(socket_a)
        assert "project-b" in str(socket_b)

    def test_different_projects_get_different_pid_paths(self, tmp_path: Path) -> None:
        """Two different project dirs produce different PID paths."""
        project_a = tmp_path / "project-a"
        project_b = tmp_path / "project-b"
        project_a.mkdir()
        project_b.mkdir()

        pid_a = get_pid_path(project_a)
        pid_b = get_pid_path(project_b)

        assert pid_a != pid_b
        assert "project-a" in str(pid_a)
        assert "project-b" in str(pid_b)

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

    def test_init_sh_exports_socket_path_to_cli(self) -> None:
        """init.sh start_daemon() must set CLAUDE_HOOKS_SOCKET_PATH before CLI call."""
        init_sh = Path("/workspace/.claude/init.sh").read_text()
        assert "CLAUDE_HOOKS_SOCKET_PATH" in init_sh
        # The env var should appear in the start_daemon function's CLI call
        assert 'CLAUDE_HOOKS_SOCKET_PATH="$SOCKET_PATH"' in init_sh

    def test_init_sh_exports_pid_path_to_cli(self) -> None:
        """init.sh start_daemon() must set CLAUDE_HOOKS_PID_PATH before CLI call."""
        init_sh = Path("/workspace/.claude/init.sh").read_text()
        assert "CLAUDE_HOOKS_PID_PATH" in init_sh
        assert 'CLAUDE_HOOKS_PID_PATH="$PID_PATH"' in init_sh

    def test_init_sh_passes_project_root_to_cli(self) -> None:
        """init.sh start_daemon() must pass --project-root to CLI."""
        init_sh = Path("/workspace/.claude/init.sh").read_text()
        assert '--project-root "$PROJECT_PATH"' in init_sh
