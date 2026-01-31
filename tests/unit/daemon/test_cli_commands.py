"""Tests for CLI command implementations.

Focused tests covering critical CLI paths including:
- get_project_path and validation
- send_daemon_request
- cmd_status, cmd_stop
- cmd_config, cmd_init_config
- Error handling paths
"""

import argparse
import json
import socket
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import (
    cmd_config,
    cmd_init_config,
    cmd_status,
    cmd_stop,
    get_project_path,
    send_daemon_request,
)


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

    def test_successful_stop(self, tmp_path: Path) -> None:
        """cmd_stop successfully stops daemon."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path)

        # Track kill calls
        kill_count = [0]

        def mock_kill_func(pid: int, sig: int) -> None:
            kill_count[0] += 1
            if kill_count[0] == 1:
                # First call (SIGTERM) - succeeds
                return
            else:
                # Second call (check if alive) - process gone
                raise ProcessLookupError()

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("os.kill", side_effect=mock_kill_func),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_pid_file") as mock_cleanup_pid,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup_sock,
            patch("time.sleep"),
        ):
            result = cmd_stop(args)
            assert result == 0
            assert kill_count[0] >= 2
            mock_cleanup_pid.assert_called_once()
            mock_cleanup_sock.assert_called_once()

    def test_stop_process_not_found(self, tmp_path: Path) -> None:
        """cmd_stop handles stale PID file."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("os.kill", side_effect=ProcessLookupError()),
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_pid_file") as mock_cleanup_pid,
            patch("claude_code_hooks_daemon.daemon.cli.cleanup_socket") as mock_cleanup_sock,
        ):
            result = cmd_stop(args)
            assert result == 0
            mock_cleanup_pid.assert_called_once()
            mock_cleanup_sock.assert_called_once()

    def test_stop_permission_denied(self, tmp_path: Path) -> None:
        """cmd_stop handles permission denied."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("os.kill", side_effect=PermissionError("Permission denied")),
        ):
            result = cmd_stop(args)
            assert result == 1

    def test_stop_timeout(self, tmp_path: Path) -> None:
        """cmd_stop handles daemon not exiting within timeout."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        # Create valid config
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("os.kill", return_value=None),  # Process stays alive
            patch("time.sleep"),
        ):
            result = cmd_stop(args)
            assert result == 1


class TestCmdStopGenericException:
    """Tests for cmd_stop generic exception path (line 373-375)."""

    def test_stop_generic_exception(self, tmp_path: Path) -> None:
        """cmd_stop returns 1 on unexpected exception."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()

        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        args = argparse.Namespace(project_root=tmp_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch("os.kill", side_effect=RuntimeError("unexpected")),
        ):
            result = cmd_stop(args)
            assert result == 1


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
