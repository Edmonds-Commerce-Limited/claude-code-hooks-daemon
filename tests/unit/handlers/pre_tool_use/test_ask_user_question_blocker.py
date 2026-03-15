"""Tests for AskUserQuestionBlockerHandler.

Optional handler that blocks AskUserQuestion to prevent progress-blocking
user prompts during unattended/batch workflows. Disabled by default.
"""

import pytest

from claude_code_hooks_daemon.core import HookResult


class TestAskUserQuestionBlockerHandler:
    """Test suite for AskUserQuestionBlockerHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.ask_user_question_blocker import (
            AskUserQuestionBlockerHandler,
        )

        return AskUserQuestionBlockerHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'block-ask-user-question'."""
        assert handler.name == "block-ask-user-question"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10 (safety range)."""
        assert handler.priority == 10

    def test_init_is_terminal(self, handler):
        """Handler should be terminal to stop dispatch chain."""
        assert handler.terminal is True

    # matches() - Positive Cases
    def test_matches_ask_user_question(self, handler):
        """Should match AskUserQuestion tool calls."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which approach?"}]},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases
    def test_matches_bash_returns_false(self, handler):
        """Should NOT match Bash tool calls."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_name_returns_false(self, handler):
        """Should not match when tool_name is missing."""
        hook_input = {"hook_event_name": "PreToolUse"}
        assert handler.matches(hook_input) is False

    def test_matches_none_tool_name_returns_false(self, handler):
        """Should not match when tool_name is None."""
        hook_input = {"hook_event_name": "PreToolUse", "tool_name": None}
        assert handler.matches(hook_input) is False

    # handle() Tests
    def test_handle_returns_deny(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which approach?"}]},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_says_blocked(self, handler):
        """handle() reason should say BLOCKED."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which?"}]},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_mentions_autonomously(self, handler):
        """handle() reason should tell Claude to decide autonomously."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which?"}]},
        }
        result = handler.handle(hook_input)
        assert "autonomously" in result.reason.lower()

    def test_handle_returns_hook_result(self, handler):
        """handle() should return HookResult instance."""
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "Which?"}]},
        }
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)
