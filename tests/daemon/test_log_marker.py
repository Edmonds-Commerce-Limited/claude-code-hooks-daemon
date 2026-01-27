"""Tests for log_marker system action in daemon server."""

import json
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.daemon.server import HooksDaemon


class TestLogMarker:
    """Test log_marker system action."""

    def test_log_marker_action_logs_message(self) -> None:
        """Test that log_marker action logs the provided message."""
        # Create daemon instance with minimal config
        config = MagicMock()
        config.socket_path = "/tmp/test.sock"
        config.pid_file_path = None
        config.idle_timeout_seconds = 600
        config.log_level = "INFO"

        daemon = HooksDaemon(controller=MagicMock(), config=config)

        # Mock logger
        with patch("claude_code_hooks_daemon.daemon.server.logger") as mock_logger:
            # Call _handle_system_request with log_marker action
            request = {"action": "log_marker", "message": "TEST MARKER"}
            response = daemon._handle_system_request(request, request_id="test-123")

            # Verify logger was called with formatted message
            mock_logger.info.assert_called_once_with("=== TEST MARKER ===")

            # Verify response
            assert response == {
                "result": {"status": "logged", "message": "TEST MARKER"},
                "request_id": "test-123",
            }

    def test_log_marker_action_with_default_message(self) -> None:
        """Test that log_marker uses default message if none provided."""
        config = MagicMock()
        config.socket_path = "/tmp/test.sock"
        config.pid_file_path = None
        config.idle_timeout_seconds = 600
        config.log_level = "INFO"

        daemon = HooksDaemon(controller=MagicMock(), config=config)

        with patch("claude_code_hooks_daemon.daemon.server.logger") as mock_logger:
            request = {"action": "log_marker"}
            response = daemon._handle_system_request(request, request_id=None)

            mock_logger.info.assert_called_once_with("=== MARKER ===")
            assert response == {"result": {"status": "logged", "message": "MARKER"}}

    def test_log_marker_action_with_empty_message(self) -> None:
        """Test that log_marker handles empty message string."""
        config = MagicMock()
        config.socket_path = "/tmp/test.sock"
        config.pid_file_path = None
        config.idle_timeout_seconds = 600
        config.log_level = "INFO"

        daemon = HooksDaemon(controller=MagicMock(), config=config)

        with patch("claude_code_hooks_daemon.daemon.server.logger") as mock_logger:
            request = {"action": "log_marker", "message": ""}
            response = daemon._handle_system_request(request, request_id=None)

            # Empty string should still be logged (formatted with ===)
            mock_logger.info.assert_called_once_with("===  ===")
            assert response == {"result": {"status": "logged", "message": ""}}

    def test_log_marker_in_full_request_flow(self) -> None:
        """Test log_marker through full _handle_request flow."""
        config = MagicMock()
        config.socket_path = "/tmp/test.sock"
        config.pid_file_path = None
        config.idle_timeout_seconds = 600
        config.log_level = "INFO"

        daemon = HooksDaemon(controller=MagicMock(), config=config)

        with patch("claude_code_hooks_daemon.daemon.server.logger") as mock_logger:
            # Simulate full request with _system event
            request_data = {
                "event": "_system",
                "hook_input": {"action": "log_marker", "message": "START BOUNDARY: Test"},
                "request_id": "req-456",
            }

            # This would normally be called by handle_request (async)
            # but we can test _handle_system_request directly
            response = daemon._handle_system_request(
                request_data["hook_input"], request_data["request_id"]
            )

            mock_logger.info.assert_called_once_with("=== START BOUNDARY: Test ===")
            assert response["result"]["status"] == "logged"
            assert response["request_id"] == "req-456"
