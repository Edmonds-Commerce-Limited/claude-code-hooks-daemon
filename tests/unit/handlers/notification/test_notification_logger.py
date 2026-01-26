"""Comprehensive tests for NotificationLoggerHandler."""

import json
from unittest.mock import mock_open, patch

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.notification.notification_logger import (
    NotificationLoggerHandler,
)


class TestNotificationLoggerHandler:
    """Test suite for NotificationLoggerHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return NotificationLoggerHandler()

    @pytest.fixture
    def mock_datetime(self):
        """Mock datetime.now() to return fixed timestamp."""
        with patch(
            "claude_code_hooks_daemon.handlers.notification.notification_logger.datetime"
        ) as mock_dt:
            mock_dt.now.return_value.isoformat.return_value = "2024-01-20T10:30:00"
            yield mock_dt

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'notification-logger'."""
        assert handler.name == "notification-logger"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 100."""
        assert handler.priority == 100

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal (logging only)."""
        assert handler.terminal is False

    # matches() Tests
    def test_matches_always_returns_true(self, handler):
        """Should match all notification events."""
        hook_input = {
            "message": "Test notification",
            "severity": "info",
        }
        assert handler.matches(hook_input) is True

    def test_matches_empty_input_returns_true(self, handler):
        """Should match even empty input."""
        hook_input = {}
        assert handler.matches(hook_input) is True

    # handle() Tests
    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_creates_log_directory(self, mock_mkdir, mock_file, handler, mock_datetime):
        """Should create log directory if it doesn't exist."""
        hook_input = {"message": "Test"}
        handler.handle(hook_input)

        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_writes_json_log_entry(self, mock_mkdir, mock_file, handler, mock_datetime):
        """Should write JSON log entry to file."""
        hook_input = {
            "message": "Build complete",
            "severity": "info",
        }

        handler.handle(hook_input)

        # Check file was opened in append mode
        assert mock_file.called
        # Check JSON write was attempted (file handle write was called)
        handle = mock_file()
        assert handle.write.called

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_includes_all_notification_fields(
        self, mock_mkdir, mock_file, handler, mock_datetime
    ):
        """Should include all fields from notification in log."""
        hook_input = {
            "message": "Error occurred",
            "severity": "error",
            "code": "E500",
            "details": {"line": 42},
        }

        handler.handle(hook_input)

        handle = mock_file()
        written_data = "".join(call.args[0] for call in handle.write.call_args_list)
        log_entry = json.loads(written_data.strip())

        assert log_entry["message"] == "Error occurred"
        assert log_entry["severity"] == "error"
        assert log_entry["code"] == "E500"
        assert log_entry["details"] == {"line": 42}

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_returns_allow_decision(self, mock_mkdir, mock_file, handler):
        """Should return allow decision (non-blocking)."""
        hook_input = {"message": "Test"}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_has_no_reason(self, mock_mkdir, mock_file, handler):
        """Should not provide reason."""
        hook_input = {"message": "Test"}
        result = handler.handle(hook_input)
        assert result.reason is None

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_has_no_context(self, mock_mkdir, mock_file, handler):
        """Should not provide context (empty list)."""
        hook_input = {"message": "Test"}
        result = handler.handle(hook_input)
        assert result.context == []

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_has_no_guidance(self, mock_mkdir, mock_file, handler):
        """Should not provide guidance."""
        hook_input = {"message": "Test"}
        result = handler.handle(hook_input)
        assert result.guidance is None

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_returns_hook_result_instance(self, mock_mkdir, mock_file, handler):
        """Should return HookResult instance."""
        hook_input = {"message": "Test"}
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)

    # Error Handling Tests
    @patch("pathlib.Path.open", side_effect=OSError("Permission denied"))
    @patch("pathlib.Path.mkdir")
    def test_handle_gracefully_handles_write_errors(self, mock_mkdir, mock_file, handler):
        """Should handle file write errors gracefully."""
        hook_input = {"message": "Test"}

        # Should not raise exception
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_empty_notification(self, mock_mkdir, mock_file, handler, mock_datetime):
        """Should handle empty notification gracefully."""
        hook_input = {}
        result = handler.handle(hook_input)

        # Should still write log entry with timestamp
        handle = mock_file()
        written_data = "".join(call.args[0] for call in handle.write.call_args_list)
        log_entry = json.loads(written_data.strip())

        assert log_entry["timestamp"] == "2024-01-20T10:30:00"
        assert result.decision == "allow"
