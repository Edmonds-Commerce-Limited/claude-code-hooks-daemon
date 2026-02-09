"""Tests for ModelContextHandler."""

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
        assert "Ctx:" in result.context[0]

    def test_handle_with_defaults(self, handler: ModelContextHandler) -> None:
        """Test formatting with missing data uses defaults."""
        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Claude" in result.context[0]
        assert "0.0%" in result.context[0]

    def test_color_coding_green(self, handler: ModelContextHandler) -> None:
        """Test green color for low usage (0-40%)."""
        hook_input = {
            "model": {"display_name": "Claude"},
            "context_window": {"used_percentage": 30.0},
        }

        result = handler.handle(hook_input)
        # Check for green background ANSI code
        assert "\033[42m" in result.context[0]

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

    def test_extended_thinking_effort_level_displayed(self, handler: ModelContextHandler) -> None:
        """Test effort level is displayed when extended thinking is enabled."""
        hook_input = {
            "model": {"display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 25.0},
            "extended_thinking": {"enabled": True, "effort_level": 3},
        }

        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Opus 4.6" in result.context[0]
        assert "Effort: 3" in result.context[0]

    def test_extended_thinking_disabled(self, handler: ModelContextHandler) -> None:
        """Test effort level is not displayed when extended thinking is disabled."""
        hook_input = {
            "model": {"display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 25.0},
            "extended_thinking": {"enabled": False, "effort_level": 3},
        }

        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Opus 4.6" in result.context[0]
        assert "Effort:" not in result.context[0]

    def test_extended_thinking_missing(self, handler: ModelContextHandler) -> None:
        """Test no error when extended_thinking key is missing entirely."""
        hook_input = {
            "model": {"display_name": "Sonnet 4.5"},
            "context_window": {"used_percentage": 30.0},
        }

        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Sonnet 4.5" in result.context[0]
        assert "Effort:" not in result.context[0]

    def test_extended_thinking_effort_level_none(self, handler: ModelContextHandler) -> None:
        """Test effort level not displayed when effort_level is None."""
        hook_input = {
            "model": {"display_name": "Opus 4.6"},
            "context_window": {"used_percentage": 25.0},
            "extended_thinking": {"enabled": True, "effort_level": None},
        }

        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "Opus 4.6" in result.context[0]
        assert "Effort:" not in result.context[0]
