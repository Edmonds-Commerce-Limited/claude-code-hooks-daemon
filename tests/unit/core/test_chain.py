"""Comprehensive tests for core.chain module.

Tests HandlerChain execution, priority ordering, terminal/non-terminal behavior,
error handling, and ChainExecutionResult.
"""

from typing import Any

from claude_code_hooks_daemon.core.chain import ChainExecutionResult, HandlerChain
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult


class MockHandler(Handler):
    """Mock handler for testing."""

    def __init__(
        self,
        name: str,
        priority: int = 50,
        terminal: bool = False,
        should_match: bool = True,
        result: HookResult | None = None,
        raise_exception: Exception | None = None,
    ) -> None:
        """Initialize mock handler.

        Args:
            name: Handler name
            priority: Handler priority
            terminal: Whether handler is terminal
            should_match: Whether matches() returns True
            result: HookResult to return (or default allow)
            raise_exception: Exception to raise in handle()
        """
        super().__init__(name=name, priority=priority, terminal=terminal)
        self._should_match = should_match
        self._result = result or HookResult.allow()
        self._raise_exception = raise_exception
        self.matches_called = 0
        self.handle_called = 0

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if handler matches input."""
        self.matches_called += 1
        return self._should_match

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Handle the input."""
        self.handle_called += 1
        if self._raise_exception:
            raise self._raise_exception
        return self._result


class TestChainExecutionResult:
    """Tests for ChainExecutionResult dataclass."""

    def test_default_values(self) -> None:
        """ChainExecutionResult has correct defaults."""
        result = HookResult.allow()
        exec_result = ChainExecutionResult(result=result)

        assert exec_result.result is result
        assert exec_result.handlers_executed == []
        assert exec_result.handlers_matched == []
        assert exec_result.execution_time_ms == 0.0
        assert exec_result.terminated_by is None

    def test_can_set_all_fields(self) -> None:
        """Can set all ChainExecutionResult fields."""
        result = HookResult.deny(reason="test")
        exec_result = ChainExecutionResult(
            result=result,
            handlers_executed=["h1", "h2"],
            handlers_matched=["h1", "h2", "h3"],
            execution_time_ms=42.5,
            terminated_by="h2",
        )

        assert exec_result.result is result
        assert exec_result.handlers_executed == ["h1", "h2"]
        assert exec_result.handlers_matched == ["h1", "h2", "h3"]
        assert exec_result.execution_time_ms == 42.5
        assert exec_result.terminated_by == "h2"


class TestHandlerChain:
    """Tests for HandlerChain class."""

    def test_init_creates_empty_chain(self) -> None:
        """Initialization creates empty handler chain."""
        chain = HandlerChain()
        assert len(chain) == 0
        assert list(chain) == []

    def test_add_appends_handler(self) -> None:
        """add appends handler to chain."""
        chain = HandlerChain()
        handler = MockHandler("test", priority=10)

        chain.add(handler)

        assert len(chain) == 1
        assert chain.get("test") is handler

    def test_add_multiple_handlers(self) -> None:
        """Can add multiple handlers to chain."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10)
        h2 = MockHandler("h2", priority=20)
        h3 = MockHandler("h3", priority=5)

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        assert len(chain) == 3

    def test_add_marks_chain_as_unsorted(self) -> None:
        """add marks chain as needing sort."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=50)

        # Access handlers to sort
        _ = chain.handlers
        assert chain._sorted is True

        chain.add(h1)
        assert chain._sorted is False

    def test_remove_deletes_handler_by_name(self) -> None:
        """remove deletes handler from chain by name."""
        chain = HandlerChain()
        h1 = MockHandler("h1")
        h2 = MockHandler("h2")
        chain.add(h1)
        chain.add(h2)

        result = chain.remove("h1")

        assert result is True
        assert len(chain) == 1
        assert chain.get("h1") is None
        assert chain.get("h2") is h2

    def test_remove_returns_false_for_missing_handler(self) -> None:
        """remove returns False when handler not found."""
        chain = HandlerChain()
        h1 = MockHandler("h1")
        chain.add(h1)

        result = chain.remove("nonexistent")

        assert result is False
        assert len(chain) == 1

    def test_get_returns_handler_by_name(self) -> None:
        """get returns handler by name."""
        chain = HandlerChain()
        h1 = MockHandler("h1")
        h2 = MockHandler("h2")
        chain.add(h1)
        chain.add(h2)

        found = chain.get("h2")

        assert found is h2

    def test_get_returns_none_for_missing_handler(self) -> None:
        """get returns None when handler not found."""
        chain = HandlerChain()
        h1 = MockHandler("h1")
        chain.add(h1)

        found = chain.get("missing")

        assert found is None

    def test_clear_removes_all_handlers(self) -> None:
        """clear removes all handlers from chain."""
        chain = HandlerChain()
        chain.add(MockHandler("h1"))
        chain.add(MockHandler("h2"))
        chain.add(MockHandler("h3"))

        chain.clear()

        assert len(chain) == 0
        assert list(chain) == []

    def test_clear_marks_chain_as_sorted(self) -> None:
        """clear marks chain as sorted."""
        chain = HandlerChain()
        chain.add(MockHandler("h1"))
        chain._sorted = False

        chain.clear()

        assert chain._sorted is True

    def test_handlers_property_returns_sorted_list(self) -> None:
        """handlers property returns handlers sorted by priority."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=50)
        h2 = MockHandler("h2", priority=10)
        h3 = MockHandler("h3", priority=30)

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        handlers = chain.handlers

        assert len(handlers) == 3
        assert handlers[0] is h2  # priority 10
        assert handlers[1] is h3  # priority 30
        assert handlers[2] is h1  # priority 50

    def test_handlers_property_caches_sort(self) -> None:
        """handlers property caches sort result."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=20)
        chain.add(h1)

        handlers1 = chain.handlers
        assert chain._sorted is True

        handlers2 = chain.handlers
        assert handlers1 is handlers2

    def test_len_returns_handler_count(self) -> None:
        """len returns number of handlers."""
        chain = HandlerChain()
        assert len(chain) == 0

        chain.add(MockHandler("h1"))
        assert len(chain) == 1

        chain.add(MockHandler("h2"))
        assert len(chain) == 2

    def test_iter_yields_handlers_in_priority_order(self) -> None:
        """iter yields handlers in priority order."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=100)
        h2 = MockHandler("h2", priority=1)
        h3 = MockHandler("h3", priority=50)

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        handlers = list(chain)

        assert handlers[0] is h2  # priority 1
        assert handlers[1] is h3  # priority 50
        assert handlers[2] is h1  # priority 100

    def test_execute_empty_chain_returns_allow(self) -> None:
        """execute on empty chain returns allow result."""
        chain = HandlerChain()
        hook_input = {"tool_name": "Bash"}

        result = chain.execute(hook_input)

        assert result.result.decision == "allow"
        assert result.handlers_executed == []
        assert result.handlers_matched == []
        assert result.terminated_by is None

    def test_execute_calls_matches_on_all_handlers(self) -> None:
        """execute calls matches() on all handlers."""
        chain = HandlerChain()
        h1 = MockHandler("h1", should_match=False)
        h2 = MockHandler("h2", should_match=True)
        h3 = MockHandler("h3", should_match=False)

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        hook_input = {"tool_name": "Bash"}
        chain.execute(hook_input)

        assert h1.matches_called == 1
        assert h2.matches_called == 1
        assert h3.matches_called == 1

    def test_execute_calls_handle_only_on_matching_handlers(self) -> None:
        """execute calls handle() only on matching handlers."""
        chain = HandlerChain()
        h1 = MockHandler("h1", should_match=False)
        h2 = MockHandler("h2", should_match=True)
        h3 = MockHandler("h3", should_match=True)

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        hook_input = {"tool_name": "Bash"}
        chain.execute(hook_input)

        assert h1.handle_called == 0
        assert h2.handle_called == 1
        assert h3.handle_called == 1

    def test_execute_stops_at_terminal_handler(self) -> None:
        """execute stops chain at terminal handler."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, terminal=False)
        h2 = MockHandler("h2", priority=20, terminal=True)
        h3 = MockHandler("h3", priority=30, terminal=False)

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert h1.handle_called == 1
        assert h2.handle_called == 1
        assert h3.handle_called == 0  # Never reached
        assert result.terminated_by == "h2"

    def test_execute_accumulates_context_from_non_terminal_handlers(self) -> None:
        """execute accumulates context from non-terminal handlers."""
        chain = HandlerChain()
        h1 = MockHandler(
            "h1",
            priority=10,
            terminal=False,
            result=HookResult(decision="allow", context=["ctx1"]),
        )
        h2 = MockHandler(
            "h2",
            priority=20,
            terminal=False,
            result=HookResult(decision="allow", context=["ctx2"]),
        )

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert result.result.context == ["ctx1", "ctx2"]

    def test_execute_merges_context_at_terminal_handler(self) -> None:
        """execute merges accumulated context at terminal handler."""
        chain = HandlerChain()
        h1 = MockHandler(
            "h1",
            priority=10,
            terminal=False,
            result=HookResult(decision="allow", context=["ctx1"]),
        )
        h2 = MockHandler(
            "h2",
            priority=20,
            terminal=True,
            result=HookResult(decision="deny", context=["ctx2"]),
        )

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert result.result.context == ["ctx1", "ctx2"]
        assert result.result.decision == "deny"
        assert result.terminated_by == "h2"

    def test_execute_records_handler_names_in_result(self) -> None:
        """execute records handler names in HookResult."""
        chain = HandlerChain()
        h1 = MockHandler("handler1", priority=10)
        h2 = MockHandler("handler2", priority=20)

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert "handler1" in result.result.handlers_matched
        assert "handler2" in result.result.handlers_matched

    def test_execute_tracks_matched_and_executed_handlers(self) -> None:
        """execute tracks matched and executed handler lists."""
        chain = HandlerChain()
        h1 = MockHandler("h1", should_match=True)
        h2 = MockHandler("h2", should_match=False)
        h3 = MockHandler("h3", should_match=True)

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert result.handlers_matched == ["h1", "h3"]
        assert result.handlers_executed == ["h1", "h3"]

    def test_execute_records_execution_time(self) -> None:
        """execute records execution time in milliseconds."""
        chain = HandlerChain()
        h1 = MockHandler("h1")
        chain.add(h1)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert result.execution_time_ms > 0.0
        assert result.execution_time_ms < 100.0  # Should be very fast

    def test_execute_handles_handler_exception(self) -> None:
        """execute handles exceptions raised by handlers."""
        chain = HandlerChain()
        h1 = MockHandler("h1", raise_exception=ValueError("test error"))
        h2 = MockHandler("h2")

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        # Chain continues after error
        assert h2.handle_called == 1
        assert result.handlers_executed == ["h1", "h2"]

    def test_execute_creates_error_context_on_exception(self) -> None:
        """execute creates error context when handler raises exception."""
        chain = HandlerChain()
        h1 = MockHandler("h1", raise_exception=RuntimeError("boom"))
        h2 = MockHandler(
            "h2",
            terminal=True,
            result=HookResult(decision="allow", context=["ctx2"]),
        )

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        # Error context should be accumulated
        assert any("RuntimeError" in ctx for ctx in result.result.context)
        assert "ctx2" in result.result.context

    def test_execute_fail_open_continues_after_exception(self) -> None:
        """execute continues chain after exception (fail-open)."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, raise_exception=Exception("error"))
        h2 = MockHandler("h2", priority=20, terminal=True)

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert result.terminated_by == "h2"
        assert h2.handle_called == 1

    def test_execute_preserves_handler_priority_order(self) -> None:
        """execute processes handlers in strict priority order."""
        chain = HandlerChain()
        execution_order = []

        def make_tracking_handler(name: str, priority: int) -> MockHandler:
            h = MockHandler(name, priority=priority)
            original_handle = h.handle

            def tracked_handle(hook_input: dict[str, Any]) -> HookResult:
                execution_order.append(name)
                return original_handle(hook_input)

            h.handle = tracked_handle  # type: ignore[method-assign]
            return h

        h1 = make_tracking_handler("h1", priority=50)
        h2 = make_tracking_handler("h2", priority=10)
        h3 = make_tracking_handler("h3", priority=30)

        # Add in random order
        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        hook_input = {"tool_name": "Bash"}
        chain.execute(hook_input)

        # Should execute in priority order
        assert execution_order == ["h2", "h3", "h1"]

    def test_execute_with_no_matching_handlers_returns_allow(self) -> None:
        """execute returns allow when no handlers match."""
        chain = HandlerChain()
        h1 = MockHandler("h1", should_match=False)
        h2 = MockHandler("h2", should_match=False)

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert result.result.decision == "allow"
        assert result.handlers_executed == []
        assert result.handlers_matched == []

    def test_execute_terminal_handler_includes_all_matched(self) -> None:
        """execute includes all matched handlers in terminal result."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, terminal=False)
        h2 = MockHandler("h2", priority=20, terminal=True)

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert "h1" in result.result.handlers_matched
        assert "h2" in result.result.handlers_matched

    def test_execute_legacy_returns_hook_result(self) -> None:
        """execute_legacy returns HookResult directly."""
        chain = HandlerChain()
        h1 = MockHandler(
            "h1",
            terminal=True,
            result=HookResult.deny(reason="blocked"),
        )
        chain.add(h1)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute_legacy(hook_input)

        assert isinstance(result, HookResult)
        assert result.decision == "deny"
        assert result.reason == "blocked"

    def test_execute_legacy_compatible_with_execute(self) -> None:
        """execute_legacy produces same result as execute().result."""
        chain = HandlerChain()
        h1 = MockHandler("h1")
        h2 = MockHandler("h2")
        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}

        result1 = chain.execute(hook_input).result
        result2 = chain.execute_legacy(hook_input)

        assert result1.decision == result2.decision
        assert result1.context == result2.context

    def test_complex_scenario_multiple_non_terminal_then_terminal(self) -> None:
        """Complex scenario: multiple non-terminal then terminal handler."""
        chain = HandlerChain()

        # Non-terminal handlers that accumulate context
        h1 = MockHandler(
            "h1",
            priority=10,
            terminal=False,
            result=HookResult(decision="allow", context=["info1"]),
        )
        h2 = MockHandler(
            "h2",
            priority=20,
            terminal=False,
            result=HookResult(decision="allow", context=["info2"]),
        )
        h3 = MockHandler(
            "h3",
            priority=30,
            terminal=False,
            result=HookResult(decision="allow", context=["info3"]),
        )

        # Terminal handler that makes final decision
        h4 = MockHandler(
            "h4",
            priority=40,
            terminal=True,
            result=HookResult(decision="deny", reason="final decision", context=["info4"]),
        )

        # Handler that should never execute
        h5 = MockHandler(
            "h5",
            priority=50,
            terminal=False,
        )

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)
        chain.add(h4)
        chain.add(h5)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        # Verify execution
        assert result.handlers_executed == ["h1", "h2", "h3", "h4"]
        assert h5.handle_called == 0

        # Verify result
        assert result.result.decision == "deny"
        assert result.result.reason == "final decision"
        assert result.result.context == ["info1", "info2", "info3", "info4"]
        assert result.terminated_by == "h4"

        # Verify all handlers recorded
        for handler_name in ["h1", "h2", "h3", "h4"]:
            assert handler_name in result.result.handlers_matched

    def test_execute_with_mixed_matching_patterns(self) -> None:
        """execute with mixed matching and non-matching handlers."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, should_match=True)
        h2 = MockHandler("h2", priority=20, should_match=False)
        h3 = MockHandler("h3", priority=30, should_match=True)
        h4 = MockHandler("h4", priority=40, should_match=False)
        h5 = MockHandler("h5", priority=50, should_match=True)

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)
        chain.add(h4)
        chain.add(h5)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        # Only h1, h3, h5 should match and execute
        assert result.handlers_matched == ["h1", "h3", "h5"]
        assert result.handlers_executed == ["h1", "h3", "h5"]

        # All handlers should have matches() called
        assert h1.matches_called == 1
        assert h2.matches_called == 1
        assert h3.matches_called == 1
        assert h4.matches_called == 1
        assert h5.matches_called == 1

        # Only matching handlers should have handle() called
        assert h1.handle_called == 1
        assert h2.handle_called == 0
        assert h3.handle_called == 1
        assert h4.handle_called == 0
        assert h5.handle_called == 1
