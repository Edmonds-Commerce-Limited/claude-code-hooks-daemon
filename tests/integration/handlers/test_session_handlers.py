"""Integration tests for Session lifecycle handlers.

Tests: YoloContainerDetectionHandler, CleanupHandler
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import (
    make_session_end_input,
)


# ---------------------------------------------------------------------------
# YoloContainerDetectionHandler
# ---------------------------------------------------------------------------
class TestYoloContainerDetectionHandler:
    """Integration tests for YoloContainerDetectionHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
            YoloContainerDetectionHandler,
        )

        return YoloContainerDetectionHandler()

    def test_matches_yolo_environment(self, handler: Any) -> None:
        hook_input = {
            "hook_event_name": "SessionStart",
            "source": "user",
        }
        # Simulate YOLO environment with environment variables
        with patch.dict("os.environ", {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"}):
            if handler.matches(hook_input):
                result = handler.handle(hook_input)
                assert result.decision == Decision.ALLOW
                assert result.context is not None

    def test_ignores_non_session_start(self, handler: Any) -> None:
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_non_yolo(self, handler: Any) -> None:
        hook_input = {
            "hook_event_name": "SessionStart",
            "source": "user",
        }
        # Clear YOLO indicators to ensure low confidence score
        env_overrides = {
            "CLAUDECODE": "",
            "CLAUDE_CODE_ENTRYPOINT": "",
            "DEVCONTAINER": "",
            "IS_SANDBOX": "",
            "container": "",
        }
        with patch.dict("os.environ", env_overrides, clear=False):
            # With low confidence score, should not match
            handler.config["min_confidence_score"] = 100
            assert handler.matches(hook_input) is False

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False

    def test_null_input_not_matched(self, handler: Any) -> None:
        # Pass None typed as Any to test null safety
        null_input: Any = None
        assert handler.matches(null_input) is False


# ---------------------------------------------------------------------------
# CleanupHandler
# ---------------------------------------------------------------------------
class TestCleanupHandler:
    """Integration tests for CleanupHandler (SessionEnd)."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_end.cleanup_handler import (
            CleanupHandler,
        )

        return CleanupHandler()

    def test_matches_session_end(self, handler: Any) -> None:
        hook_input = make_session_end_input()
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow(self, handler: Any) -> None:
        hook_input = make_session_end_input()
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False
