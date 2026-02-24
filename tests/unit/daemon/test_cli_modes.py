"""Tests for CLI mode commands (get-mode, set-mode)."""

from unittest.mock import Mock, patch

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
