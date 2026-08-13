"""Integration tests for Stop handlers.

Tests: AutoContinueStopHandler
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import make_stop_input


# ---------------------------------------------------------------------------
# AutoContinueStopHandler
# ---------------------------------------------------------------------------
class TestAutoContinueStopHandler:
    """Integration tests for AutoContinueStopHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
            AutoContinueStopHandler,
        )

        return AutoContinueStopHandler()

    def test_blocks_confirmation_question(self, handler: Any, tmp_path: Any) -> None:
        # Create a transcript with a confirmation question
        transcript = tmp_path / "transcript.jsonl"
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Would you like me to continue with the next step?"}
                ],
            },
        }
        transcript.write_text(json.dumps(message) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path=str(transcript),
        )
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "AUTO-CONTINUE" in result.reason

    def test_prevents_infinite_loop(self, handler: Any, tmp_path: Any) -> None:
        # Genuine re-entry (prior Stop block marker in transcript) MUST not match
        # to prevent infinite loops. Without a block marker, stop_hook_active=True
        # is the silent-stop bug shape and matches() must still fire.
        transcript = tmp_path / "transcript.jsonl"
        assistant_msg = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Would you like me to continue?"}],
            },
        }
        block_marker = {
            "type": "user",
            "message": {
                "role": "user",
                "content": "Stop hook feedback:\nYou stopped without explaining why.",
            },
        }
        transcript.write_text(json.dumps(assistant_msg) + "\n" + json.dumps(block_marker) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=True,
            transcript_path=str(transcript),
        )
        assert handler.matches(hook_input) is False

    def test_matches_error_questions_with_default_continue_on_errors(
        self, handler: Any, tmp_path: Any
    ) -> None:
        """With default continue_on_errors=True, error questions SHOULD match."""
        transcript = tmp_path / "transcript.jsonl"
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Error: build failed. What would you like me to do?"}
                ],
            },
        }
        transcript.write_text(json.dumps(message) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path=str(transcript),
        )
        assert handler.matches(hook_input) is True

    def test_ignores_error_questions_when_continue_on_errors_false(
        self, handler: Any, tmp_path: Any
    ) -> None:
        """With continue_on_errors=False, error questions match but don't auto-continue."""
        handler._continue_on_errors = False
        transcript = tmp_path / "transcript.jsonl"
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Error: build failed. What would you like me to do?"}
                ],
            },
        }
        transcript.write_text(json.dumps(message) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path=str(transcript),
        )
        # matches() always returns True now — routing is in handle()
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        # Must not emit auto-continue confirmation — requires stop explanation instead
        assert not (result.reason or "").startswith("AUTO-CONTINUE: Yes")

    def test_ignores_non_question(self, handler: Any, tmp_path: Any) -> None:
        """Non-question text matches but requires stop explanation."""
        transcript = tmp_path / "transcript.jsonl"
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "All tasks completed successfully."}],
            },
        }
        transcript.write_text(json.dumps(message) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path=str(transcript),
        )
        # matches() always returns True now — routing is in handle()
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "STOPPING BECAUSE" in (result.reason or "")

    def test_handles_missing_transcript(self, handler: Any) -> None:
        """Missing transcript is fail-open: matches True, handle() requires explanation."""
        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path="/nonexistent/transcript.jsonl",
        )
        # matches() is fail-open — returns True even when transcript is missing
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "STOPPING BECAUSE" in (result.reason or "")

    def test_handler_is_terminal(self, handler: Any) -> None:
        assert handler.terminal is True
