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

    # Tests for patterns ported from php-qa-ci (Phase 2)
    def test_matches_let_me_know_if_you_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'let me know if you' pattern (ported from php-qa-ci)."""
        self._write_transcript(
            mock_transcript_path, "Let me know if you want me to continue with phase 2"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_want_me_to_go_ahead_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'want me to go ahead' pattern (ported from php-qa-ci)."""
        self._write_transcript(
            mock_transcript_path, "Do you want me to go ahead and implement the changes"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_want_me_to_keep_going_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'want me to keep going' pattern (ported from php-qa-ci)."""
        self._write_transcript(
            mock_transcript_path, "Do you want me to keep going with the refactoring"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_if_youd_like_to_continue_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'if you'd like' pattern (ported from php-qa-ci)."""
        self._write_transcript(
            mock_transcript_path, "If you'd like me to continue, I can proceed with the next step"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_i_can_continue_with_pattern(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should match 'I can continue with' pattern (ported from php-qa-ci)."""
        self._write_transcript(
            mock_transcript_path, "I can continue with implementing the remaining features"
        )
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

    def test_matches_true_when_last_message_is_error_report_default(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """With default continue_on_errors=True, error reports with questions DO match."""
        self._write_transcript(
            mock_transcript_path,
            "Error: The test failed. What would you like me to do",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        # With continue_on_errors=True (default), this SHOULD match
        assert handler.matches(hook_input) is True

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


class TestAutoContinueStopHandlerAskUserQuestion:
    """Test AskUserQuestion bug fix - handler must NOT auto-continue when Claude used AskUserQuestion.

    Bug: When Claude calls AskUserQuestion, the text content often contains
    confirmation-like phrasing ("Would you like...") which matches the handler's
    patterns. The handler would block the Stop and tell Claude to continue,
    meaning the user never sees the question.

    Fix: If the last assistant message contains a tool_use block for AskUserQuestion,
    matches() must return False regardless of text content.
    """

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    @pytest.fixture
    def mock_transcript_path(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file path."""
        return tmp_path / "transcript.jsonl"

    def test_matches_false_when_ask_user_question_used(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """CRITICAL BUG FIX: Must return False when AskUserQuestion was used."""
        with mock_transcript_path.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Would you like me to continue with approach A or B?",
                                },
                                {
                                    "type": "tool_use",
                                    "name": "AskUserQuestion",
                                    "input": {"question": "Which approach?"},
                                },
                            ],
                        },
                    }
                )
                + "\n"
            )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False

    def test_matches_true_when_confirmation_without_ask_user(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should still match confirmation questions that DON'T use AskUserQuestion."""
        with mock_transcript_path.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Would you like me to continue with the next phase?",
                                },
                            ],
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

    def test_matches_false_when_ask_user_with_shall_i_proceed(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """AskUserQuestion with 'shall I proceed' text must not auto-continue."""
        with mock_transcript_path.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Shall I proceed with the deployment?",
                                },
                                {
                                    "type": "tool_use",
                                    "name": "AskUserQuestion",
                                    "input": {"question": "Deploy now?"},
                                },
                            ],
                        },
                    }
                )
                + "\n"
            )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False


class TestAutoContinueStopContinueOnErrors:
    """Test continue_on_errors option - auto-continue even when error patterns detected.

    When continue_on_errors is True (default), the handler should auto-continue
    even when Claude's message contains error patterns like "error:", "failed:".
    This prevents sessions from blocking until the user comes back and says "go".

    When continue_on_errors is False, the handler preserves the original behavior
    of NOT auto-continuing on error messages.
    """

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance (default: continue_on_errors=True)."""
        return AutoContinueStopHandler()

    @pytest.fixture
    def handler_no_continue_on_errors(self) -> AutoContinueStopHandler:
        """Create handler with continue_on_errors disabled."""
        handler = AutoContinueStopHandler()
        handler._continue_on_errors = False
        return handler

    @pytest.fixture
    def mock_transcript_path(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file path."""
        return tmp_path / "transcript.jsonl"

    def _write_transcript(self, path: Path, assistant_text: str) -> None:
        """Write a mock transcript with an assistant message."""
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_text}],
                },
            }
        ]
        with path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

    def test_default_continue_on_errors_is_true(self, handler: AutoContinueStopHandler) -> None:
        """Default value of continue_on_errors should be True."""
        assert getattr(handler, "_continue_on_errors", True) is True

    def test_continue_on_errors_matches_error_with_confirmation(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """With continue_on_errors=True, should match even when error pattern present."""
        self._write_transcript(
            mock_transcript_path,
            "Error: The test failed. Would you like me to continue with a different approach?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_continue_on_errors_matches_failed_with_should_i(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """With continue_on_errors=True, should match 'failed:' + 'should I proceed'."""
        self._write_transcript(
            mock_transcript_path,
            "Failed: the build did not compile. Should I proceed with fixing the issue?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_continue_on_errors_matches_how_should_i_proceed(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """With continue_on_errors=True, should match 'how should I proceed' error pattern."""
        self._write_transcript(
            mock_transcript_path,
            "The command exited with code 1. How should I proceed?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_continue_on_errors_matches_what_would_you_like(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """With continue_on_errors=True, should match 'what would you like me to do'."""
        self._write_transcript(
            mock_transcript_path,
            "The test suite has 3 failures. What would you like me to do?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_disabled_continue_on_errors_blocks_on_error(
        self, handler_no_continue_on_errors: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """With continue_on_errors=False, should NOT match when error pattern present."""
        self._write_transcript(
            mock_transcript_path,
            "Error: The test failed. Would you like me to continue with a different approach?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler_no_continue_on_errors.matches(hook_input) is False

    def test_disabled_continue_on_errors_blocks_on_failed(
        self, handler_no_continue_on_errors: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """With continue_on_errors=False, should NOT match when failed pattern present."""
        self._write_transcript(
            mock_transcript_path,
            "Failed: build broke. Should I proceed with fixing it?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler_no_continue_on_errors.matches(hook_input) is False

    def test_continue_on_errors_still_requires_question_mark(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Even with continue_on_errors=True, message must contain a question mark."""
        self._write_transcript(
            mock_transcript_path,
            "Error: The test failed. I will try a different approach.",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False

    def test_continue_on_errors_still_checks_stop_hook_active(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Even with continue_on_errors=True, stop_hook_active must prevent infinite loops."""
        self._write_transcript(
            mock_transcript_path,
            "Error: something broke. Should I proceed?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": True,
        }
        assert handler.matches(hook_input) is False

    def test_continue_on_errors_handle_gives_diagnostic_instruction(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """When auto-continuing on errors, handle() should instruct to diagnose and fix."""
        # Simulate that the handler matched on an error message
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None

    def test_continue_on_errors_still_respects_ask_user_question(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Even with continue_on_errors=True, AskUserQuestion must still block."""
        with mock_transcript_path.open("w") as f:
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Error: test failed. Would you like me to continue?",
                                },
                                {
                                    "type": "tool_use",
                                    "name": "AskUserQuestion",
                                    "input": {"question": "What to do?"},
                                },
                            ],
                        },
                    }
                )
                + "\n"
            )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is False


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

        def mock_open(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Unexpected error")

        monkeypatch.setattr(Path, "open", mock_open)

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        # After Plan 00094: matches() always returns True unless stop_hook_active=True or
        # AskUserQuestion was used. On read error, reader is empty → True.
        assert handler.matches(hook_input) is True


class TestAutoContinueStopHandlerExplainerBehaviours:
    """Tests for stop-explainer and QA-failure auto-continue (Plan 00094).

    New behaviours added by Plan 00094:
    - matches() always returns True when stop_hook_active=False (except AskUserQuestion)
    - QA tool failures → DENY: "fix failures and continue"
    - "STOPPING BECAUSE:" prefix in last message → ALLOW
    - No transcript / unclear stop → DENY: "explain or continue"
    """

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    def _write_bash_and_result(self, path: Path, command: str, output: str) -> None:
        """Write transcript with a Bash tool_use followed by a tool_result."""
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu_1",
                            "name": "Bash",
                            "input": {"command": command},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1", "content": output}
                    ],
                },
            },
        ]
        with path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

    def _write_assistant_text(self, path: Path, text: str) -> None:
        """Write transcript with a single assistant text message."""
        msg = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            },
        }
        with path.open("w") as f:
            f.write(json.dumps(msg) + "\n")

    # ── matches() always-True tests ──────────────────────────────────────────

    def test_matches_true_when_no_transcript(self, handler: AutoContinueStopHandler) -> None:
        """No transcript_path → matches=True; handle() will force explanation."""
        hook_input: dict[str, Any] = {"stop_hook_active": False}
        assert handler.matches(hook_input) is True

    def test_matches_true_when_transcript_not_found(
        self, handler: AutoContinueStopHandler
    ) -> None:
        """Non-existent transcript file → matches=True."""
        hook_input = {
            "transcript_path": "/nonexistent/no-such-file.jsonl",
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_true_when_no_question_mark(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Statement without '?' → matches=True (old: False). handle() forces explanation."""
        path = tmp_path / "t.jsonl"
        self._write_assistant_text(path, "I have completed the implementation.")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        assert handler.matches(hook_input) is True

    def test_matches_true_when_unrelated_question(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Non-continuation question → matches=True. handle() forces explanation."""
        path = tmp_path / "t.jsonl"
        self._write_assistant_text(path, "What colour scheme would you prefer for the UI?")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        assert handler.matches(hook_input) is True

    # ── handle() branch: QA failure ─────────────────────────────────────────

    def test_handle_pytest_failure_returns_deny(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """pytest FAILED output → DENY with fix instruction."""
        path = tmp_path / "t.jsonl"
        self._write_bash_and_result(
            path,
            "pytest tests/ -v",
            "FAILED tests/test_foo.py::test_bar - AssertionError\n2 failed, 3 passed",
        )
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_pytest_failure_reason_mentions_fix(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """pytest failure reason should mention fixing failures."""
        path = tmp_path / "t.jsonl"
        self._write_bash_and_result(
            path,
            "pytest tests/ -v",
            "FAILED tests/test_foo.py::test_bar\n1 failed, 0 passed",
        )
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.reason is not None
        reason_lower = result.reason.lower()
        assert "fix" in reason_lower or "fail" in reason_lower

    def test_handle_run_all_sh_failure_returns_deny(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """./scripts/qa/run_all.sh FAILED → DENY with fix instruction."""
        path = tmp_path / "t.jsonl"
        self._write_bash_and_result(
            path,
            "./scripts/qa/run_all.sh",
            "Format Check   : FAILED\nOverall Status : FAILED",
        )
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        reason_lower = result.reason.lower()
        assert "fix" in reason_lower or "fail" in reason_lower

    def test_handle_qa_pass_does_not_trigger_qa_branch(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """pytest all passing → NOT the QA-fail branch (falls to explain-or-continue)."""
        path = tmp_path / "t.jsonl"
        self._write_bash_and_result(path, "pytest tests/ -v", "5 passed in 0.5s")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "qa fail" not in result.reason.lower()

    def test_handle_non_qa_bash_does_not_trigger_qa_branch(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """A non-QA Bash command (echo) → NOT the QA-fail branch."""
        path = tmp_path / "t.jsonl"
        self._write_bash_and_result(path, "echo hello", "hello")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "qa fail" not in result.reason.lower()

    # ── handle() branch: STOPPING BECAUSE ───────────────────────────────────

    def test_handle_stopping_because_prefix_returns_allow(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """'STOPPING BECAUSE:' prefix in last message → ALLOW."""
        path = tmp_path / "t.jsonl"
        self._write_assistant_text(path, "STOPPING BECAUSE: all tasks complete and QA passes.")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_stopping_because_lowercase_does_not_match(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Lowercase 'stopping because' does NOT match prefix → DENY (force explanation)."""
        path = tmp_path / "t.jsonl"
        self._write_assistant_text(path, "I am stopping because the task is done.")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_stopping_because_with_whitespace_returns_allow(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """'STOPPING BECAUSE:' with leading whitespace still returns ALLOW."""
        path = tmp_path / "t.jsonl"
        self._write_assistant_text(path, "  STOPPING BECAUSE: work is complete.")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    # ── handle() branch: no transcript (force explanation) ───────────────────

    def test_handle_no_transcript_returns_deny(self, handler: AutoContinueStopHandler) -> None:
        """No transcript → DENY with explain-or-continue message."""
        hook_input: dict[str, Any] = {"stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_handle_no_transcript_reason_contains_stopping_because_hint(
        self, handler: AutoContinueStopHandler
    ) -> None:
        """Explain-or-continue reason should hint at STOPPING BECAUSE: protocol."""
        hook_input: dict[str, Any] = {"stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert "STOPPING BECAUSE" in result.reason
