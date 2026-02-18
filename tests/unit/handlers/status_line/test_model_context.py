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
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 42.5},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Sonnet 4.6" in result.context[0]
        assert "42.5%" in result.context[0]
        assert "🤖" in result.context[0]
        assert "◑" in result.context[0]

    def test_handle_with_defaults(self, handler: ModelContextHandler) -> None:
        """Test formatting with missing data uses defaults."""
        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Claude" in result.context[0]
        assert "0.0%" in result.context[0]

    def test_color_coding_green(self, handler: ModelContextHandler) -> None:
        """Test green color for low usage (0-25%)."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 20.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[42m" in result.context[0]
        assert "◔" in result.context[0]

    def test_color_coding_yellow(self, handler: ModelContextHandler) -> None:
        """Test yellow color for moderate usage (41-60%)."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 50.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[43m" in result.context[0]

    def test_color_coding_orange(self, handler: ModelContextHandler) -> None:
        """Test orange color for high usage (61-80%)."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 70.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[48;5;208m" in result.context[0]

    def test_color_coding_red(self, handler: ModelContextHandler) -> None:
        """Test red color for critical usage (81-100%)."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 90.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[41m" in result.context[0]

    def test_color_reset_included(self, handler: ModelContextHandler) -> None:
        """Test that ANSI reset code is included."""
        hook_input = {
            "model": {"id": "", "display_name": "Claude"},
            "context_window": {"used_percentage": 50.0},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert "\033[0m" in result.context[0]

    def test_handle_with_null_used_percentage(self, handler: ModelContextHandler) -> None:
        """Test handling when used_percentage is None (fixes TypeError bug).

        Early in a session, Claude Code may send null for used_percentage.
        """
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": None},
        }

        with patch.object(handler, "_get_settings_path", return_value=Path("/nonexistent")):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert "Sonnet 4.6" in result.context[0]
        assert "0.0%" in result.context[0]
        assert "\033[42m" in result.context[0]

    # --- Effort bars: explicit settings ---

    def test_explicit_medium_effort_shows_two_bars(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Explicitly set medium effort shows two orange bars, one dim."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "medium"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌" in result.context[0]

    def test_explicit_low_effort_shows_one_bar(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Explicitly set low effort shows one orange bar, two dim."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "low"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌" in result.context[0]

    def test_explicit_high_effort_shows_three_bars(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Explicitly set high effort shows all three orange bars."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"effortLevel": "high"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌" in result.context[0]

    # --- Effort bars: default "high" for Claude 4+ when not in settings ---

    def test_claude4_defaults_to_high_bars_when_effort_absent(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Claude 4+ with no effortLevel in settings shows high bars (Claude Code default)."""
        hook_input = {
            "model": {"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"alwaysThinkingEnabled": True}))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌" in result.context[0]

    def test_claude4_defaults_to_high_bars_when_settings_missing(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Claude 4+ with no settings file at all shows high bars (Claude Code default)."""
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌" in result.context[0]

    def test_haiku4_defaults_to_high_bars_when_effort_absent(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Haiku 4.x with no effortLevel also defaults to high bars."""
        hook_input = {
            "model": {"id": "claude-haiku-4-5-20251001", "display_name": "Haiku 4.5"},
            "context_window": {"used_percentage": 10.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "\033[38;5;208m▌▌▌" in result.context[0]

    # --- No bars for pre-4.x models ---

    def test_claude3_no_bars_when_effort_not_in_settings(
        self, handler: ModelContextHandler, tmp_path: Path
    ) -> None:
        """Claude 3.x models don't support effort - no bars shown."""
        hook_input = {
            "model": {"id": "claude-3-5-sonnet-20241022", "display_name": "Claude 3.5 Sonnet"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "▌" not in result.context[0]

    def test_no_model_id_no_bars(self, handler: ModelContextHandler, tmp_path: Path) -> None:
        """Missing model ID shows no effort bars (safe default)."""
        hook_input = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 30.0},
        }
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle(hook_input)

        assert "▌" not in result.context[0]

    # --- _model_supports_effort unit tests ---

    def test_model_supports_effort_sonnet46(self, handler: ModelContextHandler) -> None:
        """claude-sonnet-4-6 supports effort."""
        assert handler._model_supports_effort("claude-sonnet-4-6") is True

    def test_model_supports_effort_opus46(self, handler: ModelContextHandler) -> None:
        """claude-opus-4-6 supports effort."""
        assert handler._model_supports_effort("claude-opus-4-6") is True

    def test_model_supports_effort_haiku45(self, handler: ModelContextHandler) -> None:
        """claude-haiku-4-5-20251001 supports effort."""
        assert handler._model_supports_effort("claude-haiku-4-5-20251001") is True

    def test_model_supports_effort_claude3_false(self, handler: ModelContextHandler) -> None:
        """claude-3-5-sonnet-20241022 does not support effort."""
        assert handler._model_supports_effort("claude-3-5-sonnet-20241022") is False

    def test_model_supports_effort_empty_false(self, handler: ModelContextHandler) -> None:
        """Empty model ID does not support effort."""
        assert handler._model_supports_effort("") is False
