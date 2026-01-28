"""Tests for SuggestStatusLineHandler."""

import pytest

from claude_code_hooks_daemon.handlers.session_start import SuggestStatusLineHandler


class TestSuggestStatusLineHandler:
    """Tests for SuggestStatusLineHandler."""

    @pytest.fixture
    def handler(self) -> SuggestStatusLineHandler:
        """Create handler instance."""
        return SuggestStatusLineHandler()

    def test_handler_properties(self, handler: SuggestStatusLineHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "suggest-statusline"
        assert handler.priority == 55
        assert handler.terminal is False
        assert "advisory" in handler.tags
        assert "workflow" in handler.tags
        assert "statusline" in handler.tags

    def test_matches_always_returns_true(self, handler: SuggestStatusLineHandler) -> None:
        """Handler should always match for session start events."""
        assert handler.matches({}) is True
        assert handler.matches({"session_id": "test"}) is True

    def test_handle_returns_suggestion(self, handler: SuggestStatusLineHandler) -> None:
        """Test handler returns status line setup suggestion."""
        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) > 0

        # Check for key elements in suggestion
        context_text = "\n".join(result.context)
        assert "Status Line Available" in context_text
        assert ".claude/settings.json" in context_text
        assert "statusLine" in context_text
        assert ".claude/hooks/status-line" in context_text

    def test_suggestion_includes_example_config(self, handler: SuggestStatusLineHandler) -> None:
        """Test suggestion includes example JSON configuration."""
        result = handler.handle({})

        context_text = "\n".join(result.context)
        assert "```json" in context_text
        assert '"type": "command"' in context_text
        assert '"command": ".claude/hooks/status-line"' in context_text

    def test_suggestion_describes_features(self, handler: SuggestStatusLineHandler) -> None:
        """Test suggestion describes what status line shows."""
        result = handler.handle({})

        context_text = "\n".join(result.context)
        assert "model name" in context_text
        assert "context usage" in context_text
        assert "git branch" in context_text
        assert "daemon health" in context_text
