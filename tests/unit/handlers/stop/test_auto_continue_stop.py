"""Comprehensive TDD tests for AutoContinueStopHandler.

This handler auto-continues when Claude asks confirmation questions before stopping,
preventing the need for user input and enabling true YOLO mode automation.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision, HookResult
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
    AutoContinueStopHandler,
)


class TestAutoContinueStopHandlerInit:
    """Test AutoContinueStopHandler initialization."""

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    def test_init_sets_correct_name(self, handler: AutoContinueStopHandler) -> None:
        """Handler name should be 'auto-continue-stop'."""
        assert handler.name == "auto-continue-stop"

    def test_init_sets_correct_priority(self, handler: AutoContinueStopHandler) -> None:
        """Handler priority should be 15 (early, before task_completion_checker at 50)."""
        assert handler.priority == 15

    def test_init_is_terminal(self, handler: AutoContinueStopHandler) -> None:
        """Handler should be terminal to stop dispatch chain."""
        assert handler.terminal is True

    def test_init_has_correct_tags(self, handler: AutoContinueStopHandler) -> None:
        """Handler should have workflow, automation, yolo-mode, and terminal tags."""
        expected_tags = ["workflow", "automation", "yolo-mode", "terminal"]
        assert set(handler.tags) == set(expected_tags)


class TestAutoContinueStopHandlerMatchesTrue:
    """Test cases where matches() should return True."""

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    @pytest.fixture
    def mock_transcript_path(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file path."""
        return tmp_path / "transcript.jsonl"

    def _write_transcript(
        self, path: Path, assistant_text: str, include_question: bool = True
    ) -> None:
        """Write a mock transcript with an assistant message."""
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": assistant_text + ("?" if include_question else ""),
                        }
                    ],
                },
            }
        ]
        with path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

    def test_matches_when_transcript_has_confirmation_question(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match when transcript contains a confirmation question."""
        self._write_transcript(
            mock_transcript_path, "Would you like me to continue with the next phase"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_should_i_proceed_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'should I proceed' pattern."""
        self._write_transcript(
            mock_transcript_path,
            "I've completed phase 1. Should I proceed with phase 2",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_ready_for_phase_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'ready for phase' pattern."""
        self._write_transcript(
            mock_transcript_path, "Ready for me to start the next batch of tests"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_would_you_like_to_continue_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'would you like to continue' pattern."""
        self._write_transcript(
            mock_transcript_path, "Would you like to continue with the implementation"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_shall_i_proceed_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'shall I proceed' pattern."""
        self._write_transcript(mock_transcript_path, "Shall I proceed with the remaining files")
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_can_i_continue_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'can I continue' pattern."""
        self._write_transcript(mock_transcript_path, "Can I continue with the next step")
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_may_i_proceed_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'may I proceed' pattern."""
        self._write_transcript(mock_transcript_path, "May I proceed with deploying the changes")
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_do_you_want_me_to_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'do you want me to' pattern."""
        self._write_transcript(
            mock_transcript_path, "Do you want me to continue with the refactoring"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_ready_to_implement_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'ready to implement' pattern."""
        self._write_transcript(mock_transcript_path, "Ready to implement the changes")
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True


class TestAutoContinueStopHandlerMatchesFalse:
    """Test cases where matches() should return False."""

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    @pytest.fixture
    def mock_transcript_path(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file path."""
        return tmp_path / "transcript.jsonl"

    def _write_transcript(
        self, path: Path, assistant_text: str, include_question: bool = True
    ) -> None:
        """Write a mock transcript with an assistant message."""
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": assistant_text + ("?" if include_question else ""),
                        }
                    ],
                },
            }
        ]
        with path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

    def test_matches_false_when_stop_hook_active_true(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """CRITICAL: Should return False when stop_hook_active is True to prevent infinite loops."""
        self._write_transcript(
            mock_transcript_path, "Would you like me to continue with the next phase"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": True,  # This prevents infinite loops
        }
        assert handler.matches(hook_input) is False

    def test_matches_false_when_no_transcript_path(self, handler: AutoContinueStopHandler) -> None:
        """Should return False when transcript_path is missing."""
        hook_input: dict[str, Any] = {"stop_hook_active": False}
        assert handler.matches(hook_input) is False

    def test_matches_false_when_transcript_path_empty(
        self, handler: AutoContinueStopHandler
    ) -> None:
        """Should return False when transcript_path is empty string."""
        hook_input = {"transcript_path": "", "stop_hook_active": False}
        assert handler.matches(hook_input) is False

    def test_matches_false_when_transcript_not_found(
        self, handler: AutoContinueStopHandler
    ) -> None:
        """Should return False when transcript file does not exist."""
        hook_input = {
            "transcript_path": "/nonexistent/path/transcript.jsonl",
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False

    def test_matches_false_when_last_message_not_question(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return False when last message doesn't contain a question mark."""
        self._write_transcript(
            mock_transcript_path,
            "I have completed the implementation",
            include_question=False,
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False

    def test_matches_false_when_last_message_is_error_report(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return False when last message is an error report, not a confirmation."""
        self._write_transcript(
            mock_transcript_path,
            "Error: The test failed. What would you like me to do",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        # This should NOT match because it's asking about error handling,
        # not asking for continuation permission
        assert handler.matches(hook_input) is False

    def test_matches_false_when_question_not_about_continuation(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return False when question is not about continuation."""
        self._write_transcript(
            mock_transcript_path, "What color scheme would you prefer for the UI"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False

    def test_matches_false_when_no_assistant_messages(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return False when transcript has no assistant messages."""
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Please continue"}],
                },
            }
        ]
        with mock_transcript_path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False

    def test_matches_false_when_transcript_is_malformed_json(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return False when transcript contains malformed JSON."""
        with mock_transcript_path.open("w") as f:
            f.write("not valid json\n")
            f.write("{incomplete json\n")

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False

    def test_matches_false_when_transcript_is_empty(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return False when transcript file is empty."""
        mock_transcript_path.touch()  # Create empty file

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False


class TestAutoContinueStopHandlerHandle:
    """Test handle() method behavior."""

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    def test_handle_returns_deny_decision(self, handler: AutoContinueStopHandler) -> None:
        """Should return DENY decision (which maps to 'block' in Stop hook output)."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_reason_contains_continue_instruction(
        self, handler: AutoContinueStopHandler
    ) -> None:
        """Should include clear instruction to continue in reason field."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.reason is not None
        reason_lower = result.reason.lower()
        # Check for key continuation phrases
        assert "continue" in reason_lower or "proceed" in reason_lower

    def test_handle_reason_tells_claude_to_proceed(self, handler: AutoContinueStopHandler) -> None:
        """Should tell Claude to proceed automatically without asking."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.reason is not None
        reason_lower = result.reason.lower()
        # Should mention automatic/auto-continue
        assert "auto" in reason_lower or "automatic" in reason_lower

    def test_handle_reason_mentions_no_confirmation_needed(
        self, handler: AutoContinueStopHandler
    ) -> None:
        """Should indicate that no confirmation is needed."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.reason is not None
        reason_lower = result.reason.lower()
        # Should mention not asking or no confirmation
        assert (
            "do not ask" in reason_lower
            or "don't ask" in reason_lower
            or "no confirmation" in reason_lower
            or "without asking" in reason_lower
        )

    def test_handle_returns_hook_result_instance(self, handler: AutoContinueStopHandler) -> None:
        """Should return HookResult instance."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)

    def test_handle_has_no_context(self, handler: AutoContinueStopHandler) -> None:
        """Should not provide context (Stop hooks don't use context)."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_has_no_guidance(self, handler: AutoContinueStopHandler) -> None:
        """Should not provide guidance."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_reason_is_concise(self, handler: AutoContinueStopHandler) -> None:
        """Reason should be concise and clear (not overly verbose)."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.reason is not None
        # Reason should be under 500 characters
        assert len(result.reason) < 500

    def test_handle_reason_is_actionable(self, handler: AutoContinueStopHandler) -> None:
        """Reason should be actionable and tell Claude what to do."""
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.reason is not None
        reason_lower = result.reason.lower()
        # Should contain action verbs
        action_verbs = ["continue", "proceed", "go", "resume", "move"]
        assert any(verb in reason_lower for verb in action_verbs)


class TestAutoContinueStopHandlerEdgeCases:
    """Test edge cases for transcript parsing."""

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    @pytest.fixture
    def mock_transcript_path(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file path."""
        return tmp_path / "transcript.jsonl"

    def test_matches_handles_transcript_with_blank_lines(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should handle transcripts with blank lines."""
        with mock_transcript_path.open("w") as f:
            f.write("\n")  # Blank line
            f.write("\n")  # Another blank line
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Should I continue?"}],
                        },
                    }
                )
                + "\n"
            )

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_handles_transcript_with_non_message_entries(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should skip non-message type entries in transcript."""
        with mock_transcript_path.open("w") as f:
            f.write(json.dumps({"type": "status", "data": "some status"}) + "\n")
            f.write(json.dumps({"type": "event", "data": "some event"}) + "\n")
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Would you like me to proceed?"}],
                        },
                    }
                )
                + "\n"
            )

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_handles_string_content_in_message(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should handle content that is a string instead of dict."""
        with mock_transcript_path.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": ["Should I continue?"],  # String directly
                        },
                    }
                )
                + "\n"
            )

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_handles_oserror_reading_transcript(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Should handle OSError when reading transcript."""
        transcript_path = tmp_path / "unreadable.jsonl"
        transcript_path.touch()
        # Make file unreadable
        transcript_path.chmod(0o000)

        hook_input = {
            "transcript_path": str(transcript_path),
            "stop_hook_active": False,
        }

        try:
            result = handler.matches(hook_input)
            # Should return False on read error
            assert result is False
        finally:
            # Clean up - restore permissions so pytest can delete the file
            transcript_path.chmod(0o644)

    def test_matches_handles_unicode_decode_error(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should handle UnicodeDecodeError when reading transcript."""
        # Write invalid UTF-8 bytes
        with mock_transcript_path.open("wb") as f:
            f.write(b"\xff\xfe invalid utf-8 \x80\x81")

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        # Should return False on decode error
        assert handler.matches(hook_input) is False

    def test_matches_handles_unexpected_exception(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path, monkeypatch: Any
    ) -> None:
        """Should handle unexpected exceptions during transcript reading."""
        # Write a valid file first
        with mock_transcript_path.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Should I continue?"}],
                        },
                    }
                )
                + "\n"
            )

        # Patch Path.open to raise an unexpected exception
        original_open = Path.open

        def mock_open(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Unexpected error")

        monkeypatch.setattr(Path, "open", mock_open)

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        # Should return False on unexpected error
        assert handler.matches(hook_input) is False
