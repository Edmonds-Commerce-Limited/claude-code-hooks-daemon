"""Tests for input validation integration in HooksDaemon server.

Tests validation at the front controller layer (server.py _process_request).
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.config.models import DaemonConfig, InputValidationConfig
from claude_code_hooks_daemon.daemon.server import HooksDaemon


@pytest.fixture
def mock_controller():
    """Mock controller for testing."""
    controller = MagicMock()
    controller.dispatch = MagicMock(return_value=MagicMock(to_json=lambda x: {}))
    return controller


@pytest.fixture
def daemon_config_validation_enabled():
    """Config with validation enabled (default)."""
    config = DaemonConfig()
    config.socket_path = "/tmp/test.sock"
    config.pid_file_path = "/tmp/test.pid"
    assert config.input_validation.enabled is True
    assert config.input_validation.strict_mode is False
    return config


@pytest.fixture
def daemon_config_validation_disabled():
    """Config with validation disabled."""
    config = DaemonConfig()
    config.socket_path = "/tmp/test.sock"
    config.pid_file_path = "/tmp/test.pid"
    config.input_validation = InputValidationConfig(enabled=False)
    return config


@pytest.fixture
def daemon_config_strict_mode():
    """Config with strict validation mode."""
    config = DaemonConfig()
    config.socket_path = "/tmp/test.sock"
    config.pid_file_path = "/tmp/test.pid"
    config.input_validation = InputValidationConfig(enabled=True, strict_mode=True)
    return config


class TestValidationConfigChecks:
    """Test validation configuration checking methods."""

    def test_should_validate_enabled_by_default(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Validation is enabled by default."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)
        assert daemon._should_validate_input() is True

    def test_should_validate_disabled_by_config(
        self, mock_controller, daemon_config_validation_disabled
    ):
        """Validation can be disabled via config."""
        daemon = HooksDaemon(daemon_config_validation_disabled, mock_controller)
        assert daemon._should_validate_input() is False

    def test_env_var_overrides_config_enabled(
        self, mock_controller, daemon_config_validation_disabled
    ):
        """HOOKS_DAEMON_INPUT_VALIDATION=true overrides config."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_INPUT_VALIDATION": "true"}):
            daemon = HooksDaemon(daemon_config_validation_disabled, mock_controller)
            assert daemon._should_validate_input() is True

    def test_env_var_overrides_config_disabled(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """HOOKS_DAEMON_INPUT_VALIDATION=false overrides config."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_INPUT_VALIDATION": "false"}):
            daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)
            assert daemon._should_validate_input() is False

    def test_env_var_accepts_various_true_values(
        self, mock_controller, daemon_config_validation_disabled
    ):
        """Env var accepts true/1/yes as true values."""
        for value in ["true", "True", "TRUE", "1", "yes", "Yes", "YES"]:
            with patch.dict(os.environ, {"HOOKS_DAEMON_INPUT_VALIDATION": value}):
                daemon = HooksDaemon(daemon_config_validation_disabled, mock_controller)
                assert daemon._should_validate_input() is True, f"Failed for value: {value}"

    def test_strict_mode_disabled_by_default(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Strict mode is disabled by default (fail-open)."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)
        assert daemon._is_strict_validation() is False

    def test_strict_mode_enabled_by_config(self, mock_controller, daemon_config_strict_mode):
        """Strict mode can be enabled via config."""
        daemon = HooksDaemon(daemon_config_strict_mode, mock_controller)
        assert daemon._is_strict_validation() is True

    def test_strict_mode_env_var_overrides_config(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """HOOKS_DAEMON_VALIDATION_STRICT env var overrides config."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_VALIDATION_STRICT": "true"}):
            daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)
            assert daemon._is_strict_validation() is True


class TestValidationMethods:
    """Test validation helper methods."""

    def test_get_input_validator_caches_validators(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Validators are cached per event type."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)

        # First call creates validator
        validator1 = daemon._get_input_validator("PreToolUse")
        assert validator1 is not None
        assert "PreToolUse" in daemon._input_validators

        # Second call returns cached validator
        validator2 = daemon._get_input_validator("PreToolUse")
        assert validator2 is validator1

    def test_get_input_validator_returns_none_for_unknown_event(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Unknown event types return None."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)
        validator = daemon._get_input_validator("UnknownEvent")
        assert validator is None

    def test_validate_hook_input_unknown_event(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Validation returns empty list for unknown event types."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)
        errors = daemon._validate_hook_input("UnknownEvent", {"foo": "bar"})
        assert errors == []

    def test_validate_hook_input_valid_event(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Valid hook_input passes validation."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)

        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }

        errors = daemon._validate_hook_input("PreToolUse", hook_input)
        assert errors == []

    def test_validate_hook_input_invalid_event(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Invalid hook_input fails validation."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)

        hook_input = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_output": {"stdout": "output"},  # WRONG FIELD!
        }

        errors = daemon._validate_hook_input("PostToolUse", hook_input)
        assert len(errors) > 0
        # Should fail because tool_response is required

    def test_validation_error_response_format(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Validation error response has correct format."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)

        errors = ["field1: missing", "field2: invalid type"]
        response = daemon._validation_error_response("PostToolUse", errors, "req-123")

        assert response["error"] == "input_validation_failed"
        assert response["details"] == errors
        assert response["event_type"] == "PostToolUse"
        assert response["request_id"] == "req-123"


class TestProcessRequestValidation:
    """Test validation integration in _process_request."""

    @pytest.mark.anyio
    async def test_valid_event_passes_validation(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Valid event passes validation and is processed."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)

        request = json.dumps(
            {
                "event": "PreToolUse",
                "hook_input": {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                },
            }
        )

        response = await daemon._process_request(request)

        # Should not have validation error
        assert response.get("error") != "input_validation_failed"
        # Should have result (processed by controller)
        assert "result" in response or "error" not in response

    @pytest.mark.anyio
    async def test_invalid_event_logged_in_fail_open_mode(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """Invalid event is logged but processed in fail-open mode."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)

        request = json.dumps(
            {
                "event": "PostToolUse",
                "hook_input": {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_output": {"stdout": "output"},  # WRONG FIELD!
                },
            }
        )

        with patch("claude_code_hooks_daemon.daemon.server.logger") as mock_logger:
            response = await daemon._process_request(request)

            # Should log warning
            mock_logger.warning.assert_called()
            warning_call = mock_logger.warning.call_args
            assert warning_call is not None
            assert "Input validation failed" in str(warning_call)
            assert "PostToolUse" in str(warning_call)

            # Should still process (fail-open)
            assert response.get("error") != "input_validation_failed"

    @pytest.mark.anyio
    async def test_invalid_event_blocked_in_strict_mode(
        self, mock_controller, daemon_config_strict_mode
    ):
        """Invalid event returns error in strict mode."""
        daemon = HooksDaemon(daemon_config_strict_mode, mock_controller)

        request = json.dumps(
            {
                "event": "PostToolUse",
                "hook_input": {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_output": {"stdout": "output"},  # WRONG FIELD!
                },
            }
        )

        with patch("claude_code_hooks_daemon.daemon.server.logger") as mock_logger:
            response = await daemon._process_request(request)

            # Should log error
            mock_logger.error.assert_called()
            error_call = mock_logger.error.call_args[0]
            assert "Input validation failed" in error_call[0]
            assert "strict mode" in error_call[0]

            # Should return error
            assert response["error"] == "input_validation_failed"
            assert "details" in response
            assert response["event_type"] == "PostToolUse"

            # Controller should NOT be called
            mock_controller.dispatch.assert_not_called()

    @pytest.mark.anyio
    async def test_validation_disabled_skips_check(
        self, mock_controller, daemon_config_validation_disabled
    ):
        """Validation is skipped when disabled."""
        daemon = HooksDaemon(daemon_config_validation_disabled, mock_controller)

        request = json.dumps(
            {
                "event": "PostToolUse",
                "hook_input": {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_output": {"stdout": "output"},  # WRONG but validation disabled
                },
            }
        )

        # With validation disabled, malformed input should still be processed
        response = await daemon._process_request(request)

        # Should process normally (validation disabled)
        assert "result" in response or "error" not in response

    @pytest.mark.anyio
    async def test_system_events_skip_validation(
        self, mock_controller, daemon_config_validation_enabled
    ):
        """System events (_system) skip validation."""
        daemon = HooksDaemon(daemon_config_validation_enabled, mock_controller)

        request = json.dumps(
            {
                "event": "_system",
                "hook_input": {"action": "get_logs"},
            }
        )

        response = await daemon._process_request(request)

        # System events are handled directly, not dispatched to controller
        # Should not have validation error
        assert response.get("error") != "input_validation_failed"


class TestRealWorldScenarios:
    """Test validation with real-world event structures."""

    @pytest.mark.anyio
    async def test_catches_tool_output_vs_tool_response_bug(
        self, mock_controller, daemon_config_strict_mode
    ):
        """Catches the actual bug: tool_output instead of tool_response."""
        daemon = HooksDaemon(daemon_config_strict_mode, mock_controller)

        # Simulates broken BashErrorDetectorHandler test fixture
        request = json.dumps(
            {
                "event": "PostToolUse",
                "hook_input": {
                    "tool_name": "Bash",
                    "tool_output": {  # BUG: should be tool_response
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "error",
                    },
                },
            }
        )

        response = await daemon._process_request(request)

        # Should catch the bug
        assert response["error"] == "input_validation_failed"
        assert any("tool_response" in detail for detail in response["details"])

    @pytest.mark.anyio
    async def test_catches_permission_type_vs_permission_suggestions_bug(
        self, mock_controller, daemon_config_strict_mode
    ):
        """Catches the actual bug: permission_type instead of permission_suggestions."""
        daemon = HooksDaemon(daemon_config_strict_mode, mock_controller)

        # Simulates broken AutoApproveReadsHandler structure
        request = json.dumps(
            {
                "event": "PermissionRequest",
                "hook_input": {
                    "tool_name": "Read",
                    "permission_type": "read",  # BUG: should be permission_suggestions
                    "resource": "test.txt",
                },
            }
        )

        response = await daemon._process_request(request)

        # Should catch the bug
        assert response["error"] == "input_validation_failed"
        assert any("permission_suggestions" in detail for detail in response["details"])

    @pytest.mark.anyio
    async def test_catches_severity_vs_notification_type_bug(
        self, mock_controller, daemon_config_strict_mode
    ):
        """Catches the actual bug: severity instead of notification_type."""
        daemon = HooksDaemon(daemon_config_strict_mode, mock_controller)

        # Simulates broken NotificationLoggerHandler test fixture
        request = json.dumps(
            {
                "event": "Notification",
                "hook_input": {
                    "severity": "warning",  # BUG: should be notification_type
                    "message": "Test notification",
                },
            }
        )

        response = await daemon._process_request(request)

        # Should catch the bug
        assert response["error"] == "input_validation_failed"
        assert any("notification_type" in detail for detail in response["details"])
