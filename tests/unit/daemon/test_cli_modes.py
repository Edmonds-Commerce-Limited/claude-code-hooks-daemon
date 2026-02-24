"""Tests for CLI mode commands (get-mode, set-mode, restart mode advisory)."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant


class TestCmdGetMode:
    """Tests for cmd_get_mode CLI command."""

    def test_get_mode_shows_default(self) -> None:
        """get-mode shows default mode."""
        from claude_code_hooks_daemon.daemon.cli import cmd_get_mode

        args = Mock()
        args.project_root = None
        args.json = False

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_project,
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path") as mock_socket,
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path") as mock_pid,
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=123),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request") as mock_send,
        ):
            mock_project.return_value = "/tmp/project"
            mock_socket.return_value = "/tmp/sock"
            mock_pid.return_value = "/tmp/pid"
            mock_send.return_value = {
                "result": {
                    ModeConstant.KEY_MODE: DaemonMode.DEFAULT.value,
                    ModeConstant.KEY_CUSTOM_MESSAGE: None,
                }
            }

            result = cmd_get_mode(args)

        assert result == 0

    def test_get_mode_daemon_not_running(self) -> None:
        """get-mode returns 1 when daemon not running."""
        from claude_code_hooks_daemon.daemon.cli import cmd_get_mode

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
        ):
            result = cmd_get_mode(args)

        assert result == 1

    def test_get_mode_json_output(self) -> None:
        """get-mode --json outputs JSON."""
        from claude_code_hooks_daemon.daemon.cli import cmd_get_mode

        args = Mock()
        args.project_root = None
        args.json = True

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=123),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request") as mock_send,
        ):
            mock_send.return_value = {
                "result": {
                    ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
                    ModeConstant.KEY_CUSTOM_MESSAGE: "finish tasks",
                }
            }

            result = cmd_get_mode(args)

        assert result == 0


class TestCmdSetMode:
    """Tests for cmd_set_mode CLI command."""

    def test_set_mode_unattended(self) -> None:
        """set-mode unattended changes mode."""
        from claude_code_hooks_daemon.daemon.cli import cmd_set_mode

        args = Mock()
        args.project_root = None
        args.mode = "unattended"
        args.message = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=123),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request") as mock_send,
        ):
            mock_send.return_value = {
                "result": {
                    ModeConstant.KEY_STATUS: ModeConstant.STATUS_CHANGED,
                    ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
                    ModeConstant.KEY_CUSTOM_MESSAGE: None,
                }
            }

            result = cmd_set_mode(args)

        assert result == 0
        # Verify the request sent correct mode
        call_args = mock_send.call_args[0]
        request = call_args[1]
        assert request["hook_input"][ModeConstant.KEY_MODE] == DaemonMode.UNATTENDED.value

    def test_set_mode_with_message(self) -> None:
        """set-mode --message passes custom message."""
        from claude_code_hooks_daemon.daemon.cli import cmd_set_mode

        args = Mock()
        args.project_root = None
        args.mode = "unattended"
        args.message = "finish the release"

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=123),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request") as mock_send,
        ):
            mock_send.return_value = {
                "result": {
                    ModeConstant.KEY_STATUS: ModeConstant.STATUS_CHANGED,
                    ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
                    ModeConstant.KEY_CUSTOM_MESSAGE: "finish the release",
                }
            }

            result = cmd_set_mode(args)

        assert result == 0
        call_args = mock_send.call_args[0]
        request = call_args[1]
        assert request["hook_input"][ModeConstant.KEY_CUSTOM_MESSAGE] == "finish the release"

    def test_set_mode_daemon_not_running(self) -> None:
        """set-mode returns 1 when daemon not running."""
        from claude_code_hooks_daemon.daemon.cli import cmd_set_mode

        args = Mock()
        args.project_root = None
        args.mode = "unattended"
        args.message = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
        ):
            result = cmd_set_mode(args)

        assert result == 1

    def test_set_mode_error_response(self) -> None:
        """set-mode returns 1 on error response."""
        from claude_code_hooks_daemon.daemon.cli import cmd_set_mode

        args = Mock()
        args.project_root = None
        args.mode = "bogus"
        args.message = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=123),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request") as mock_send,
        ):
            mock_send.return_value = {"error": "Invalid mode: 'bogus'"}

            result = cmd_set_mode(args)

        assert result == 1


class TestGetCurrentMode:
    """Tests for _get_current_mode helper."""

    def test_returns_mode_dict_when_daemon_running(self) -> None:
        """Returns mode result dict when daemon is running."""
        from claude_code_hooks_daemon.daemon.cli import _get_current_mode

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_project,
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path") as mock_socket,
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path") as mock_pid,
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=123),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request") as mock_send,
        ):
            mock_project.return_value = Path("/tmp/project")
            mock_socket.return_value = Path("/tmp/sock")
            mock_pid.return_value = Path("/tmp/pid")
            mock_send.return_value = {
                "result": {
                    ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
                    ModeConstant.KEY_CUSTOM_MESSAGE: "finish tasks",
                }
            }

            result = _get_current_mode(args)

        assert result is not None
        assert result[ModeConstant.KEY_MODE] == DaemonMode.UNATTENDED.value
        assert result[ModeConstant.KEY_CUSTOM_MESSAGE] == "finish tasks"

    def test_returns_none_when_daemon_not_running(self) -> None:
        """Returns None when daemon is not running (no PID)."""
        from claude_code_hooks_daemon.daemon.cli import _get_current_mode

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path"),
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path"),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
        ):
            result = _get_current_mode(args)

        assert result is None

    def test_returns_none_on_communication_error(self) -> None:
        """Returns None when daemon communication fails."""
        from claude_code_hooks_daemon.daemon.cli import _get_current_mode

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_project,
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path") as mock_socket,
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path") as mock_pid,
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=123),
            patch("claude_code_hooks_daemon.daemon.cli.send_daemon_request", return_value=None),
        ):
            mock_project.return_value = Path("/tmp/project")
            mock_socket.return_value = Path("/tmp/sock")
            mock_pid.return_value = Path("/tmp/pid")

            result = _get_current_mode(args)

        assert result is None

    def test_returns_none_on_error_response(self) -> None:
        """Returns None when daemon returns error."""
        from claude_code_hooks_daemon.daemon.cli import _get_current_mode

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.get_project_path") as mock_project,
            patch("claude_code_hooks_daemon.daemon.cli._resolve_socket_path") as mock_socket,
            patch("claude_code_hooks_daemon.daemon.cli._resolve_pid_path") as mock_pid,
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=123),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value={"error": "something broke"},
            ),
        ):
            mock_project.return_value = Path("/tmp/project")
            mock_socket.return_value = Path("/tmp/sock")
            mock_pid.return_value = Path("/tmp/pid")

            result = _get_current_mode(args)

        assert result is None


class TestPrintModeAdvisory:
    """Tests for _print_mode_advisory helper."""

    def test_prints_advisory_for_non_default_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Prints restore command when mode was non-default."""
        from claude_code_hooks_daemon.daemon.cli import _print_mode_advisory

        pre_mode = {
            ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
            ModeConstant.KEY_CUSTOM_MESSAGE: None,
        }

        _print_mode_advisory(pre_mode)

        captured = capsys.readouterr()
        assert "unattended" in captured.out
        assert "set-mode" in captured.out

    def test_prints_nothing_for_default_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Prints nothing when mode was default."""
        from claude_code_hooks_daemon.daemon.cli import _print_mode_advisory

        pre_mode = {
            ModeConstant.KEY_MODE: DaemonMode.DEFAULT.value,
            ModeConstant.KEY_CUSTOM_MESSAGE: None,
        }

        _print_mode_advisory(pre_mode)

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_includes_custom_message_in_restore_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Includes custom message in restore command."""
        from claude_code_hooks_daemon.daemon.cli import _print_mode_advisory

        pre_mode = {
            ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
            ModeConstant.KEY_CUSTOM_MESSAGE: "finish the release",
        }

        _print_mode_advisory(pre_mode)

        captured = capsys.readouterr()
        assert "finish the release" in captured.out
        assert "-m" in captured.out


class TestCmdRestartModeAdvisory:
    """Tests for cmd_restart mode advisory integration."""

    def test_restart_prints_advisory_when_non_default_mode(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """cmd_restart prints mode advisory when mode was non-default."""
        from claude_code_hooks_daemon.daemon.cli import cmd_restart

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.cmd_stop") as mock_stop,
            patch("claude_code_hooks_daemon.daemon.cli.cmd_start", return_value=0) as mock_start,
            patch("claude_code_hooks_daemon.daemon.cli.time.sleep"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._get_current_mode",
                return_value={
                    ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
                    ModeConstant.KEY_CUSTOM_MESSAGE: "testing",
                },
            ),
        ):
            result = cmd_restart(args)

        assert result == 0
        mock_stop.assert_called_once_with(args)
        mock_start.assert_called_once_with(args)
        captured = capsys.readouterr()
        assert "unattended" in captured.out

    def test_restart_no_advisory_when_default_mode(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """cmd_restart prints no advisory when mode was default."""
        from claude_code_hooks_daemon.daemon.cli import cmd_restart

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.cmd_stop"),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_start", return_value=0),
            patch("claude_code_hooks_daemon.daemon.cli.time.sleep"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._get_current_mode",
                return_value={
                    ModeConstant.KEY_MODE: DaemonMode.DEFAULT.value,
                    ModeConstant.KEY_CUSTOM_MESSAGE: None,
                },
            ),
        ):
            result = cmd_restart(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "set-mode" not in captured.out

    def test_restart_no_advisory_when_mode_query_fails(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """cmd_restart prints no advisory when mode query fails."""
        from claude_code_hooks_daemon.daemon.cli import cmd_restart

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.cmd_stop"),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_start", return_value=0),
            patch("claude_code_hooks_daemon.daemon.cli.time.sleep"),
            patch("claude_code_hooks_daemon.daemon.cli._get_current_mode", return_value=None),
        ):
            result = cmd_restart(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "set-mode" not in captured.out

    def test_restart_no_advisory_when_start_fails(self) -> None:
        """cmd_restart skips advisory when start fails."""
        from claude_code_hooks_daemon.daemon.cli import cmd_restart

        args = Mock()
        args.project_root = None

        with (
            patch("claude_code_hooks_daemon.daemon.cli.cmd_stop"),
            patch("claude_code_hooks_daemon.daemon.cli.cmd_start", return_value=1),
            patch("claude_code_hooks_daemon.daemon.cli.time.sleep"),
            patch(
                "claude_code_hooks_daemon.daemon.cli._get_current_mode",
                return_value={
                    ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
                    ModeConstant.KEY_CUSTOM_MESSAGE: None,
                },
            ),
        ):
            result = cmd_restart(args)

        assert result == 1
