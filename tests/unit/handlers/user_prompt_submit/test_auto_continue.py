"""Tests for AutoContinueHandler."""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.user_prompt_submit.auto_continue import (
    AutoContinueHandler,
)


class TestAutoContinueHandler:
    """Test AutoContinueHandler initialization and configuration."""

    @pytest.fixture
    def handler(self) -> AutoContinueHandler:
        """Create handler instance for testing."""
        return AutoContinueHandler()

    @pytest.fixture
    def transcript_file(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file."""
        return tmp_path / "transcript.jsonl"

    def test_handler_initialization(self, handler: AutoContinueHandler) -> None:
        """Handler initializes with correct attributes."""
        assert handler.name == "auto-continue"
        assert handler.priority == 10
        assert "workflow" in handler.tags
        assert "automation" in handler.tags
        assert "non-terminal" in handler.tags

    def test_confirmation_patterns_are_defined(self, handler: AutoContinueHandler) -> None:
        """Handler has confirmation patterns defined."""
        assert len(handler.CONFIRMATION_PATTERNS) > 0
        assert isinstance(handler.CONFIRMATION_PATTERNS, list)

    def test_minimal_responses_are_defined(self, handler: AutoContinueHandler) -> None:
        """Handler has minimal responses defined."""
        assert len(handler.MINIMAL_RESPONSES) > 0
        assert "yes" in handler.MINIMAL_RESPONSES
        assert "y" in handler.MINIMAL_RESPONSES


class TestMatches:
    """Test match detection logic."""

    @pytest.fixture
    def handler(self) -> AutoContinueHandler:
        """Create handler instance for testing."""
        return AutoContinueHandler()

    @pytest.fixture
    def transcript_file(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file."""
        return tmp_path / "transcript.jsonl"

    def _write_assistant_message(self, transcript_file: Path, text: str) -> None:
        """Helper to write an assistant message to transcript."""
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            },
        }
        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

    def test_matches_minimal_response_after_confirmation(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Matches when user gives minimal response after confirmation prompt."""
        self._write_assistant_message(
            transcript_file, "Would you like me to continue with the implementation?"
        )

        hook_input: dict[str, Any] = {
            "prompt": "yes",
            "transcript_path": str(transcript_file),
        }

        assert handler.matches(hook_input) is True

    def test_does_not_match_without_prompt(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Does not match if prompt is empty."""
        self._write_assistant_message(transcript_file, "Would you like me to continue?")

        hook_input: dict[str, Any] = {
            "prompt": "",
            "transcript_path": str(transcript_file),
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_without_transcript_path(self, handler: AutoContinueHandler) -> None:
        """Does not match if transcript path is missing."""
        hook_input: dict[str, Any] = {
            "prompt": "yes",
            "transcript_path": "",
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_without_confirmation_prompt(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Does not match if last message wasn't a confirmation prompt."""
        self._write_assistant_message(transcript_file, "Here's some information about the code.")

        hook_input: dict[str, Any] = {
            "prompt": "yes",
            "transcript_path": str(transcript_file),
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_detailed_response(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Does not match if user gives detailed response."""
        self._write_assistant_message(transcript_file, "Would you like me to continue?")

        hook_input: dict[str, Any] = {
            "prompt": "Yes, but please make sure to add error handling",
            "transcript_path": str(transcript_file),
        }

        assert handler.matches(hook_input) is False

    def test_matches_various_minimal_responses(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Matches all defined minimal responses."""
        self._write_assistant_message(transcript_file, "Should I proceed with the next step?")

        for response in ["yes", "y", "yep", "yeah", "ok", "okay", "continue", "proceed"]:
            hook_input: dict[str, Any] = {
                "prompt": response,
                "transcript_path": str(transcript_file),
            }
            assert handler.matches(hook_input) is True


class TestHandle:
    """Test handle logic."""

    @pytest.fixture
    def handler(self) -> AutoContinueHandler:
        """Create handler instance for testing."""
        return AutoContinueHandler()

    def test_enhances_minimal_response(self, handler: AutoContinueHandler) -> None:
        """Enhances minimal response with auto-continue instruction."""
        hook_input: dict[str, Any] = {
            "prompt": "yes",
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "yes" in result.context[0]
        assert "AUTO-CONTINUE MODE" in result.context[0]
        assert "Do NOT ask for confirmation again" in result.context[0]

    def test_enhances_detailed_response(self, handler: AutoContinueHandler) -> None:
        """Enhances detailed response with auto-continue note."""
        hook_input: dict[str, Any] = {
            "prompt": "Yes, please continue but add error handling",
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "Yes, please continue but add error handling" in result.context[0]
        assert "Auto-continue mode enabled" in result.context[0]

    def test_preserves_original_prompt_in_context(self, handler: AutoContinueHandler) -> None:
        """Original prompt is preserved in enhanced version."""
        hook_input: dict[str, Any] = {
            "prompt": "okay",
        }

        result = handler.handle(hook_input)

        assert "okay" in result.context[0]


class TestContainsConfirmationPrompt:
    """Test confirmation prompt detection."""

    @pytest.fixture
    def handler(self) -> AutoContinueHandler:
        """Create handler instance for testing."""
        return AutoContinueHandler()

    def test_detects_would_you_like_pattern(self, handler: AutoContinueHandler) -> None:
        """Detects 'would you like me to' pattern."""
        text = "Would you like me to continue with the implementation?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_detects_should_i_pattern(self, handler: AutoContinueHandler) -> None:
        """Detects 'should I' pattern."""
        text = "Should I proceed with the next step?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_detects_shall_i_pattern(self, handler: AutoContinueHandler) -> None:
        """Detects 'shall I' pattern."""
        text = "Shall I continue with batch 2?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_detects_do_you_want_pattern(self, handler: AutoContinueHandler) -> None:
        """Detects 'do you want me to' pattern."""
        text = "Do you want me to start the implementation?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_detects_ready_to_pattern(self, handler: AutoContinueHandler) -> None:
        """Detects 'ready to' pattern."""
        text = "Ready to implement the changes?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_does_not_detect_statement(self, handler: AutoContinueHandler) -> None:
        """Does not detect confirmation in regular statement."""
        text = "I have completed the implementation."
        assert handler._contains_confirmation_prompt(text) is False

    def test_detects_question_with_confirmation_words(self, handler: AutoContinueHandler) -> None:
        """Detects question with confirmation words in last section."""
        text = "Here's the plan. Would you like to proceed?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_returns_false_for_empty_text(self, handler: AutoContinueHandler) -> None:
        """Returns False for empty text."""
        assert handler._contains_confirmation_prompt("") is False

    def test_detects_batch_continuation_pattern(self, handler: AutoContinueHandler) -> None:
        """Detects batch/phase continuation pattern."""
        text = "Continue with batch 2?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_detects_question_in_last_section_with_confirmation_words(
        self, handler: AutoContinueHandler
    ) -> None:
        """Detects question mark with confirmation words in last 300 chars."""
        # Long text with question at the end containing confirmation words
        long_text = "A" * 250 + " Would you prefer to continue?"
        assert handler._contains_confirmation_prompt(long_text) is True

    def test_detects_question_with_like_me_to(self, handler: AutoContinueHandler) -> None:
        """Detects 'like me to' pattern in question."""
        text = "Would you like me to implement this?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_detects_question_with_want_me_to(self, handler: AutoContinueHandler) -> None:
        """Detects 'want me to' pattern in question."""
        text = "Do you want me to start?"
        assert handler._contains_confirmation_prompt(text) is True

    def test_no_match_question_without_confirmation_words(
        self, handler: AutoContinueHandler
    ) -> None:
        """Does not match question without confirmation words."""
        text = "What is the weather today?"
        assert handler._contains_confirmation_prompt(text) is False


class TestIsMinimalResponse:
    """Test minimal response detection."""

    @pytest.fixture
    def handler(self) -> AutoContinueHandler:
        """Create handler instance for testing."""
        return AutoContinueHandler()

    def test_detects_yes(self, handler: AutoContinueHandler) -> None:
        """Detects 'yes' as minimal response."""
        assert handler._is_minimal_response("yes") is True

    def test_detects_yes_with_whitespace(self, handler: AutoContinueHandler) -> None:
        """Detects 'yes' with surrounding whitespace."""
        assert handler._is_minimal_response("  yes  ") is True

    def test_detects_uppercase_yes(self, handler: AutoContinueHandler) -> None:
        """Detects uppercase 'YES'."""
        assert handler._is_minimal_response("YES") is True

    def test_detects_all_minimal_responses(self, handler: AutoContinueHandler) -> None:
        """Detects all defined minimal responses."""
        for response in handler.MINIMAL_RESPONSES:
            assert handler._is_minimal_response(response) is True

    def test_does_not_detect_detailed_response(self, handler: AutoContinueHandler) -> None:
        """Does not detect detailed response as minimal."""
        assert handler._is_minimal_response("yes, but add error handling") is False

    def test_does_not_detect_empty_string(self, handler: AutoContinueHandler) -> None:
        """Does not detect empty string as minimal."""
        assert handler._is_minimal_response("") is False


class TestGetLastAssistantMessage:
    """Test transcript parsing logic."""

    @pytest.fixture
    def handler(self) -> AutoContinueHandler:
        """Create handler instance for testing."""
        return AutoContinueHandler()

    @pytest.fixture
    def transcript_file(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file."""
        return tmp_path / "transcript.jsonl"

    def test_extracts_last_assistant_message(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Extracts the last assistant message from transcript."""
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "First message"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "User response"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Last message"}],
                },
            },
        ]

        with transcript_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        result = handler._get_last_assistant_message(str(transcript_file))
        assert result == "Last message"

    def test_handles_multiple_text_parts(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Handles message with multiple text parts."""
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                ],
            },
        }

        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

        result = handler._get_last_assistant_message(str(transcript_file))
        assert "Part 1" in result
        assert "Part 2" in result

    def test_handles_string_content(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Handles content as string instead of dict."""
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": ["String content"],
            },
        }

        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

        result = handler._get_last_assistant_message(str(transcript_file))
        assert "String content" in result

    def test_returns_empty_for_missing_file(self, handler: AutoContinueHandler) -> None:
        """Returns empty string for missing file."""
        result = handler._get_last_assistant_message("/nonexistent/file.jsonl")
        assert result == ""

    def test_handles_invalid_json_lines(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Handles transcript with invalid JSON lines."""
        with transcript_file.open("w") as f:
            f.write("invalid json\n")
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Valid message"}],
                        },
                    }
                )
                + "\n"
            )

        result = handler._get_last_assistant_message(str(transcript_file))
        assert result == "Valid message"

    def test_returns_empty_for_no_assistant_messages(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Returns empty string when no assistant messages found."""
        message = {
            "type": "message",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "User message"}],
            },
        }

        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

        result = handler._get_last_assistant_message(str(transcript_file))
        assert result == ""

    def test_handles_exception_gracefully(
        self, handler: AutoContinueHandler, transcript_file: Path
    ) -> None:
        """Handles exceptions gracefully and returns empty string."""
        # Create a file with permission issues by writing and then making it unreadable
        # Instead, just pass an invalid path
        result = handler._get_last_assistant_message("/invalid\x00path.jsonl")
        assert result == ""
