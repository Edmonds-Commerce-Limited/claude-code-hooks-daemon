"""Comprehensive tests for all HelloWorld handlers."""

import pytest

from claude_code_hooks_daemon.handlers.notification.hello_world import (
    HelloWorldNotificationHandler,
)
from claude_code_hooks_daemon.handlers.permission_request.hello_world import (
    HelloWorldPermissionRequestHandler,
)
from claude_code_hooks_daemon.handlers.post_tool_use.hello_world import (
    HelloWorldPostToolUseHandler,
)
from claude_code_hooks_daemon.handlers.pre_compact.hello_world import (
    HelloWorldPreCompactHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.hello_world import (
    HelloWorldPreToolUseHandler,
)
from claude_code_hooks_daemon.handlers.session_end.hello_world import (
    HelloWorldSessionEndHandler,
)
from claude_code_hooks_daemon.handlers.session_start.hello_world import (
    HelloWorldSessionStartHandler,
)
from claude_code_hooks_daemon.handlers.stop.hello_world import HelloWorldStopHandler
from claude_code_hooks_daemon.handlers.subagent_stop.hello_world import (
    HelloWorldSubagentStopHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.hello_world import (
    HelloWorldUserPromptSubmitHandler,
)

# Test data: (Handler class, event name for message, sample hook_input)
ALL_HANDLERS = [
    (
        HelloWorldPreToolUseHandler,
        "PreToolUse",
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    ),
    (
        HelloWorldPostToolUseHandler,
        "PostToolUse",
        {"tool_name": "Bash", "tool_output": "file1.txt\nfile2.txt"},
    ),
    (
        HelloWorldSessionStartHandler,
        "SessionStart",
        {"source": "new"},
    ),
    (
        HelloWorldPermissionRequestHandler,
        "PermissionRequest",
        {"permission": "network"},
    ),
    (
        HelloWorldNotificationHandler,
        "Notification",
        {"message": "Test notification"},
    ),
    (
        HelloWorldUserPromptSubmitHandler,
        "UserPromptSubmit",
        {"prompt": "Hello Claude"},
    ),
    (
        HelloWorldStopHandler,
        "Stop",
        {"reason": "user_requested"},
    ),
    (
        HelloWorldSubagentStopHandler,
        "SubagentStop",
        {"agent_id": "test-agent-123"},
    ),
    (
        HelloWorldPreCompactHandler,
        "PreCompact",
        {"reason": "message_limit"},
    ),
    (
        HelloWorldSessionEndHandler,
        "SessionEnd",
        {"reason": "normal_exit"},
    ),
]


class TestHelloWorldHandlers:
    """Test suite for all HelloWorld handlers."""

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_init_sets_correct_name(self, handler_class, event_name, sample_input):
        """Handler name should be 'hello_world'."""
        handler = handler_class()
        assert handler.name == "hello-world"

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_init_sets_correct_priority(self, handler_class, event_name, sample_input):
        """Handler priority should be 5 (run first)."""
        handler = handler_class()
        assert handler.priority == 5

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_init_sets_non_terminal_flag(self, handler_class, event_name, sample_input):
        """Handler should be non-terminal to allow other handlers to run."""
        handler = handler_class()
        assert handler.terminal is False

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_matches_always_returns_true(self, handler_class, event_name, sample_input):
        """matches() should always return True (universal test handler)."""
        handler = handler_class()
        assert handler.matches(sample_input) is True

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_matches_with_empty_input(self, handler_class, event_name, sample_input):
        """matches() should return True even for empty input."""
        handler = handler_class()
        assert handler.matches({}) is True

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_matches_with_none_values(self, handler_class, event_name, sample_input):
        """matches() should return True even with None values."""
        handler = handler_class()
        assert handler.matches({"key": None}) is True

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_handle_returns_allow_decision(self, handler_class, event_name, sample_input):
        """handle() should return allow decision."""
        handler = handler_class()
        result = handler.handle(sample_input)
        assert result.decision == "allow"

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_handle_reason_is_none(self, handler_class, event_name, sample_input):
        """handle() reason should be None (allow has no reason)."""
        handler = handler_class()
        result = handler.handle(sample_input)
        assert result.reason is None

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_handle_context_contains_confirmation(self, handler_class, event_name, sample_input):
        """handle() context should contain confirmation message."""
        handler = handler_class()
        result = handler.handle(sample_input)
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context)
        assert "✅" in context_text
        assert event_name in context_text
        assert "hook system active" in context_text

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_handle_guidance_is_none(self, handler_class, event_name, sample_input):
        """handle() guidance should be None (not used for hello world)."""
        handler = handler_class()
        result = handler.handle(sample_input)
        assert result.guidance is None

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_handle_context_format(self, handler_class, event_name, sample_input):
        """handle() context should match expected format."""
        handler = handler_class()
        result = handler.handle(sample_input)
        expected = f"✅ {event_name} hook system active"
        assert result.context == [expected]


class TestHelloWorldHandlerIndividualCases:
    """Individual test cases for specific handlers (edge cases)."""

    def test_pre_tool_use_various_tools(self):
        """PreToolUse handler should match all tool types."""
        handler = HelloWorldPreToolUseHandler()
        tools = [
            {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/test.txt"}},
            {"tool_name": "Read", "tool_input": {"file_path": "/test.txt"}},
            {"tool_name": "Edit", "tool_input": {"file_path": "/test.txt"}},
        ]
        for tool_input in tools:
            assert handler.matches(tool_input) is True

    def test_session_start_various_sources(self):
        """SessionStart handler should match all source types."""
        handler = HelloWorldSessionStartHandler()
        sources = [
            {"source": "new"},
            {"source": "compact"},
            {"source": "resume"},
        ]
        for source_input in sources:
            assert handler.matches(source_input) is True

    def test_pre_compact_various_reasons(self):
        """PreCompact handler should match all compact reasons."""
        handler = HelloWorldPreCompactHandler()
        reasons = [
            {"reason": "message_limit"},
            {"reason": "user_requested"},
            {"reason": "auto"},
        ]
        for reason_input in reasons:
            assert handler.matches(reason_input) is True


class TestHelloWorldPriorityOrdering:
    """Test that hello_world handlers run before other handlers."""

    def test_priority_lower_than_typical_handlers(self):
        """Priority 5 should be lower than typical handler priorities (10-60)."""
        handler = HelloWorldPreToolUseHandler()
        assert handler.priority < 10
        assert handler.priority < 20
        assert handler.priority < 100  # Default priority

    def test_all_handlers_same_priority(self):
        """All hello_world handlers should have same priority for consistency."""
        priorities = [handler_class().priority for handler_class, _, _ in ALL_HANDLERS]
        assert len(set(priorities)) == 1  # All same
        assert priorities[0] == 5


class TestHelloWorldNonTerminalBehavior:
    """Test that hello_world handlers are non-terminal."""

    @pytest.mark.parametrize("handler_class,event_name,sample_input", ALL_HANDLERS)
    def test_non_terminal_allows_fallthrough(self, handler_class, event_name, sample_input):
        """Non-terminal handlers should not stop dispatch chain."""
        handler = handler_class()
        # Non-terminal flag allows other handlers to run
        assert handler.terminal is False
        # This means if this handler matches and executes,
        # the FrontController will continue to next handler
