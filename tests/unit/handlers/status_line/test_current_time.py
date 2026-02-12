"""Tests for CurrentTimeHandler."""

from datetime import datetime
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.status_line.current_time import CurrentTimeHandler


class TestCurrentTimeHandler:
    """Test suite for CurrentTimeHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return CurrentTimeHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'status-current-time'."""
        assert handler.name == "status-current-time"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 14."""
        assert handler.priority == 14

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should not be terminal."""
        assert handler.terminal is False

    # matches() Tests
    def test_matches_status_line_event(self, handler):
        """Should always match (returns True for all inputs)."""
        hook_input = {"event": "STATUS_LINE"}
        assert handler.matches(hook_input) is True

    def test_matches_returns_true_for_any_event(self, handler):
        """Should match any event (status line handlers always run)."""
        hook_input = {"event": "PRE_TOOL_USE"}
        assert handler.matches(hook_input) is True

    def test_matches_returns_true_for_empty_input(self, handler):
        """Should match even with empty input."""
        hook_input = {}
        assert handler.matches(hook_input) is True

    # handle() Tests
    @patch("claude_code_hooks_daemon.handlers.status_line.current_time.datetime")
    def test_handle_returns_current_time_24h_format(self, mock_datetime, handler):
        """Should return current time in 24-hour format without seconds."""
        # Mock datetime.now() to return specific time
        mock_now = datetime(2026, 2, 12, 14, 23, 45)
        mock_datetime.now.return_value = mock_now

        hook_input = {}
        result = handler.handle(hook_input)

        assert result.context == ["| 🕐 14:23"]

    @patch("claude_code_hooks_daemon.handlers.status_line.current_time.datetime")
    def test_handle_formats_single_digit_minutes(self, mock_datetime, handler):
        """Should zero-pad single digit minutes."""
        mock_now = datetime(2026, 2, 12, 9, 5, 30)
        mock_datetime.now.return_value = mock_now

        hook_input = {}
        result = handler.handle(hook_input)

        assert result.context == ["| 🕐 09:05"]

    @patch("claude_code_hooks_daemon.handlers.status_line.current_time.datetime")
    def test_handle_shows_midnight_correctly(self, mock_datetime, handler):
        """Should show midnight as 00:00."""
        mock_now = datetime(2026, 2, 12, 0, 0, 0)
        mock_datetime.now.return_value = mock_now

        hook_input = {}
        result = handler.handle(hook_input)

        assert result.context == ["| 🕐 00:00"]

    @patch("claude_code_hooks_daemon.handlers.status_line.current_time.datetime")
    def test_handle_shows_noon_correctly(self, mock_datetime, handler):
        """Should show noon as 12:00."""
        mock_now = datetime(2026, 2, 12, 12, 0, 0)
        mock_datetime.now.return_value = mock_now

        hook_input = {}
        result = handler.handle(hook_input)

        assert result.context == ["| 🕐 12:00"]

    def test_handle_returns_context_list(self, handler):
        """Handler should return context as a list."""
        hook_input = {}
        result = handler.handle(hook_input)
        assert isinstance(result.context, list)
        assert len(result.context) == 1
        assert result.context[0].startswith("| 🕐 ")

    def test_handle_guidance_is_none(self, handler):
        """Handler should not set guidance."""
        hook_input = {"event": "STATUS_LINE"}
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_reason_is_none(self, handler):
        """Handler should not set reason."""
        hook_input = {"event": "STATUS_LINE"}
        result = handler.handle(hook_input)
        assert result.reason is None
