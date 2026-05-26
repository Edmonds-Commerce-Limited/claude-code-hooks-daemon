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
        """Genuine re-entry (block marker present) MUST return False to prevent infinite loops."""
        # Write a transcript with a prior "Stop hook feedback:" user message —
        # this is the genuine re-entry shape Claude Code creates after a Stop
        # block. Without the marker, stop_hook_active=True is the silent-stop
        # bug shape and matches() must still fire (see
        # TestSilentStopAfterToolErrorReentryGuard).
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
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": ("Stop hook feedback:\nYou stopped without explaining why."),
                        },
                    }
                )
                + "\n"
            )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": True,  # Genuine re-entry — block marker confirms it
        }
        assert handler.matches(hook_input) is False

    def test_matches_true_when_no_transcript_path(self, handler: AutoContinueStopHandler) -> None:
        """Should return True when transcript_path is missing (handle() forces explanation)."""
        hook_input: dict[str, Any] = {"stop_hook_active": False}
        assert handler.matches(hook_input) is True

    def test_matches_true_when_transcript_path_empty(
        self, handler: AutoContinueStopHandler
    ) -> None:
        """Should return True when transcript_path is empty string (no AskUserQuestion detectable)."""
        hook_input = {"transcript_path": "", "stop_hook_active": False}
        assert handler.matches(hook_input) is True

    def test_matches_true_when_transcript_not_found(self, handler: AutoContinueStopHandler) -> None:
        """Should return True when transcript file does not exist (handle() forces explanation)."""
        hook_input = {
            "transcript_path": "/nonexistent/path/transcript.jsonl",
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_true_when_last_message_not_question(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return True when last message has no question mark (handle() routes to branch 4)."""
        self._write_transcript(
            mock_transcript_path,
            "I have completed the implementation",
            include_question=False,
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

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

    def test_matches_true_when_question_not_about_continuation(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return True when question is not about continuation (handle() routes to branch 4)."""
        self._write_transcript(
            mock_transcript_path, "What color scheme would you prefer for the UI"
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_true_when_no_assistant_messages(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return True when transcript has no assistant messages (no AskUserQuestion)."""
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
        assert handler.matches(hook_input) is True

    def test_matches_true_when_transcript_is_malformed_json(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return True when transcript contains malformed JSON (no AskUserQuestion found)."""
        with mock_transcript_path.open("w") as f:
            f.write("not valid json\n")
            f.write("{incomplete json\n")

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_true_when_transcript_is_empty(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Should return True when transcript file is empty (no AskUserQuestion found)."""
        mock_transcript_path.touch()  # Create empty file

        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True


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
        """Reason should be concise and clear (not overly verbose).

        The cap is generous (1000 chars) because the Branch 4 reason carries
        load-bearing guidance: STOPPING BECAUSE/AUTO-CONTINUE escape hatches
        plus the context-limit clause (Plan 00111) that tells the agent
        auto-compact handles context pressure. Anything beyond ~1000 chars
        would mean the reason has drifted into prose.
        """
        hook_input: dict[str, Any] = {}
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert len(result.reason) < 1000

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
        """With continue_on_errors=False, matches() still fires; handle() skips auto-continue."""
        self._write_transcript(
            mock_transcript_path,
            "Error: The test failed. Would you like me to continue with a different approach?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        # matches() always returns True now — routing moved to handle()
        assert handler_no_continue_on_errors.matches(hook_input) is True
        # handle() must NOT treat this as auto-continue (error + continue_on_errors=False)
        result = handler_no_continue_on_errors.handle(hook_input)
        assert result.decision == Decision.DENY
        reason = result.reason or ""
        assert "STOPPING BECAUSE" in reason or "AUTO-CONTINUE" in reason

    def test_disabled_continue_on_errors_blocks_on_failed(
        self, handler_no_continue_on_errors: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """With continue_on_errors=False, matches() still fires; handle() skips auto-continue."""
        self._write_transcript(
            mock_transcript_path,
            "Failed: build broke. Should I proceed with fixing it?",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        # matches() always returns True now — routing moved to handle()
        assert handler_no_continue_on_errors.matches(hook_input) is True
        # handle() must NOT treat this as auto-continue (error + continue_on_errors=False)
        result = handler_no_continue_on_errors.handle(hook_input)
        assert result.decision == Decision.DENY
        reason = result.reason or ""
        assert "STOPPING BECAUSE" in reason or "AUTO-CONTINUE" in reason

    def test_continue_on_errors_still_requires_question_mark(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Without a question mark the confirmation branch in handle() is not triggered."""
        self._write_transcript(
            mock_transcript_path,
            "Error: The test failed. I will try a different approach.",
        )
        hook_input = {
            "transcript_path": str(mock_transcript_path),
            "stop_hook_active": False,
        }
        # matches() always returns True — routing is in handle()
        assert handler.matches(hook_input) is True
        # handle() falls through to explain-or-continue branch (no question mark → no auto-continue)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "STOPPING BECAUSE" in (result.reason or "")

    def test_continue_on_errors_still_checks_stop_hook_active(
        self, handler: AutoContinueStopHandler, mock_transcript_path: Path
    ) -> None:
        """Genuine re-entry (block marker present) MUST return False to prevent infinite loops.

        Without a block marker, stop_hook_active=True alone is the silent-stop bug
        shape and matches() must still fire — see TestSilentStopAfterToolErrorReentryGuard.
        """
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
                                    "text": "An issue surfaced. Should I proceed?",
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": ("Stop hook feedback:\nYou stopped without explaining why."),
                        },
                    }
                )
                + "\n"
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
            # Now returns True on read error — routing (fail open) happens in handle()
            assert result is True
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
        # Now returns True on decode error — routing (fail open) happens in handle()
        assert handler.matches(hook_input) is True

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
                    "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": output}],
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

    def test_matches_true_when_transcript_not_found(self, handler: AutoContinueStopHandler) -> None:
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

    def test_handle_stopping_because_after_summary_returns_allow(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """'STOPPING BECAUSE:' on a later line (after summary content) → ALLOW.

        Regression test: Bug 1 from untracked/hooks-daemon-stopping-because.md.
        Assistants naturally summarise work before stating the stop reason, so
        the prefix appears on a non-first line of the message.
        """
        path = tmp_path / "t.jsonl"
        message = (
            "Both fixed:\n\n"
            "1. **`core.fileMode`** set to `true`\n"
            "2. **`.claude/worktrees/`** added to `.gitignore`\n\n"
            "STOPPING BECAUSE: both issues resolved."
        )
        self._write_assistant_text(path, message)
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_stopping_because_on_last_line_returns_allow(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """'STOPPING BECAUSE:' as the final line of a multi-line message → ALLOW."""
        path = tmp_path / "t.jsonl"
        message = "Done.\n\nAll QA passes.\n\nSTOPPING BECAUSE: task complete."
        self._write_assistant_text(path, message)
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_stopping_because_with_leading_whitespace_on_later_line_returns_allow(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """'STOPPING BECAUSE:' with leading whitespace on a non-first line → ALLOW."""
        path = tmp_path / "t.jsonl"
        message = "Summary of work done.\n\n  STOPPING BECAUSE: no more tasks."
        self._write_assistant_text(path, message)
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_stopping_because_in_second_content_block_returns_allow(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """'STOPPING BECAUSE:' at start of second content block → ALLOW.

        Regression test: When agent interleaves text + tool_use + text in one message,
        TranscriptReader joins text blocks with ' ' (space). If 'STOPPING BECAUSE:'
        starts the second block, it ends up mid-line after joining and the startswith
        check fails. Handler must check each content block individually.
        """
        path = tmp_path / "t.jsonl"
        msg = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Pushed. The flow is now:\n\n  No more stale data."},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}},
                    {"type": "text", "text": "STOPPING BECAUSE: SSH test flow cleaned up."},
                ],
            },
        }
        with path.open("w") as f:
            f.write(json.dumps(msg) + "\n")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_stopping_because_in_second_block_with_leading_whitespace_returns_allow(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """'STOPPING BECAUSE:' with leading whitespace in second block → ALLOW."""
        path = tmp_path / "t.jsonl"
        msg = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Work complete."},
                    {"type": "text", "text": "  STOPPING BECAUSE: all tasks done."},
                ],
            },
        }
        with path.open("w") as f:
            f.write(json.dumps(msg) + "\n")
        hook_input = {"transcript_path": str(path), "stop_hook_active": False}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    # ── handle() branch: race condition (thinking entry before text flushed) ────

    def test_has_stop_explanation_retries_when_last_message_is_thinking_only(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Race condition: last entry thinking-only, text flushed before retry → ALLOW.

        Simulates Claude Code writing the thinking entry first. The stop hook fires
        before the text entry is flushed to disk. The retry mechanism should reload
        the transcript and find the text entry with STOPPING BECAUSE:.
        """
        from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

        path = tmp_path / "t.jsonl"
        thinking_entry = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "thinking", "thinking": "I'm done, will write stop reason."}],
            },
        }
        with path.open("w") as f:
            f.write(json.dumps(thinking_entry) + "\n")

        # Load reader while only the thinking entry is in the file
        reader = TranscriptReader()
        reader.load(str(path))

        # Now append the text entry (simulating flush after initial read)
        text_entry = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "STOPPING BECAUSE: all work complete."}],
            },
        }
        with path.open("a") as f:
            f.write(json.dumps(text_entry) + "\n")

        # Retry must reload the file and find the text entry
        result = handler._has_stop_explanation(reader)
        assert result is True

    def test_has_stop_explanation_returns_false_when_thinking_only_after_retries(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Race condition: last entry is thinking-only and no text ever appears → False.

        When retries also yield thinking-only, _has_stop_explanation must return False
        so the stop is denied. Mocks sleep to avoid 150ms test latency.
        """
        from unittest.mock import patch

        from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

        path = tmp_path / "t.jsonl"
        thinking_entry = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "thinking", "thinking": "Hmm."}],
            },
        }
        with path.open("w") as f:
            f.write(json.dumps(thinking_entry) + "\n")

        reader = TranscriptReader()
        reader.load(str(path))

        with patch("claude_code_hooks_daemon.handlers.stop.auto_continue_stop.time.sleep"):
            result = handler._has_stop_explanation(reader)
        assert result is False

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


class TestBranch3StaleReaderRace:
    """Tests for the stale-reader race condition in Branch 3 (confirmation question).

    Bug: handle() creates a reader once at the top. Branch 2 (_has_stop_explanation)
    has retry logic that reloads the transcript, but the fresh data doesn't propagate
    to Branch 3. Branch 3 reads stale data from the original reader and never detects
    confirmation questions that were flushed after the initial reader was created.

    Result: Branch 3 NEVER fires — 88 stop events logged, zero auto-continues.
    """

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    def test_confirmation_question_detected_after_late_transcript_flush(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Branch 3 should detect confirmation question even when initial read was stale.

        Scenario:
        1. Stop fires before text block is written (only thinking block in transcript)
        2. During Branch 2 retries, the text block flushes with a confirmation question
        3. Branch 2 returns False (no STOPPING BECAUSE:)
        4. Branch 3 MUST detect the confirmation question from fresh transcript data

        Without the fix, Branch 3 uses the original stale reader and misses the question.
        """
        from unittest.mock import patch

        transcript_path = tmp_path / "transcript.jsonl"

        # Initial transcript: user prompt, then assistant with NO text blocks yet
        initial_messages = [
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "implement the feature"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "tu_1", "name": "Write", "input": {}}],
                },
            },
        ]
        with transcript_path.open("w") as f:
            for msg in initial_messages:
                f.write(json.dumps(msg) + "\n")

        # Simulate text flushing during Branch 2 retries
        flush_done = [False]

        def mock_sleep(_duration: float) -> None:
            if not flush_done[0]:
                flush_done[0] = True
                # Rewrite transcript with the text block now present
                updated_messages = [
                    {
                        "type": "message",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "implement the feature"}],
                        },
                    },
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tu_1",
                                    "name": "Write",
                                    "input": {},
                                },
                                {
                                    "type": "text",
                                    "text": "I've implemented the feature. Would you like me to continue with the tests?",
                                },
                            ],
                        },
                    },
                ]
                with transcript_path.open("w") as f:
                    for msg in updated_messages:
                        f.write(json.dumps(msg) + "\n")

        hook_input: dict[str, Any] = {
            "transcript_path": str(transcript_path),
            "stop_hook_active": False,
        }

        with patch(
            "claude_code_hooks_daemon.handlers.stop.auto_continue_stop.time.sleep",
            side_effect=mock_sleep,
        ):
            result = handler.handle(hook_input)

        # Should be Branch 3 (AUTO-CONTINUE: Yes, proceed), NOT Branch 4
        # Branch 4 starts with "You stopped without explaining" — distinct from Branch 3
        assert result.decision == Decision.DENY
        reason = result.reason or ""
        assert reason.startswith(
            "AUTO-CONTINUE: Yes, proceed"
        ), f"Expected Branch 3 auto-continue but got: {reason[:80]}"

    def test_confirmation_in_fresh_transcript_after_user_as_last_message(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Branch 3 detects confirmation when initial transcript had user as last message.

        Scenario:
        1. Stop fires before new assistant message is written
        2. Transcript shows: [old assistant], [user] — user is last
        3. During retries, new assistant message with confirmation question flushes
        4. Branch 3 must detect it
        """
        from unittest.mock import patch

        transcript_path = tmp_path / "transcript.jsonl"

        # Initial: user is last message (stale — new assistant turn not written yet)
        initial_messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I completed the work."}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "now do the tests"}],
                },
            },
        ]
        with transcript_path.open("w") as f:
            for msg in initial_messages:
                f.write(json.dumps(msg) + "\n")

        flush_done = [False]

        def mock_sleep(_duration: float) -> None:
            if not flush_done[0]:
                flush_done[0] = True
                # New assistant message appears
                fresh_msg = {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "Should I proceed with writing the integration tests?",
                            }
                        ],
                    },
                }
                with transcript_path.open("a") as f:
                    f.write(json.dumps(fresh_msg) + "\n")

        hook_input: dict[str, Any] = {
            "transcript_path": str(transcript_path),
            "stop_hook_active": False,
        }

        with patch(
            "claude_code_hooks_daemon.handlers.stop.auto_continue_stop.time.sleep",
            side_effect=mock_sleep,
        ):
            result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        reason = result.reason or ""
        assert reason.startswith(
            "AUTO-CONTINUE: Yes, proceed"
        ), f"Expected Branch 3 auto-continue but got: {reason[:80]}"


class TestHasStopExplanationStaleTranscriptRace:
    """Tests for the stale-transcript race condition in _has_stop_explanation().

    Race condition scenario:
    1. Turn N: Claude says "STOPPING BECAUSE: task done" → stop allowed.
    2. User sends new prompt; Claude starts a new turn.
    3. Second stop fires BEFORE Claude writes any new assistant content.
    4. get_last_assistant_message() returns the OLD turn-N message.
    5. Without the fix, _has_stop_explanation() incorrectly returns True.
    """

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    def test_stale_explanation_from_previous_turn_not_accepted(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """STOPPING BECAUSE: in old turn must not satisfy current stop event.

        Race condition: stop fires before new assistant message is written.
        Transcript has user message after old 'STOPPING BECAUSE:' assistant
        message, but no new assistant message yet. Must return False.
        """
        from unittest.mock import patch

        from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

        transcript_path = tmp_path / "transcript.jsonl"
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "STOPPING BECAUSE: task complete"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "please continue"}],
                },
            },
            # No new assistant message — new turn not written yet
        ]
        with transcript_path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        reader = TranscriptReader()
        reader.load(str(transcript_path))

        # Patch sleep so retries are instant (all retries will still see user as last)
        with patch("claude_code_hooks_daemon.handlers.stop.auto_continue_stop.time.sleep"):
            result = handler._has_stop_explanation(reader)

        assert (
            result is False
        ), "STOPPING BECAUSE: from previous turn should not satisfy current stop"

    def test_explanation_in_current_turn_accepted(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """STOPPING BECAUSE: in current turn (no user msg after it) is valid."""
        from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

        transcript_path = tmp_path / "transcript.jsonl"
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "do the work"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "STOPPING BECAUSE: all done"}],
                },
            },
            # Last message IS assistant — fresh, not stale
        ]
        with transcript_path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        reader = TranscriptReader()
        reader.load(str(transcript_path))

        result = handler._has_stop_explanation(reader)

        assert result is True

    def test_stale_then_fresh_assistant_message_accepted_on_retry(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Stale transcript at first read, fresh assistant message appears on retry.

        Simulates the transcript being updated between the initial load and the
        retry: initial state has user as last message, but by the time retry
        reloads the file a new assistant message with STOPPING BECAUSE: exists.
        """
        from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader

        transcript_path = tmp_path / "transcript.jsonl"

        # Initial state: last message is user (no new assistant yet)
        initial_messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "STOPPING BECAUSE: old turn"}],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "continue"}],
                },
            },
        ]
        with transcript_path.open("w") as f:
            for msg in initial_messages:
                f.write(json.dumps(msg) + "\n")

        reader = TranscriptReader()
        reader.load(str(transcript_path))

        # Append fresh assistant message BEFORE retries run (file already updated)
        fresh_msg = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "STOPPING BECAUSE: new turn done"}],
            },
        }
        with transcript_path.open("a") as f:
            f.write(json.dumps(fresh_msg) + "\n")

        # Retry must reload and find the fresh assistant message
        result = handler._has_stop_explanation(reader)

        assert result is True


class TestSilentStopAfterToolErrorReentryGuard:
    """Tests for Plan 00101 incident — silent stop after tool error / empty turn.

    Bug: Claude Code sets stop_hook_active=true on at least some abnormal-stop
    paths (e.g. silent stop after a failed Edit with no following assistant
    text). The handler's re-entry guard treats stop_hook_active=true as proof
    of legitimate Stop-hook re-entry and returns matches()=False, so the daemon
    returns {} (allow) and the user has to manually intervene.

    Fix: matches() must additionally require evidence of a recent prior Stop
    hook block in the transcript before honouring stop_hook_active=true.
    Markers of a real prior block:
      - user-role JSONL entry whose message.content begins with
        "Stop hook feedback:"
      - attachment entry of type "hook_blocking_error" with hookEvent=Stop
    Either marker, present in the recent tail of the transcript, signals a
    genuine re-entry. Absence signals the silent-stop bug.
    """

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        """Create handler instance."""
        return AutoContinueStopHandler()

    def _write_lines(self, path: Path, lines: list[dict[str, Any]]) -> None:
        with path.open("w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    # ── BUG REGRESSION ──────────────────────────────────────────────────────

    def test_matches_true_when_stop_hook_active_but_no_prior_block_with_tool_error(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """REGRESSION (Plan 00101 incident 2026-04-29):

        stop_hook_active=true + previous turn was tool_use Edit with tool_result
        is_error=true + NO prior Stop hook block in transcript.

        Old behaviour: matches() returned False (re-entry guard tripped) →
        daemon returned {} → user had to intervene manually.

        New behaviour: matches() must return True so handle() runs and (in
        default config) blocks with the explain-or-continue message.
        """
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {
                                    "file_path": "/workspace/some/file.md",
                                    "old_string": "x",
                                    "new_string": "y",
                                },
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "is_error": True,
                                "content": (
                                    "<tool_use_error>"
                                    "File has not been read yet"
                                    "</tool_use_error>"
                                ),
                                "tool_use_id": "tu_1",
                            }
                        ],
                    },
                },
            ],
        )
        hook_input = {
            "transcript_path": str(path),
            "stop_hook_active": True,
        }
        # Bug: handler currently returns False; after fix must return True.
        assert handler.matches(hook_input) is True

    def test_matches_true_when_stop_hook_active_after_tool_success_empty_turn(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Silent stop after a SUCCESSFUL Edit with no following assistant text.

        This is the original L685 / L1301 / L1394 bug shape: tool_use Edit →
        tool_result success → empty assistant turn → Stop fires with
        stop_hook_active=true. Without a prior Stop block in the transcript,
        the handler must NOT silently allow the stop.
        """
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Edit",
                                "input": {
                                    "file_path": "/workspace/some/file.py",
                                    "old_string": "old",
                                    "new_string": "new",
                                },
                            }
                        ],
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "is_error": False,
                                "content": "File updated successfully.",
                                "tool_use_id": "tu_1",
                            }
                        ],
                    },
                },
            ],
        )
        hook_input = {
            "transcript_path": str(path),
            "stop_hook_active": True,
        }
        assert handler.matches(hook_input) is True

    # ── GENUINE RE-ENTRY (must still pass through) ──────────────────────────

    def test_matches_false_when_stop_hook_active_with_prior_feedback_message(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Genuine re-entry: prior 'Stop hook feedback:' user message in tail.

        This is the original infinite-loop-prevention scenario. After a Stop
        hook block, Claude Code re-fires Stop with stop_hook_active=true, and
        the transcript contains the injected 'Stop hook feedback:' user
        message that proves a real prior block existed. Handler must return
        False to prevent infinite loops.
        """
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": (
                            "Stop hook feedback:\n"
                            "You stopped without explaining why. "
                            "Either:\n1. Prefix your stop message..."
                        ),
                    },
                },
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "STOPPING BECAUSE: my work is complete.",
                            }
                        ],
                    },
                },
            ],
        )
        hook_input = {
            "transcript_path": str(path),
            "stop_hook_active": True,
        }
        assert handler.matches(hook_input) is False

    def test_matches_false_when_stop_hook_active_with_prior_blocking_attachment(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Genuine re-entry detected via hook_blocking_error attachment marker."""
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "attachment",
                    "attachment": {
                        "type": "hook_blocking_error",
                        "hookName": "Stop",
                        "hookEvent": "Stop",
                        "blockingError": {"blockingError": "You stopped..."},
                    },
                },
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "STOPPING BECAUSE: done."}],
                    },
                },
            ],
        )
        hook_input = {
            "transcript_path": str(path),
            "stop_hook_active": True,
        }
        assert handler.matches(hook_input) is False

    # ── stop_hook_active=false unchanged ────────────────────────────────────

    def test_matches_true_when_stop_hook_active_false_and_no_block_marker(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """stop_hook_active=false → always matches (handle() routes)."""
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "I am done"}],
                    },
                },
            ],
        )
        hook_input = {
            "transcript_path": str(path),
            "stop_hook_active": False,
        }
        assert handler.matches(hook_input) is True

    def test_matches_true_when_stop_hook_active_but_transcript_missing(
        self, handler: AutoContinueStopHandler
    ) -> None:
        """stop_hook_active=true with no transcript_path → cannot prove prior
        block exists → must NOT silently allow.

        This protects against the bug shape where Claude Code sets
        stop_hook_active=true but no transcript info is available.
        """
        hook_input = {"stop_hook_active": True}
        # No transcript_path provided → has_recent_stop_hook_block returns
        # False → matches must return True
        assert handler.matches(hook_input) is True


class TestAutoContinueStopGetClaudeMdGuidance:
    """Plan 00101 Phase 5: get_claude_md() must teach tool_use_error recovery.

    The 2026-05-02 silent-stop incident showed a recurring failure mode:
    the agent calls Edit on a file it has not Read, Claude Code returns a
    tool_use_error, and the agent stops with no output. The daemon-side
    fix (Plan 00102 has_recent_stop_hook_block guard) ensures the Stop
    hook fires on re-entry — but the model still needs explicit guidance
    on how to recover. This test class asserts that guidance is now
    present in the handler's get_claude_md() output.
    """

    def test_guidance_mentions_read_before_edit(self) -> None:
        """get_claude_md() must remind agents to Read before Edit/Write."""
        handler = AutoContinueStopHandler()
        guidance = handler.get_claude_md() or ""
        guidance_lower = guidance.lower()
        assert "read" in guidance_lower and "edit" in guidance_lower, (
            "get_claude_md() must mention Read-before-Edit to prevent the "
            "tool_use_error-then-silent-stop incident shape. "
            f"Current guidance: {guidance!r}"
        )
        assert "read before edit" in guidance_lower or (
            "read the file" in guidance_lower and "edit" in guidance_lower
        ), (
            "get_claude_md() must explicitly state the Read-before-Edit "
            "rule (substring 'read before edit' or 'read the file ... edit'). "
            f"Current guidance: {guidance!r}"
        )

    def test_guidance_mentions_tool_use_error_recovery(self) -> None:
        """get_claude_md() must teach: on tool_use_error, retry — do NOT stop."""
        handler = AutoContinueStopHandler()
        guidance = handler.get_claude_md() or ""
        guidance_lower = guidance.lower()
        assert "tool_use_error" in guidance_lower or "tool error" in guidance_lower, (
            "get_claude_md() must mention tool_use_error/tool error explicitly "
            "so agents recognise the recovery branch. "
            f"Current guidance: {guidance!r}"
        )
        assert "do not stop" in guidance_lower or "do not silently stop" in guidance_lower, (
            "get_claude_md() must instruct agents NOT to stop on tool error — "
            "the recovery action is to retry, not to halt. "
            f"Current guidance: {guidance!r}"
        )

    def test_guidance_mentions_reentry_stopping_because(self) -> None:
        """get_claude_md() must say re-entry responses ALSO need STOPPING BECAUSE:.

        When the Stop hook re-fires after blocking, the agent's next response
        must still prefix with STOPPING BECAUSE: if it intends to stop —
        otherwise the loop continues. Tell the agent that explicitly.
        """
        handler = AutoContinueStopHandler()
        guidance = handler.get_claude_md() or ""
        guidance_lower = guidance.lower()
        assert (
            "re-entry" in guidance_lower
            or "re-fires" in guidance_lower
            or ("stop hook fires again" in guidance_lower)
        ), (
            "get_claude_md() must mention Stop hook re-entry/re-fire so the "
            "agent knows the same STOPPING BECAUSE: rule applies on subsequent "
            f"stops. Current guidance: {guidance!r}"
        )


class TestAutoContinueStopAfterToolUseError:
    """Plan 00101 Phase 6: handle() must emit a specific recovery reason after
    a tool_use_error, not the generic explain-or-continue text.

    Bug shape (recurring): agent calls Edit on a file it hasn't Read, Claude
    Code returns tool_result is_error=true ("File has not been read yet"),
    agent stops silently. Plan 00102's matches()-side guard ensures handle()
    runs. This phase strengthens handle() to emit a *specific* recovery
    instruction (Read the file, retry) so the model has a clear next action.

    Three cases:
      A. tool_use Edit → tool_result is_error=true + silent turn → DENY with
         tool-error recovery reason (NOT generic explain-or-continue).
      B. Same shape + STOPPING BECAUSE: assistant text → ALLOW (Branch 2 wins).
      C. tool_use Edit → tool_result success + silent turn → existing default
         Branch 4 fires (no regression — only fires on actual is_error=true).
    """

    @pytest.fixture
    def handler(self) -> AutoContinueStopHandler:
        return AutoContinueStopHandler()

    def _write_lines(self, path: Path, lines: list[dict[str, Any]]) -> None:
        with path.open("w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    def _tool_use_edit_block(self) -> dict[str, Any]:
        return {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "Edit",
                        "input": {
                            "file_path": "/workspace/some/file.py",
                            "old_string": "old",
                            "new_string": "new",
                        },
                    }
                ],
            },
        }

    def _tool_result_block(self, *, is_error: bool, text: str) -> dict[str, Any]:
        return {
            "type": "message",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "is_error": is_error,
                        "content": text,
                        "tool_use_id": "tu_1",
                    }
                ],
            },
        }

    def test_case_a_tool_use_error_silent_turn_emits_recovery_reason(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Case A: tool_use_error + silent stop → specific recovery reason.

        The DENY reason must name the tool error and the recovery action
        (Read the file, retry) — NOT the generic explain-or-continue text.
        """
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                self._tool_use_edit_block(),
                self._tool_result_block(
                    is_error=True,
                    text="<tool_use_error>File has not been read yet</tool_use_error>",
                ),
            ],
        )
        hook_input = {"transcript_path": str(path)}
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY, f"Case A must DENY (block stop). Got: {result}"
        reason = (result.reason or "").lower()
        assert "tool_use_error" in reason or "tool error" in reason, (
            "Case A reason must name the tool error explicitly. " f"Got reason: {result.reason!r}"
        )
        assert "retry" in reason or "read the file" in reason, (
            "Case A reason must instruct the agent to retry (Read + retry). "
            f"Got reason: {result.reason!r}"
        )
        assert "stopped without explaining" not in reason, (
            "Case A must NOT fall through to the generic explain-or-continue "
            f"reason. Got reason: {result.reason!r}"
        )

    def test_case_b_stopping_because_overrides_tool_error_branch(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Case B: tool_use_error + assistant STOPPING BECAUSE: → ALLOW.

        Branch 2 (explicit explanation) must win over the new tool-error
        recovery branch. The agent has explained the stop — let it stop.
        """
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                self._tool_use_edit_block(),
                self._tool_result_block(
                    is_error=True,
                    text="<tool_use_error>File has not been read yet</tool_use_error>",
                ),
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "STOPPING BECAUSE: file is read-only "
                                    "and edit is genuinely impossible."
                                ),
                            }
                        ],
                    },
                },
            ],
        )
        hook_input = {"transcript_path": str(path)}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW, (
            "Case B: STOPPING BECAUSE: must override the tool-error branch. " f"Got: {result}"
        )

    def test_case_c_tool_result_success_silent_turn_uses_default_branch(
        self, handler: AutoContinueStopHandler, tmp_path: Path
    ) -> None:
        """Case C: tool_result success + silent stop → existing default branch.

        Regression guard: the new branch must trigger ONLY on is_error=true.
        A successful tool result followed by a silent stop must continue to
        fire the existing explain-or-continue default (Branch 4), not the
        new tool-error recovery reason.
        """
        path = tmp_path / "transcript.jsonl"
        self._write_lines(
            path,
            [
                self._tool_use_edit_block(),
                self._tool_result_block(
                    is_error=False,
                    text="File edited successfully",
                ),
            ],
        )
        hook_input = {"transcript_path": str(path)}
        result = handler.handle(hook_input)

        assert (
            result.decision == Decision.DENY
        ), f"Case C must still DENY (existing default branch). Got: {result}"
        reason = (result.reason or "").lower()
        assert "tool_use_error" not in reason and "tool error" not in reason, (
            "Case C must NOT trigger the tool-error recovery branch — "
            f"is_error was False. Got reason: {result.reason!r}"
        )


class TestExplainOrContinueReasonContent:
    """Pin the wording of the Branch 4 explain-or-continue reason (Plan 00111).

    The user reported a dogfooding failure: the agent voluntarily stops near
    the context-window limit, believing it needs to "checkpoint" before
    auto-compact. Claude Code's auto-compact triggers automatically — the
    correct behaviour is to keep working. The Branch 4 message must say so
    explicitly so the agent self-corrects on the re-entry turn.
    """

    def test_reason_contains_explicit_context_limit_guidance(self) -> None:
        """The Branch 4 reason must explicitly forbid context-limit stops."""
        from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
            _EXPLAIN_OR_CONTINUE_REASON,
        )

        reason_lower = _EXPLAIN_OR_CONTINUE_REASON.lower()
        assert "auto-compact" in reason_lower or "auto compact" in reason_lower, (
            "Branch 4 reason must mention auto-compact so the agent knows "
            "Claude Code handles context pressure automatically. "
            f"Got: {_EXPLAIN_OR_CONTINUE_REASON!r}"
        )
        assert "context" in reason_lower, (
            "Branch 4 reason must mention the context window/limit so the "
            "context-checkpoint failure mode is addressed by name. "
            f"Got: {_EXPLAIN_OR_CONTINUE_REASON!r}"
        )

    def test_reason_retains_existing_explain_or_continue_clauses(self) -> None:
        """Existing STOPPING BECAUSE / AUTO-CONTINUE guidance must remain."""
        from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
            _EXPLAIN_OR_CONTINUE_REASON,
        )

        assert (
            "STOPPING BECAUSE:" in _EXPLAIN_OR_CONTINUE_REASON
        ), "Branch 4 reason must keep the STOPPING BECAUSE: prefix guidance."
        assert (
            "AUTO-CONTINUE" in _EXPLAIN_OR_CONTINUE_REASON
        ), "Branch 4 reason must keep the AUTO-CONTINUE escape hatch."
