"""Comprehensive tests for TaskCompletionCheckerHandler."""

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.stop.task_completion_checker import (
    TaskCompletionCheckerHandler,
)


class TestTaskCompletionCheckerHandler:
    """Test suite for TaskCompletionCheckerHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return TaskCompletionCheckerHandler()

    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'task-completion-checker'."""
        assert handler.name == "task-completion-checker"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 50."""
        assert handler.priority == 50

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal."""
        assert handler.terminal is False

    def test_matches_always_returns_true(self, handler):
        """Should match all stop events."""
        hook_input = {"reason": "user_request"}
        assert handler.matches(hook_input) is True

    def test_handle_provides_completion_reminder(self, handler):
        """Should provide task completion reminder context."""
        hook_input = {"reason": "user_request"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context).lower()
        assert "completion" in context_text

    def test_handle_has_no_reason(self, handler):
        """Should not provide reason."""
        hook_input = {}
        result = handler.handle(hook_input)
        assert result.reason is None

    def test_handle_has_no_guidance(self, handler):
        """Should not provide guidance."""
        hook_input = {}
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_returns_hook_result_instance(self, handler):
        """Should return HookResult instance."""
        hook_input = {}
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)
