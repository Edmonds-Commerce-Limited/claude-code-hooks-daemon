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
        assert handler.priority == 25

    def test_init_terminal_false(self, handler: ThinkingModeHandler) -> None:
        assert handler.terminal is False

    def test_matches_always_true(self, handler: ThinkingModeHandler) -> None:
        assert handler.matches({}) is True

    def test_handle_shows_on_when_thinking_enabled(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should show 'On' when alwaysThinkingEnabled is true."""
        settings = {"alwaysThinkingEnabled": True}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        assert result.context is not None
        assert len(result.context) > 0
        context_str = result.context[0]
        assert "On" in context_str

    def test_handle_shows_off_when_thinking_disabled(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should show 'Off' when alwaysThinkingEnabled is false."""
        settings = {"alwaysThinkingEnabled": False}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        assert result.context is not None
        assert len(result.context) > 0
        context_str = result.context[0]
        assert "Off" in context_str

    def test_handle_shows_off_when_key_missing(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should show 'Off' when key is missing from settings."""
        settings: dict[str, Any] = {"someOtherKey": True}
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps(settings))

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        context_str = result.context[0]
        assert "Off" in context_str

    def test_handle_shows_off_when_file_missing(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should show 'Off' when settings file doesn't exist."""
        settings_file = tmp_path / "nonexistent.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        context_str = result.context[0]
        assert "Off" in context_str

    def test_handle_shows_off_on_malformed_json(
        self, handler: ThinkingModeHandler, tmp_path: Path
    ) -> None:
        """Should show 'Off' when settings file has invalid JSON."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not valid json{{{")

        with patch.object(handler, "_get_settings_path", return_value=settings_file):
            result = handler.handle({})

        context_str = result.context[0]
        assert "Off" in context_str

    def test_get_acceptance_tests(self, handler: ThinkingModeHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
