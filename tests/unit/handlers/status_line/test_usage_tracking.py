"""Tests for UsageTrackingHandler."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import UsageTrackingHandler


class TestUsageTrackingHandler:
    """Tests for UsageTrackingHandler."""

    @pytest.fixture
    def handler(self) -> UsageTrackingHandler:
        """Create handler instance."""
        return UsageTrackingHandler()

    def test_handler_properties(self, handler: UsageTrackingHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-usage-tracking"
        assert handler.priority == 15
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "display" in handler.tags

    def test_matches_always_returns_true(self, handler: UsageTrackingHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"model": {"id": "test"}}) is True

    def test_handle_with_valid_stats_and_model(self, handler: UsageTrackingHandler) -> None:
        """Test formatting with valid stats cache and model."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {
                    "date": today,
                    "tokensByModel": {
                        "claude-sonnet-4-5-20250929": 50000,  # 25% of 200k
                    },
                }
            ]
        }

        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)):
                result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        # Daily: 25% (50k/200k), Weekly: ~3.6% (50k/1400k)
        # Output includes ANSI color codes
        assert "daily:" in result.context[0]
        assert "25.0%" in result.context[0]
        assert "weekly:" in result.context[0]

    def test_handle_with_missing_stats_file(self, handler: UsageTrackingHandler) -> None:
        """Test handling when stats-cache.json doesn't exist."""
        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        with patch("pathlib.Path.exists", return_value=False):
            result = handler.handle(hook_input)

        # Should return empty context (silent fail)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_missing_model_id(self, handler: UsageTrackingHandler) -> None:
        """Test handling when model ID is not in hook_input."""
        hook_input = {}  # No model data

        result = handler.handle(hook_input)

        # Should return empty context (silent fail)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_unknown_model(self, handler: UsageTrackingHandler) -> None:
        """Test handling with model not in DAILY_LIMITS."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [{"date": today, "tokensByModel": {"unknown-model": 50000}}]
        }

        hook_input = {
            "model": {
                "id": "unknown-model",
            }
        }

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)):
                result = handler.handle(hook_input)

        # Unknown model = no display
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_zero_usage(self, handler: UsageTrackingHandler) -> None:
        """Test formatting when usage is 0%."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {"date": today, "tokensByModel": {"claude-sonnet-4-5-20250929": 0}}
            ]
        }

        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)):
                result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert "daily:" in result.context[0]
        assert "0.0%" in result.context[0]
        assert "weekly:" in result.context[0]

    def test_handle_with_high_usage(self, handler: UsageTrackingHandler) -> None:
        """Test formatting with high usage percentages includes red color."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {
                    "date": today,
                    "tokensByModel": {
                        "claude-sonnet-4-5-20250929": 180000,  # 90% of 200k
                    },
                }
            ]
        }

        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)):
                result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert "daily:" in result.context[0]
        assert "90.0%" in result.context[0]
        # Should have red color for >80% usage
        assert "\033[41m" in result.context[0]  # Red background

    def test_handle_with_options_show_daily_only(self, handler: UsageTrackingHandler) -> None:
        """Test with options to show only daily usage."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {"date": today, "tokensByModel": {"claude-sonnet-4-5-20250929": 50000}}
            ]
        }

        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        # Override handler options
        handler._options = {"show_daily": True, "show_weekly": False}

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)):
                result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert "daily:" in result.context[0]
        assert "weekly:" not in result.context[0]

    def test_handle_with_options_show_weekly_only(self, handler: UsageTrackingHandler) -> None:
        """Test with options to show only weekly usage."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {"date": today, "tokensByModel": {"claude-sonnet-4-5-20250929": 50000}}
            ]
        }

        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        # Override handler options
        handler._options = {"show_daily": False, "show_weekly": True}

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)):
                result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert "daily:" not in result.context[0]
        assert "weekly:" in result.context[0]

    def test_handle_with_opus_model(self, handler: UsageTrackingHandler) -> None:
        """Test with Opus model (100k daily limit)."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {
                    "date": today,
                    "tokensByModel": {
                        "claude-opus-4-5-20251101": 30000,  # 30% of 100k
                    },
                }
            ]
        }

        hook_input = {
            "model": {
                "id": "claude-opus-4-5-20251101",
            }
        }

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)):
                result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert "daily:" in result.context[0]
        assert "30.0%" in result.context[0]

    def test_handle_reads_file_every_time(self, handler: UsageTrackingHandler) -> None:
        """Test that file is read on every call (no TTL caching)."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {"date": today, "tokensByModel": {"claude-sonnet-4-5-20250929": 50000}}
            ]
        }

        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        with patch("pathlib.Path.exists", return_value=True) as mock_exists:
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)) as mock_read:
                # First call
                result1 = handler.handle(hook_input)
                # Second call - should read file again (no caching)
                result2 = handler.handle(hook_input)

        # File should be read twice (no TTL cache)
        assert mock_read.call_count == 2
        # Results should be the same
        assert result1.context == result2.context

    def test_handle_with_both_daily_weekly_disabled(self, handler: UsageTrackingHandler) -> None:
        """Test with both daily and weekly disabled returns empty context."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {"date": today, "tokensByModel": {"claude-sonnet-4-5-20250929": 50000}}
            ]
        }

        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        # Disable both options
        handler._options = {"show_daily": False, "show_weekly": False}

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json.dumps(cache_data)):
                result = handler.handle(hook_input)

        # Should return empty context (no parts to display)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_with_exception(self, handler: UsageTrackingHandler) -> None:
        """Test exception handling returns empty context."""
        hook_input = {
            "model": {
                "id": "claude-sonnet-4-5-20250929",
            }
        }

        # Simulate exception during file read
        with patch("pathlib.Path.exists", side_effect=RuntimeError("Simulated error")):
            result = handler.handle(hook_input)

        # Should silently fail with empty context
        assert result.decision == "allow"
        assert result.context == []

    def test_colorize_percentage_yellow(self, handler: UsageTrackingHandler) -> None:
        """Test yellow color for 41-60% usage."""
        result = handler._colorize_percentage(50.0)
        # Should have yellow color
        assert "\033[43m" in result  # Yellow background
        assert "50.0%" in result

    def test_colorize_percentage_orange(self, handler: UsageTrackingHandler) -> None:
        """Test orange color for 61-80% usage."""
        result = handler._colorize_percentage(70.0)
        # Should have orange color
        assert "\033[48;5;208m" in result  # Orange background
        assert "70.0%" in result
