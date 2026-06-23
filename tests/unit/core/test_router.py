"""Tests for EventRouter."""

import pytest

from claude_code_hooks_daemon.core.chain import ChainExecutionResult
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.router import EventRouter


class MockHandler(Handler):
    """Mock handler for testing."""

    def __init__(
        self,
        name: str = "mock",
        priority: int = 50,
        terminal: bool = False,
    ) -> None:
        """Initialize mock handler."""
        super().__init__(name=name, priority=priority, terminal=terminal)
        self.matches_called = False
        self.handle_called = False
        self.match_result = True
        self.handle_result = HookResult.allow()

    def matches(self, hook_input: dict) -> bool:
        """Track matches call."""
        self.matches_called = True
        return self.match_result

    def handle(self, hook_input: dict) -> HookResult:
        """Track handle call."""
        self.handle_called = True
        return self.handle_result

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list:
        """Test handler - stub implementation."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="mock handler",
                command="echo 'test'",
                description="Mock handler for router tests",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                test_type=TestType.BLOCKING,
            )
        ]


class TestEventRouter:
    """Tests for EventRouter class."""

    @pytest.fixture
    def router(self) -> EventRouter:
        """Create a fresh router for each test."""
        return EventRouter()

    def test_initialization(self, router: EventRouter) -> None:
        """Router should initialize with empty chains for all event types."""
        for event_type in EventType:
            chain = router.get_chain(event_type)
            assert len(chain) == 0

    def test_get_chain(self, router: EventRouter) -> None:
        """get_chain should return handler chain for event type."""
        chain = router.get_chain(EventType.PRE_TOOL_USE)
        assert chain is not None
        assert len(chain) == 0

    def test_register_handler(self, router: EventRouter) -> None:
        """register should add handler to event chain."""
        handler = MockHandler(name="test-handler")
        router.register(EventType.PRE_TOOL_USE, handler)

        chain = router.get_chain(EventType.PRE_TOOL_USE)
        assert len(chain) == 1
        assert next(iter(chain.handlers)).name == "test-handler"

    def test_register_multiple_handlers(self, router: EventRouter) -> None:
        """register should add multiple handlers to chain."""
        handler1 = MockHandler(name="handler1", priority=10)
        handler2 = MockHandler(name="handler2", priority=20)
        handler3 = MockHandler(name="handler3", priority=15)

        router.register(EventType.PRE_TOOL_USE, handler1)
        router.register(EventType.PRE_TOOL_USE, handler2)
        router.register(EventType.PRE_TOOL_USE, handler3)

        chain = router.get_chain(EventType.PRE_TOOL_USE)
        assert len(chain) == 3

        # Handlers should be sorted by priority
        handlers = list(chain.handlers)
        assert handlers[0].name == "handler1"
        assert handlers[1].name == "handler3"
        assert handlers[2].name == "handler2"

    def test_register_for_all(self, router: EventRouter) -> None:
        """register_for_all should add handler to all event chains."""
        handler = MockHandler(name="global-handler")
        router.register_for_all(handler)

        for event_type in EventType:
            chain = router.get_chain(event_type)
            assert len(chain) == 1
            assert next(iter(chain.handlers)).name == "global-handler"

    def test_unregister_handler(self, router: EventRouter) -> None:
        """unregister should remove handler from chain."""
        handler = MockHandler(name="test-handler")
        router.register(EventType.PRE_TOOL_USE, handler)
        assert len(router.get_chain(EventType.PRE_TOOL_USE)) == 1

        result = router.unregister(EventType.PRE_TOOL_USE, "test-handler")
        assert result is True
        assert len(router.get_chain(EventType.PRE_TOOL_USE)) == 0

    def test_unregister_nonexistent_handler(self, router: EventRouter) -> None:
        """unregister should return False for nonexistent handler."""
        result = router.unregister(EventType.PRE_TOOL_USE, "nonexistent")
        assert result is False

    def test_route_to_handler(self, router: EventRouter) -> None:
        """route should execute handler chain for event."""
        handler = MockHandler(name="test-handler")
        handler.handle_result = HookResult.allow(context=["Test context"])
        router.register(EventType.PRE_TOOL_USE, handler)

        hook_input = {"toolName": "Bash", "toolInput": {"command": "test"}}
        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        assert isinstance(result, ChainExecutionResult)
        assert handler.matches_called is True
        assert handler.handle_called is True

    def test_route_empty_chain(self, router: EventRouter) -> None:
        """route should return default result for empty chain."""
        hook_input = {"toolName": "Bash"}
        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        assert isinstance(result, ChainExecutionResult)
        assert result.result.decision == "allow"

    def test_route_by_string(self, router: EventRouter) -> None:
        """route_by_string should route using string event type."""
        handler = MockHandler(name="test-handler")
        handler.handle_result = HookResult.deny(reason="Test deny")
        router.register(EventType.PRE_TOOL_USE, handler)

        hook_input = {"toolName": "Bash"}
        result = router.route_by_string("PreToolUse", hook_input)

        assert isinstance(result, HookResult)
        assert result.decision == Decision.DENY

    def test_route_by_string_snake_case(self, router: EventRouter) -> None:
        """route_by_string should handle snake_case event names."""
        handler = MockHandler(name="test-handler")
        router.register(EventType.PRE_TOOL_USE, handler)

        hook_input = {"toolName": "Bash"}
        result = router.route_by_string("pre_tool_use", hook_input)

        assert isinstance(result, HookResult)

    def test_get_all_handlers(self, router: EventRouter) -> None:
        """get_all_handlers should return all handlers grouped by event type."""
        handler1 = MockHandler(name="handler1")
        handler2 = MockHandler(name="handler2")

        router.register(EventType.PRE_TOOL_USE, handler1)
        router.register(EventType.POST_TOOL_USE, handler2)

        all_handlers = router.get_all_handlers()

        assert "PreToolUse" in all_handlers
        assert "PostToolUse" in all_handlers
        assert len(all_handlers["PreToolUse"]) == 1
        assert len(all_handlers["PostToolUse"]) == 1
        assert all_handlers["PreToolUse"][0].name == "handler1"
        assert all_handlers["PostToolUse"][0].name == "handler2"

    def test_get_handler_count(self, router: EventRouter) -> None:
        """get_handler_count should return handler counts for all event types."""
        handler1 = MockHandler(name="handler1")
        handler2 = MockHandler(name="handler2")
        handler3 = MockHandler(name="handler3")

        router.register(EventType.PRE_TOOL_USE, handler1)
        router.register(EventType.PRE_TOOL_USE, handler2)
        router.register(EventType.POST_TOOL_USE, handler3)

        counts = router.get_handler_count()

        assert counts["PreToolUse"] == 2
        assert counts["PostToolUse"] == 1
        assert counts["Stop"] == 0

    def test_clear(self, router: EventRouter) -> None:
        """clear should remove all handlers from all chains."""
        handler1 = MockHandler(name="handler1")
        handler2 = MockHandler(name="handler2")

        router.register(EventType.PRE_TOOL_USE, handler1)
        router.register(EventType.POST_TOOL_USE, handler2)

        router.clear()

        for event_type in EventType:
            assert len(router.get_chain(event_type)) == 0

    def test_repr(self, router: EventRouter) -> None:
        """__repr__ should show total and per-type handler counts."""
        handler1 = MockHandler(name="handler1")
        handler2 = MockHandler(name="handler2")

        router.register(EventType.PRE_TOOL_USE, handler1)
        router.register(EventType.POST_TOOL_USE, handler2)

        repr_str = repr(router)

        assert "EventRouter" in repr_str
        assert "total_handlers=2" in repr_str
        assert "by_type=" in repr_str

    def test_handler_isolation_between_event_types(self, router: EventRouter) -> None:
        """Handlers registered for one event type should not affect others."""
        handler = MockHandler(name="test-handler")
        router.register(EventType.PRE_TOOL_USE, handler)

        # PreToolUse should have the handler
        assert len(router.get_chain(EventType.PRE_TOOL_USE)) == 1

        # Other event types should be empty
        assert len(router.get_chain(EventType.POST_TOOL_USE)) == 0
        assert len(router.get_chain(EventType.STOP)) == 0

    def test_route_with_terminal_handler(self, router: EventRouter) -> None:
        """Terminal handler should stop chain execution."""
        handler1 = MockHandler(name="first", priority=10, terminal=False)
        handler2 = MockHandler(name="terminal", priority=20, terminal=True)
        handler3 = MockHandler(name="third", priority=30, terminal=False)

        handler2.handle_result = HookResult.deny(reason="Blocked by terminal")

        router.register(EventType.PRE_TOOL_USE, handler1)
        router.register(EventType.PRE_TOOL_USE, handler2)
        router.register(EventType.PRE_TOOL_USE, handler3)

        hook_input = {"toolName": "Bash"}
        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # First two handlers should be called
        assert handler1.handle_called is True
        assert handler2.handle_called is True

        # Third handler should NOT be called (terminal stopped execution)
        assert handler3.handle_called is False

        # Result should be from terminal handler
        assert result.result.decision == Decision.DENY

    def test_route_non_matching_handler(self, router: EventRouter) -> None:
        """Non-matching handlers should be skipped."""
        handler1 = MockHandler(name="no-match")
        handler1.match_result = False

        handler2 = MockHandler(name="match")
        handler2.match_result = True
        handler2.handle_result = HookResult.deny(reason="Matched")

        router.register(EventType.PRE_TOOL_USE, handler1)
        router.register(EventType.PRE_TOOL_USE, handler2)

        hook_input = {"toolName": "Bash"}
        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # First handler should check match but not handle
        assert handler1.matches_called is True
        assert handler1.handle_called is False

        # Second handler should match and handle
        assert handler2.matches_called is True
        assert handler2.handle_called is True

        assert result.result.decision == Decision.DENY

    def test_multiple_event_types_independent(self, router: EventRouter) -> None:
        """Multiple event types should maintain independent chains."""
        pre_handler = MockHandler(name="pre-handler")
        post_handler = MockHandler(name="post-handler")
        stop_handler = MockHandler(name="stop-handler")

        router.register(EventType.PRE_TOOL_USE, pre_handler)
        router.register(EventType.POST_TOOL_USE, post_handler)
        router.register(EventType.STOP, stop_handler)

        counts = router.get_handler_count()
        assert counts["PreToolUse"] == 1
        assert counts["PostToolUse"] == 1
        assert counts["Stop"] == 1

        # Removing from one chain shouldn't affect others
        router.unregister(EventType.PRE_TOOL_USE, "pre-handler")
        counts = router.get_handler_count()
        assert counts["PreToolUse"] == 0
        assert counts["PostToolUse"] == 1
        assert counts["Stop"] == 1

    def test_route_with_deny_no_handlers_executed(self, router: EventRouter, monkeypatch) -> None:
        """Route should handle DENY result with no handlers executed (empty list).

        This tests line 155: early return when handlers_executed is empty.
        This is an edge case where chain returns DENY but no handlers were tracked.
        """
        from claude_code_hooks_daemon.core.chain import ChainExecutionResult, HandlerChain

        def mock_execute(self, hook_input, strict_mode=False):
            # Return DENY result but with empty handlers_executed list
            return ChainExecutionResult(
                result=HookResult.deny(reason="Edge case denial"),
                handlers_executed=[],  # Empty list - no handlers executed
                terminated_by=None,  # Non-terminal
            )

        # Monkey-patch the HandlerChain.execute method
        monkeypatch.setattr(HandlerChain, "execute", mock_execute)

        hook_input = {"toolName": "Bash"}
        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Should handle the edge case gracefully (line 155 early return)
        # Reason should be unchanged (no footer appended)
        assert result.result.decision == Decision.DENY
        assert result.result.reason == "Edge case denial"
        assert len(result.handlers_executed) == 0

    def test_route_with_handler_not_in_chain(self, router: EventRouter) -> None:
        """Route should handle case where handler name doesn't exist in chain.

        This tests line 159: early return when handler is not found in chain.
        This can happen if execution_result references a handler that was
        dynamically unregistered or never existed.
        """
        # Create a mock execution result with a handler that doesn't exist
        from claude_code_hooks_daemon.core.chain import ChainExecutionResult

        # Create a handler and route normally first
        handler = MockHandler(name="existing-handler", terminal=True)
        handler.handle_result = HookResult.deny(reason="Blocked")
        router.register(EventType.PRE_TOOL_USE, handler)

        # Unregister the handler before the footer is appended
        # This simulates a race condition or dynamic handler removal
        router.unregister(EventType.PRE_TOOL_USE, "existing-handler")

        # Now manually create an execution result that references the missing handler
        fake_result = ChainExecutionResult(
            result=HookResult.deny(reason="Test denial"),
            handlers_executed=["non-existent-handler"],
            terminated_by="non-existent-handler",
        )

        # Manually call _inject_config_key_footer to test line 159
        chain = router.get_chain(EventType.PRE_TOOL_USE)
        router._inject_config_key_footer(fake_result, EventType.PRE_TOOL_USE, chain)

        # Result reason should be unchanged (no footer appended due to missing handler)
        assert fake_result.result.reason == "Test denial"


class _StubFooterHandler(Handler):
    """Minimal handler exposing a config_key for footer tests."""

    def __init__(
        self,
        config_key_value: str,
        result: HookResult | None = None,
        priority: int = 50,
    ) -> None:
        super().__init__(name=config_key_value.replace("_", "-"), priority=priority, terminal=True)
        self._result = result or HookResult.allow()

    def matches(self, hook_input: dict) -> bool:
        return True

    def handle(self, hook_input: dict) -> HookResult:
        return self._result

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list:
        """Stub - no acceptance tests needed for footer helper tests."""
        return []


class TestSharedFooterHelper:
    """Tests for the shared inject_config_key_footer helper (Plan 00140 #32).

    FrontController and EventRouter previously carried two near-identical
    footer-injection implementations. They now delegate to a single shared
    helper so the behaviour cannot drift.
    """

    def test_helper_appends_footer_to_deny_reason(self) -> None:
        from claude_code_hooks_daemon.core.router import inject_config_key_footer

        result = HookResult.deny(reason="Blocked")
        handler = _StubFooterHandler("my_handler")

        inject_config_key_footer(result, "pre_tool_use", handler)

        assert result.reason is not None
        assert "To disable: handlers.pre_tool_use.my_handler" in result.reason

    def test_helper_fills_none_reason_without_leading_blank_lines(self) -> None:
        from claude_code_hooks_daemon.core.router import inject_config_key_footer

        result = HookResult(decision=Decision.ASK)
        handler = _StubFooterHandler("my_handler")

        inject_config_key_footer(result, "stop", handler)

        assert result.reason is not None
        assert result.reason.startswith("To disable: handlers.stop.my_handler")

    def test_helper_skips_allow(self) -> None:
        from claude_code_hooks_daemon.core.router import inject_config_key_footer

        result = HookResult.allow()
        handler = _StubFooterHandler("my_handler")

        inject_config_key_footer(result, "pre_tool_use", handler)

        assert result.reason is None

    def test_helper_skips_none_handler(self) -> None:
        from claude_code_hooks_daemon.core.router import inject_config_key_footer

        result = HookResult.deny(reason="Blocked")

        inject_config_key_footer(result, "pre_tool_use", None)

        assert result.reason == "Blocked"

    def test_router_and_front_controller_delegate_to_helper(self) -> None:
        """Both call sites must route through the single shared helper."""
        import claude_code_hooks_daemon.core.front_controller as fc_module
        import claude_code_hooks_daemon.core.router as router_module

        calls: list[tuple[str, str]] = []
        original = router_module.inject_config_key_footer

        def spy(result: HookResult, event_config_key: str, handler: object) -> None:
            handler_key = getattr(handler, "config_key", None)
            calls.append((event_config_key, str(handler_key)))
            original(result, event_config_key, handler)

        router_module.inject_config_key_footer = spy
        fc_module.inject_config_key_footer = spy
        try:
            handler = _StubFooterHandler("my_handler", result=HookResult.deny(reason="r"))
            router = EventRouter()
            router.register(EventType.PRE_TOOL_USE, handler)
            router.route(EventType.PRE_TOOL_USE, {})

            controller = fc_module.FrontController("PreToolUse")
            fc_handler = _StubFooterHandler("fc_handler", result=HookResult.deny(reason="r"))
            controller.register(fc_handler)
            controller.dispatch({})
        finally:
            router_module.inject_config_key_footer = original
            fc_module.inject_config_key_footer = original

        assert ("pre_tool_use", "my_handler") in calls
        assert ("pre_tool_use", "fc_handler") in calls
