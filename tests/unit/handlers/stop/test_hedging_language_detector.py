"""Tests for hedging language detector handler.

Detects when the agent uses hedging/uncertain language that signals
guessing instead of doing proper research with tools.
"""

import json
import tempfile
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision


class TestHedgingLanguageDetectorInit:
    """Test handler initialization."""

    def test_handler_id(self) -> None:
        """Test handler has correct ID."""
        from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
            HedgingLanguageDetectorHandler,
        )

        handler = HedgingLanguageDetectorHandler()
        assert handler.handler_id.config_key == "hedging_language_detector"

    def test_non_terminal(self) -> None:
        """Test handler is non-terminal (advisory only)."""
        from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
            HedgingLanguageDetectorHandler,
        )

        handler = HedgingLanguageDetectorHandler()
        assert handler.terminal is False

    def test_tags_include_quality(self) -> None:
        """Test handler has quality-related tags."""
        from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
            HedgingLanguageDetectorHandler,
        )

        handler = HedgingLanguageDetectorHandler()
        assert HandlerTag.VALIDATION in handler.tags
        assert HandlerTag.ADVISORY in handler.tags
        assert HandlerTag.NON_TERMINAL in handler.tags


def _make_transcript(messages: list[dict[str, Any]]) -> str:
    """Create a temporary JSONL transcript file.

    Args:
        messages: List of transcript entries (dicts with type, message, etc.)

    Returns:
        Path to temporary JSONL file
    """
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for msg in messages:
        tmp.write(json.dumps(msg) + "\n")
    tmp.flush()
    return tmp.name


def _assistant_message(text: str) -> dict[str, Any]:
    """Create an assistant message transcript entry."""
    return {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _human_message(text: str) -> dict[str, Any]:
    """Create a human message transcript entry."""
    return {
        "type": "message",
        "message": {
            "role": "human",
            "content": [{"type": "text", "text": text}],
        },
    }


class TestHedgingLanguageDetectorMatches:
    """Test matches() correctly identifies hedging language in transcripts."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
            HedgingLanguageDetectorHandler,
        )

        return HedgingLanguageDetectorHandler()

    # --- Memory-based guessing patterns ---

    def test_matches_if_i_recall(self, handler: Any) -> None:
        """Detect 'if I recall correctly' - agent relying on memory."""
        path = _make_transcript(
            [_assistant_message("If I recall correctly, that function is in utils.py")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_iirc(self, handler: Any) -> None:
        """Detect 'IIRC' abbreviation."""
        path = _make_transcript([_assistant_message("IIRC the config file uses JSON format")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_from_memory(self, handler: Any) -> None:
        """Detect 'from memory' - explicit memory reliance."""
        path = _make_transcript(
            [_assistant_message("From memory, I think the API endpoint is /api/v2")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_if_memory_serves(self, handler: Any) -> None:
        """Detect 'if memory serves'."""
        path = _make_transcript(
            [_assistant_message("If memory serves, the tests are in the __tests__ folder")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- Uncertainty hedging patterns ---

    def test_matches_should_probably(self, handler: Any) -> None:
        """Detect 'should probably' - uncertain recommendation."""
        path = _make_transcript(
            [_assistant_message("You should probably add error handling there")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_most_likely(self, handler: Any) -> None:
        """Detect 'most likely' - uncertainty about facts."""
        path = _make_transcript([_assistant_message("The bug is most likely in the parser module")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_presumably(self, handler: Any) -> None:
        """Detect 'presumably' - assumption without verification."""
        path = _make_transcript([_assistant_message("This presumably handles the edge case")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_i_assume(self, handler: Any) -> None:
        """Detect 'I assume' - explicit assumption."""
        path = _make_transcript(
            [_assistant_message("I assume the database is PostgreSQL based on the config")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_i_believe(self, handler: Any) -> None:
        """Detect 'I believe' - belief not fact."""
        path = _make_transcript([_assistant_message("I believe this function returns a string")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_i_suspect(self, handler: Any) -> None:
        """Detect 'I suspect' - suspicion not verification."""
        path = _make_transcript([_assistant_message("I suspect the issue is a race condition")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- Weak confidence patterns ---

    def test_matches_im_not_sure_but(self, handler: Any) -> None:
        """Detect 'I'm not sure but' - explicit uncertainty."""
        path = _make_transcript(
            [_assistant_message("I'm not sure but I think the file is in src/")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_im_fairly_confident(self, handler: Any) -> None:
        """Detect 'I'm fairly confident' - hedged confidence."""
        path = _make_transcript(
            [_assistant_message("I'm fairly confident this is the right approach")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_im_pretty_sure(self, handler: Any) -> None:
        """Detect 'I'm pretty sure' - hedged certainty."""
        path = _make_transcript(
            [_assistant_message("I'm pretty sure that method exists on the class")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_it_seems_like(self, handler: Any) -> None:
        """Detect 'it seems like' - vague assessment."""
        path = _make_transcript(
            [_assistant_message("It seems like the tests are failing due to a timeout")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_might_be(self, handler: Any) -> None:
        """Detect 'might be' when used for factual claims."""
        path = _make_transcript([_assistant_message("The config file might be located in /etc/")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_could_be(self, handler: Any) -> None:
        """Detect 'could be' when used for factual claims."""
        path = _make_transcript(
            [_assistant_message("The error could be caused by a missing dependency")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_likely_standalone(self, handler: Any) -> None:
        """Detect standalone 'likely' - speculation about verifiable facts."""
        path = _make_transcript([_assistant_message("They themselves likely completed fine")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_probably_standalone(self, handler: Any) -> None:
        """Detect standalone 'probably' - speculation about verifiable facts."""
        path = _make_transcript(
            [_assistant_message("The issue probably stems from a missing dependency")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_apparently(self, handler: Any) -> None:
        """Detect 'apparently' - unverified claim presented as fact."""
        path = _make_transcript(
            [_assistant_message("Apparently the system restarted during the upgrade")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_seemingly(self, handler: Any) -> None:
        """Detect 'seemingly' - surface-level assessment without verification."""
        path = _make_transcript(
            [_assistant_message("The seemingly unrelated config change caused the failure")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_possibly(self, handler: Any) -> None:
        """Detect 'possibly' - speculation about verifiable facts."""
        path = _make_transcript(
            [_assistant_message("This was possibly caused by a race condition")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- Case insensitivity ---

    def test_matches_case_insensitive(self, handler: Any) -> None:
        """Patterns should match regardless of case."""
        path = _make_transcript([_assistant_message("IF I RECALL CORRECTLY, the file is there")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- Negative cases (should NOT match) ---

    def test_no_match_clean_factual_response(self, handler: Any) -> None:
        """Clean factual response should not trigger."""
        path = _make_transcript(
            [
                _assistant_message(
                    "The function `parse_config` is defined at line 42 of config.py. It takes a Path argument and returns a dict."
                )
            ]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_tool_based_response(self, handler: Any) -> None:
        """Response based on tool results should not trigger."""
        path = _make_transcript(
            [
                _assistant_message(
                    "I found the file at /workspace/src/main.py. Here's the relevant code:"
                )
            ]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_no_transcript_path(self, handler: Any) -> None:
        """No transcript_path in input should not match."""
        assert handler.matches({}) is False

    def test_no_match_nonexistent_transcript(self, handler: Any) -> None:
        """Nonexistent transcript file should not match."""
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: "/nonexistent/path.jsonl"}) is False

    def test_no_match_empty_transcript(self, handler: Any) -> None:
        """Empty transcript should not match."""
        path = _make_transcript([])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_only_human_messages(self, handler: Any) -> None:
        """Transcript with only human messages should not match."""
        path = _make_transcript([_human_message("I think you should check the file")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_stop_hook_active(self, handler: Any) -> None:
        """Should not match when stop_hook_active is set (re-entry prevention)."""
        path = _make_transcript([_assistant_message("I believe this is the issue")])
        hook_input = {
            HookInputField.TRANSCRIPT_PATH: path,
            "stop_hook_active": True,
        }
        assert handler.matches(hook_input) is False

    def test_no_match_stop_hook_active_camel_case(self, handler: Any) -> None:
        """Should not match when stopHookActive (camelCase) is set."""
        path = _make_transcript([_assistant_message("I believe this is the issue")])
        hook_input = {
            HookInputField.TRANSCRIPT_PATH: path,
            "stopHookActive": True,
        }
        assert handler.matches(hook_input) is False


class TestHedgingLanguageDetectorHandle:
    """Test handle() returns correct advisory response."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
            HedgingLanguageDetectorHandler,
        )

        return HedgingLanguageDetectorHandler()

    def test_returns_allow_decision(self, handler: Any) -> None:
        """Handle should return ALLOW (advisory, not blocking)."""
        path = _make_transcript([_assistant_message("I believe the config is in /etc/")])
        result = handler.handle({HookInputField.TRANSCRIPT_PATH: path})
        assert result.decision == Decision.ALLOW

    def test_context_warns_about_hedging(self, handler: Any) -> None:
        """Context should warn about hedging language detected."""
        path = _make_transcript([_assistant_message("I believe the config is in /etc/")])
        result = handler.handle({HookInputField.TRANSCRIPT_PATH: path})
        context = "\n".join(result.context)
        assert "HEDGING" in context.upper() or "hedging" in context.lower()

    def test_context_tells_to_verify(self, handler: Any) -> None:
        """Context should tell agent to research, not guess."""
        path = _make_transcript([_assistant_message("I suspect the bug is in the parser")])
        result = handler.handle({HookInputField.TRANSCRIPT_PATH: path})
        context = "\n".join(result.context)
        # Should mention using tools to verify
        assert (
            "Read" in context or "Grep" in context or "Glob" in context or "tool" in context.lower()
        )
        # Should mention online research
        assert "WebSearch" in context or "online" in context.lower()
        # Core message
        assert "GUESSING" in context
        assert "RESEARCH" in context

    def test_context_includes_matched_phrases(self, handler: Any) -> None:
        """Context should include which phrases were detected."""
        path = _make_transcript([_assistant_message("I believe this should probably work")])
        result = handler.handle({HookInputField.TRANSCRIPT_PATH: path})
        context = "\n".join(result.context)
        # Should mention what was found
        assert "believe" in context.lower() or "probably" in context.lower()

    def test_handle_with_no_transcript(self, handler: Any) -> None:
        """Handle with no transcript should still return ALLOW."""
        result = handler.handle({})
        assert result.decision == Decision.ALLOW


class TestGetLastAssistantMessageEdgeCases:
    """Test _get_last_assistant_message edge cases for coverage."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
            HedgingLanguageDetectorHandler,
        )

        return HedgingLanguageDetectorHandler()

    def test_skips_non_message_type(self, handler: Any) -> None:
        """Should skip JSONL entries with type != 'message'."""
        path = _make_transcript(
            [
                {"type": "tool_use", "tool": "Bash"},
                _assistant_message("I believe this is correct"),
            ]
        )
        # Should still find the assistant message after skipping tool_use
        result = handler._get_last_assistant_message(path)
        assert "I believe" in result

    def test_skips_non_message_type_only(self, handler: Any) -> None:
        """Should return empty string when only non-message types exist."""
        path = _make_transcript(
            [
                {"type": "tool_use", "tool": "Bash"},
                {"type": "tool_result", "output": "done"},
            ]
        )
        result = handler._get_last_assistant_message(path)
        assert result == ""

    def test_skips_non_assistant_role(self, handler: Any) -> None:
        """Should skip messages with non-assistant role."""
        path = _make_transcript(
            [
                _human_message("Tell me about the file"),
                {
                    "type": "message",
                    "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                },
            ]
        )
        result = handler._get_last_assistant_message(path)
        assert result == ""

    def test_handles_string_content_parts(self, handler: Any) -> None:
        """Should handle string content parts (not just dict text blocks)."""
        path = _make_transcript(
            [
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": ["I believe this is a string part", "and another"],
                    },
                }
            ]
        )
        result = handler._get_last_assistant_message(path)
        assert "I believe" in result
        assert "and another" in result

    def test_handles_malformed_jsonl_line(self, handler: Any) -> None:
        """Should continue past malformed JSONL lines."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write("this is not valid json\n")
        tmp.write(json.dumps(_assistant_message("I suspect something")) + "\n")
        tmp.flush()
        result = handler._get_last_assistant_message(tmp.name)
        assert "I suspect" in result

    def test_handles_oserror(self, handler: Any, tmp_path: Any) -> None:
        """Should return empty string on OSError."""
        # Use a directory path instead of a file to trigger OSError on open
        result = handler._get_last_assistant_message(str(tmp_path))
        assert result == ""

    def test_handles_unicode_decode_error(self, handler: Any, tmp_path: Any) -> None:
        """Should return empty string on UnicodeDecodeError."""
        binary_file = tmp_path / "transcript.jsonl"
        binary_file.write_bytes(b"\x80\x81\x82\x83\xff\xfe")
        result = handler._get_last_assistant_message(str(binary_file))
        assert result == ""

    def test_transcript_with_empty_lines(self, handler: Any) -> None:
        """Empty lines in JSONL are skipped."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write("\n")
        tmp.write("\n")
        tmp.write(json.dumps(_assistant_message("I believe this is right")) + "\n")
        tmp.write("\n")
        tmp.flush()
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: tmp.name}) is True

    def test_transcript_unexpected_exception(self, handler: Any) -> None:
        """Unexpected exception in transcript reading returns empty string."""
        from unittest.mock import patch as mock_patch

        with mock_patch(
            "claude_code_hooks_daemon.handlers.stop.hedging_language_detector.Path"
        ) as mock_path:
            mock_path.return_value.exists.side_effect = TypeError("unexpected")
            result = handler._get_last_assistant_message("/some/path")
            assert result == ""


class TestHedgingLanguageDetectorAcceptanceTests:
    """Test acceptance test definitions."""

    def test_has_acceptance_tests(self) -> None:
        """Handler should define acceptance tests."""
        from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
            HedgingLanguageDetectorHandler,
        )

        handler = HedgingLanguageDetectorHandler()
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0

    def test_acceptance_tests_have_titles(self) -> None:
        """Each acceptance test should have a title."""
        from claude_code_hooks_daemon.handlers.stop.hedging_language_detector import (
            HedgingLanguageDetectorHandler,
        )

        handler = HedgingLanguageDetectorHandler()
        tests = handler.get_acceptance_tests()
        for test in tests:
            assert hasattr(test, "title")
            assert test.title
