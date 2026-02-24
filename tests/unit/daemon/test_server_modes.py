"""Tests for daemon server mode IPC actions."""

from typing import Any
from unittest.mock import Mock

from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant


class TestServerGetModeAction:
    """Tests for get_mode system action."""

    def test_get_mode_returns_default(self) -> None:
        """get_mode action returns current mode."""
        from claude_code_hooks_daemon.daemon.server import HooksDaemon

        config = Mock()
        config.idle_timeout_seconds = 600
        config.log_level = "INFO"
        config.request_timeout_seconds = 30
        config.pid_file_path_obj = None
        config.input_validation = Mock()
        config.input_validation.enabled = False
        config.strict_mode = False
        config.enforce_single_daemon_process = False

        # Create a mock controller with get_mode/set_mode
        controller = Mock()
        controller.get_mode.return_value = {
            ModeConstant.KEY_MODE: DaemonMode.DEFAULT.value,
            ModeConstant.KEY_CUSTOM_MESSAGE: None,
        }

        server = HooksDaemon.__new__(HooksDaemon)
        server.config = config
        server.controller = controller
        server._is_new_controller = True

        response = server._handle_system_request({"action": ModeConstant.ACTION_GET_MODE}, None)

        assert "result" in response
        assert response["result"][ModeConstant.KEY_MODE] == DaemonMode.DEFAULT.value

    def test_get_mode_returns_unattended(self) -> None:
        """get_mode returns unattended when set."""
        from claude_code_hooks_daemon.daemon.server import HooksDaemon

        config = Mock()
        config.idle_timeout_seconds = 600
        config.input_validation = Mock()
        config.input_validation.enabled = False
        config.strict_mode = False
        config.enforce_single_daemon_process = False

        controller = Mock()
        controller.get_mode.return_value = {
            ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
            ModeConstant.KEY_CUSTOM_MESSAGE: "finish tasks",
        }

        server = HooksDaemon.__new__(HooksDaemon)
        server.config = config
        server.controller = controller
        server._is_new_controller = True

        response = server._handle_system_request({"action": ModeConstant.ACTION_GET_MODE}, None)

        assert response["result"][ModeConstant.KEY_MODE] == DaemonMode.UNATTENDED.value
        assert response["result"][ModeConstant.KEY_CUSTOM_MESSAGE] == "finish tasks"

    def test_get_mode_with_request_id(self) -> None:
        """get_mode passes through request_id."""
        from claude_code_hooks_daemon.daemon.server import HooksDaemon

        config = Mock()
        config.idle_timeout_seconds = 600
        config.input_validation = Mock()
        config.input_validation.enabled = False
        config.strict_mode = False
        config.enforce_single_daemon_process = False

        controller = Mock()
        controller.get_mode.return_value = {
            ModeConstant.KEY_MODE: DaemonMode.DEFAULT.value,
            ModeConstant.KEY_CUSTOM_MESSAGE: None,
        }

        server = HooksDaemon.__new__(HooksDaemon)
        server.config = config
        server.controller = controller
        server._is_new_controller = True

        response = server._handle_system_request(
            {"action": ModeConstant.ACTION_GET_MODE}, "req-123"
        )

        assert response["request_id"] == "req-123"


class TestServerSetModeAction:
    """Tests for set_mode system action."""

    def _make_server(self) -> Any:
        """Create minimal server with mock controller."""
        from claude_code_hooks_daemon.daemon.server import HooksDaemon

        config = Mock()
        config.idle_timeout_seconds = 600
        config.input_validation = Mock()
        config.input_validation.enabled = False
        config.strict_mode = False
        config.enforce_single_daemon_process = False

        controller = Mock()
        controller.set_mode.return_value = True
        controller.get_mode.return_value = {
            ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
            ModeConstant.KEY_CUSTOM_MESSAGE: None,
        }

        server = HooksDaemon.__new__(HooksDaemon)
        server.config = config
        server.controller = controller
        server._is_new_controller = True
        return server

    def test_set_mode_unattended(self) -> None:
        """set_mode changes to unattended."""
        server = self._make_server()

        response = server._handle_system_request(
            {
                "action": ModeConstant.ACTION_SET_MODE,
                ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
            },
            None,
        )

        assert "result" in response
        assert response["result"][ModeConstant.KEY_STATUS] == ModeConstant.STATUS_CHANGED
        server.controller.set_mode.assert_called_once_with(
            DaemonMode.UNATTENDED, custom_message=None
        )

    def test_set_mode_with_custom_message(self) -> None:
        """set_mode passes custom_message."""
        server = self._make_server()

        response = server._handle_system_request(
            {
                "action": ModeConstant.ACTION_SET_MODE,
                ModeConstant.KEY_MODE: DaemonMode.UNATTENDED.value,
                ModeConstant.KEY_CUSTOM_MESSAGE: "finish release",
            },
            None,
        )

        server.controller.set_mode.assert_called_once_with(
            DaemonMode.UNATTENDED, custom_message="finish release"
        )

    def test_set_mode_unchanged(self) -> None:
        """set_mode returns unchanged status when mode didn't change."""
        server = self._make_server()
        server.controller.set_mode.return_value = False

        response = server._handle_system_request(
            {
                "action": ModeConstant.ACTION_SET_MODE,
                ModeConstant.KEY_MODE: DaemonMode.DEFAULT.value,
            },
            None,
        )

        assert response["result"][ModeConstant.KEY_STATUS] == ModeConstant.STATUS_UNCHANGED

    def test_set_mode_invalid_mode(self) -> None:
        """set_mode returns error for invalid mode."""
        server = self._make_server()

        response = server._handle_system_request(
            {
                "action": ModeConstant.ACTION_SET_MODE,
                ModeConstant.KEY_MODE: "bogus_mode",
            },
            None,
        )

        assert "error" in response
        assert "Invalid mode" in response["error"]

    def test_set_mode_missing_mode(self) -> None:
        """set_mode returns error when mode field is missing."""
        server = self._make_server()

        response = server._handle_system_request(
            {"action": ModeConstant.ACTION_SET_MODE},
            None,
        )

        assert "error" in response
