"""Tests for ThinkingModeHandler."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.status_line.thinking_mode import (
    ThinkingModeHandler,
)


class TestThinkingModeHandler:
    """Test thinking mode status line handler."""

    @pytest.fixture
    def handler(self) -> ThinkingModeHandler:
        """Create handler instance."""
        return ThinkingModeHandler()

    def test_init_name(self, handler: ThinkingModeHandler) -> None:
        assert handler.name == "status-thinking-mode"

    def test_init_priority(self, handler: ThinkingModeHandler) -> None:
        assert handler.priority == 12

    def test_init_terminal_false(self, handler: ThinkingModeHandler) -> None:
        assert handler.terminal is False

    def test_matches_always_true(self, handler: ThinkingModeHandler) -> None:
        assert handler.matches({}) is True

    def test_handle_shows_on_when_always_thinking_enabled(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should show 'On' when alwaysThinkingEnabled is true."""
        settings = {"alwaysThinkingEnabled": True}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        assert result.context is not None
        assert len(result.context) == 1
        assert "On" in result.context[0]

    def test_handle_shows_off_when_always_thinking_disabled(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should show 'Off' when alwaysThinkingEnabled is explicitly false."""
        settings = {"alwaysThinkingEnabled": False}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        assert result.context is not None
        assert len(result.context) == 1
        assert "Off" in result.context[0]

    def test_handle_omits_thinking_when_key_missing(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should not show thinking status when key is absent (unknown state)."""
        settings = {"model": "opus"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        # No thinking status, no effort level = empty
        assert len(result.context) == 0

    def test_handle_effort_level_ignored(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Effort level should not be shown (handled by ModelContextHandler now)."""
        settings = {"alwaysThinkingEnabled": True, "effortLevel": "medium"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        # Only thinking status, no effort
        assert len(result.context) == 1
        assert "On" in result.context[0]
        assert "medium" not in result.context[0]

    def test_handle_no_thinking_key_no_effort(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should return empty context when neither key exists."""
        settings = {"model": "opus"}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        assert len(result.context) == 0

    def test_handle_empty_when_file_missing(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should return empty context when settings file doesn't exist."""
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        assert len(result.context) == 0

    def test_handle_empty_on_malformed_json(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should return empty context when settings file has invalid JSON."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not valid json{{{")

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        assert len(result.context) == 0

    def test_handle_empty_settings(self, handler: ThinkingModeHandler, tmp_path: Path) -> None:
        """Should return empty context for empty settings."""
        settings: dict[str, Any] = {}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        assert len(result.context) == 0

    def test_get_acceptance_tests(self, handler: ThinkingModeHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0

    def test_handle_returns_empty_on_unexpected_exception(
        self, handler: ThinkingModeHandler
    ) -> None:
        """Should return empty context and log when an unexpected exception occurs."""
        with patch.object(handler, "_read_settings", side_effect=RuntimeError("unexpected")):
            result = handler.handle({})

        assert result.context == []

    def test_get_settings_path_returns_claude_settings(
        self, handler: ThinkingModeHandler
    ) -> None:
        """_get_settings_path should return ~/.claude/settings.json."""
        path = handler._get_settings_path()
        assert path.name == "settings.json"
        assert path.parent.name == ".claude"
