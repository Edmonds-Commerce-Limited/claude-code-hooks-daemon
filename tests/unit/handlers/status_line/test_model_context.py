"""Tests for ModelContextHandler."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import ModelContextHandler


class TestModelContextHandler:
    """Tests for ModelContextHandler."""

    @pytest.fixture
    def handler(self) -> ModelContextHandler:
        """Create handler instance."""
        return ModelContextHandler()

    def test_handler_properties(self, handler: ModelContextHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-model-context"
        assert handler.priority == 10
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "display" in handler.tags

    def test_matches_always_returns_true(self, handler: ModelContextHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"model": {"display_name": "Claude"}}) is True

    def test_handle_with_full_data(self, handler: ModelContextHandler) -> None:
        """Test formatting with full model and context data."""
        hook_input = {
            "model": {"display_name": "Sonnet 4.5"},
            "context_window": {"used_percentage": 42.5},
        }

        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Sonnet 4.5" in result.context[0]
        assert "42.5%" in result.context[0]
        assert "🤖" in result.context[0]  # Robot emoji for model
        # Context is 42.5% which is 26-50% range, so should use ◑ (right half circle)
        assert "◑" in result.context[0]

    def test_handle_with_defaults(self, handler: ModelContextHandler) -> None:
        """Test formatting with missing data uses defaults."""
        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Claude" in result.context[0]
        assert "0.0%" in result.context[0]

    def test_color_coding_green(self, handler: ModelContextHandler) -> None:
        """Test green color for low usage (0-25%)."""
        hook_input = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 20.0},
        }

        result = handler.handle(hook_input)
        # Check for green background ANSI code (used for percentage at 0-25%)
        # Format: "\033[42m\033[30m" (green bg + black fg for percentage)
        assert "\033[42m" in result.context[0]
        # Should also have quarter circle icon ◔
        assert "◔" in result.context[0]

    def test_color_coding_yellow(self, handler: ModelContextHandler) -> None:
        """Test yellow color for moderate usage (41-60%)."""
        hook_input = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 50.0},
        }

        result = handler.handle(hook_input)
        # Check for yellow background ANSI code
        assert "\033[43m" in result.context[0]

    def test_color_coding_orange(self, handler: ModelContextHandler) -> None:
        """Test orange color for high usage (61-80%)."""
        hook_input = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 70.0},
        }

        result = handler.handle(hook_input)
        # Check for orange background ANSI code
        assert "\033[48;5;208m" in result.context[0]

    def test_color_coding_red(self, handler: ModelContextHandler) -> None:
        """Test red color for critical usage (81-100%)."""
        hook_input = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 90.0},
        }

        result = handler.handle(hook_input)
        # Check for red background ANSI code
        assert "\033[41m" in result.context[0]

    def test_color_reset_included(self, handler: ModelContextHandler) -> None:
        """Test that ANSI reset code is included."""
        hook_input = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 50.0},
        }

        result = handler.handle(hook_input)
        # Check for reset code
        assert "\033[0m" in result.context[0]

    def test_handle_with_null_used_percentage(self, handler: ModelContextHandler) -> None:
        """Test handling when used_percentage is None (fixes TypeError bug).

        Early in a session, Claude Code may send null for used_percentage.
        The handler must gracefully handle this and default to 0.0%.
        """
        hook_input = {
            "model": {"display_name": "Sonnet 4.5"},
            "context_window": {"used_percentage": None},
        }

        # Should not raise TypeError: '<=' not supported between NoneType and int
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Sonnet 4.5" in result.context[0]
        assert "0.0%" in result.context[0]
        # Should use green color (0% usage)
        assert "\033[42m" in result.context[0]

    def test_opus_shows_effort_bars_medium(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Opus model should show effort signal bars next to model name."""
        hook_input = {
            "model": {"display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings = {"effortLevel": "medium"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert len(result.context) == 1
        assert "Opus 4.6" in result.context[0]
        # Medium effort: first two bars lit in green, third dim
        assert "\033[32m▂▄" in result.context[0]

    def test_opus_shows_effort_bars_low_blue(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Low effort should show one bar lit in blue."""
        hook_input = {
            "model": {"display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings = {"effortLevel": "low"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        # Low effort: first bar lit in blue, remaining dim
        assert "\033[34m▂" in result.context[0]

    def test_opus_shows_effort_bars_high_orange(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """High effort should show all three bars lit in orange."""
        hook_input = {
            "model": {"display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings = {"effortLevel": "high"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        # High effort: all three bars lit in orange
        assert "\033[38;5;208m▂▄█" in result.context[0]

    def test_sonnet_shows_effort_bars(self, handler: ModelContextHandler, tmp_path: Path) -> None:
        """Sonnet model should also show effort bars (effort applies to all models)."""
        hook_input = {
            "model": {"display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings = {"effortLevel": "high"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        # Sonnet should now show effort bars too
        assert "Sonnet 4.6" in result.context[0]
        assert "\033[38;5;208m▂▄█" in result.context[0]

    def test_haiku_shows_effort_bars(self, handler: ModelContextHandler, tmp_path: Path) -> None:
        """Haiku model should also show effort bars."""
        hook_input = {
            "model": {"display_name": "Haiku 3.5"},
            "context_window": {"used_percentage": 10.0},
        }
        settings = {"effortLevel": "medium"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "Haiku 3.5" in result.context[0]
        assert "\033[32m▂▄" in result.context[0]

    def test_no_effort_when_not_set(self, handler: ModelContextHandler, tmp_path: Path) -> None:
        """Should not show effort bars when effortLevel is not set in settings."""
        hook_input = {
            "model": {"display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings = {"alwaysThinkingEnabled": True}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "Opus 4.6" in result.context[0]
        # No effort bars present
        assert "▂" not in result.context[0]

    def test_no_effort_when_settings_missing(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Should handle missing settings file gracefully - no bars shown."""
        hook_input = {
            "model": {"display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "Opus 4.6" in result.context[0]
        assert len(result.context) == 1
        assert "▂" not in result.context[0]
