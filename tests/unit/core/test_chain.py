"""Comprehensive tests for core.chain module.

Tests HandlerChain execution, priority ordering, terminal/non-terminal behavior,
error handling, and ChainExecutionResult.

Plan 00466 N40 m1: when ``deadline_seconds`` is set, ``HandlerChain.execute``
dispatches the WHOLE handler loop as ONE call, on its own fresh daemon
thread bounded by the shared dispatcher's semaphore (Plan 00466 N40 n1: not
a thread pool), not one dispatch per handler (measured at ~12ms overhead per
event from creating up to 69 threads, even when every handler is fast). A
handler that FINISHES (however late) is still attributed by name in the
deny/skip reason -- the per-handler deadline check is a cheap comparison,
not a thread, and still runs inline. Only when the WHOLE dispatched call
itself times out or the dispatcher is saturated (some handler never returns
at all, or there is no free capacity even for the whole chain) does the
reason name "chain" instead of a specific handler: nothing is left running
on the CALLING thread at that point that could still say which one it was.

Plan 00466 N40 n4: most of this suite calls ``chain.execute()`` with its
default ``deadline_seconds=None``, which is the SYNCHRONOUS path -- no
dispatch, no thread, no ``BoundedDispatcher`` involved at all. Only the
dispatch-specific tests above exercise the production-shipped threaded path.
``TestUnderShippedDefaultDeadline`` below re-runs a representative slice of
the synchronous-path behavioural tests under ``Timeout.CHAIN_DEADLINE_DEFAULT``
instead, to catch a divergence that only shows up once a real dispatch is in
the loop (thread creation, the semaphore, cancellation binding) -- the shape
of gap this suite would otherwise never notice.
"""

import time
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.chain import ChainExecutionResult, HandlerChain
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult


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
        raise_in_matches: Exception | None = None,
        tags: list[str] | None = None,
        sleep_in_handle: float = 0.0,
    ) -> None:
        """Initialize mock handler.

        Args:
            name: Handler name
            priority: Handler priority
            terminal: Whether handler is terminal
            should_match: Whether matches() returns True
            result: HookResult to return (or default allow)
            raise_exception: Exception to raise in handle()
            raise_in_matches: Exception to raise in matches(), before handle()
                is ever reached — exercises the chain's own try/except span,
                which covers matches() as well as handle() (Plan 00466 N24 m1).
            tags: Handler tags (default []); pass HandlerTag.SAFETY +
                HandlerTag.BLOCKING to exercise the fail-closed-on-raise path.
            sleep_in_handle: Real seconds to sleep inside handle() before
                returning, so a later handler's chain-deadline check (Plan
                00466 N25) has genuinely elapsed wall-clock time to measure.
        """
        super().__init__(name=name, priority=priority, terminal=terminal, tags=tags)
        self._should_match = should_match
        self._result = result or HookResult.allow()
        self._raise_exception = raise_exception
        self._raise_in_matches = raise_in_matches
        self._sleep_in_handle = sleep_in_handle
        self.matches_called = 0
        self.handle_called = 0

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if handler matches input."""
        self.matches_called += 1
        if self._raise_in_matches:
            raise self._raise_in_matches
        return self._should_match

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Handle the input."""
        self.handle_called += 1
        if self._sleep_in_handle:
            time.sleep(self._sleep_in_handle)
        if self._raise_exception:
            raise self._raise_exception
        return self._result

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Test handler - stub implementation."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="mock handler",
                command="echo 'test'",
                description="Mock handler for chain tests",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                test_type=TestType.BLOCKING,
            )
        ]


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

    def test_handlers_property_handles_none_priority(self) -> None:
        """handlers property should handle None priority without crashing.

        Regression test for Plan 00070: handler.priority = None caused
        TypeError in sort: '<' not supported between NoneType and int.
        Defence in depth — chain should apply default priority if None.
        """
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10)
        h2 = MockHandler("h2", priority=30)

        # Simulate a handler whose priority was set to None (e.g., from bad config).
        # Handler.priority's real type is int; aliased through Any because this
        # invalid-per-the-type-system state is exactly what the regression
        # test below exercises (chain must not crash sorting on it).
        h_broken = MockHandler("h_broken", priority=50)
        h_broken_mutable: Any = h_broken
        h_broken_mutable.priority = None

        chain.add(h1)
        chain.add(h_broken)
        chain.add(h2)

        # Should NOT raise TypeError — should sort with default priority (50)
        handlers = chain.handlers

        assert len(handlers) == 3
        # h_broken should be treated as priority 50 (default applied)
        assert handlers[0] is h1  # priority 10
        assert handlers[1] is h2  # priority 30
        assert handlers[2].name == "h_broken"
        assert handlers[2].priority == 50  # Default applied

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

        assert result.result.decision == Decision.ALLOW
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
        """execute stops chain at a terminal handler that DENIES (Plan 00242)."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, terminal=False)
        h2 = MockHandler(
            "h2",
            priority=20,
            terminal=True,
            result=HookResult(decision=Decision.DENY, reason="stop here"),
        )
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
            result=HookResult(decision=Decision.ALLOW, context=["ctx1"]),
        )
        h2 = MockHandler(
            "h2",
            priority=20,
            terminal=False,
            result=HookResult(decision=Decision.ALLOW, context=["ctx2"]),
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
            result=HookResult(decision=Decision.ALLOW, context=["ctx1"]),
        )
        h2 = MockHandler(
            "h2",
            priority=20,
            terminal=True,
            result=HookResult(decision=Decision.DENY, context=["ctx2"]),
        )

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input)

        assert result.result.context == ["ctx1", "ctx2"]
        assert result.result.decision == Decision.DENY
        assert result.terminated_by == "h2"

    def test_non_terminal_deny_survives_later_allow(self) -> None:
        """A non-terminal DENY must never be overwritten by a later ALLOW.

        Regression (Plan 00144 dogfooding): plan_qa_edit (priority 44,
        non-terminal) denied a bad PLAN.md write, but markdown_organization
        (priority 50) matched afterwards and its ALLOW replaced the deny —
        the block was silently lost. The most restrictive decision must win
        across non-terminal handlers.
        """
        chain = HandlerChain()
        denier = MockHandler(
            "denier",
            priority=10,
            terminal=False,
            result=HookResult(decision=Decision.DENY, reason="bad content", context=["dctx"]),
        )
        allower = MockHandler(
            "allower",
            priority=20,
            terminal=False,
            result=HookResult(decision=Decision.ALLOW, context=["actx"]),
        )
        chain.add(denier)
        chain.add(allower)

        result = chain.execute({"tool_name": "Write"})

        assert result.result.decision == Decision.DENY
        assert result.result.reason == "bad content"
        # Context from BOTH handlers is still accumulated.
        assert "dctx" in result.result.context
        assert "actx" in result.result.context

    def test_non_terminal_ask_survives_later_allow(self) -> None:
        """ASK (restrictive) also survives a later non-terminal ALLOW."""
        chain = HandlerChain()
        asker = MockHandler(
            "asker",
            priority=10,
            terminal=False,
            result=HookResult(decision=Decision.ASK, reason="confirm this"),
        )
        allower = MockHandler("allower", priority=20, terminal=False)
        chain.add(asker)
        chain.add(allower)

        result = chain.execute({"tool_name": "Write"})

        assert result.result.decision == Decision.ASK

    def test_non_terminal_deny_then_deny_keeps_first_reason(self) -> None:
        """Two non-terminal denies: the FIRST (highest-priority) reason wins."""
        chain = HandlerChain()
        first = MockHandler(
            "first",
            priority=10,
            terminal=False,
            result=HookResult(decision=Decision.DENY, reason="first reason"),
        )
        second = MockHandler(
            "second",
            priority=20,
            terminal=False,
            result=HookResult(decision=Decision.DENY, reason="second reason"),
        )
        chain.add(first)
        chain.add(second)

        result = chain.execute({"tool_name": "Write"})

        assert result.result.decision == Decision.DENY
        assert result.result.reason == "first reason"

    def test_decided_by_names_the_denying_handler(self) -> None:
        """ChainExecutionResult.decided_by must name the handler that owns
        the restrictive decision — NOT the last executed handler — so the
        'To disable:' footer points users at the right config key."""
        chain = HandlerChain()
        denier = MockHandler(
            "denier",
            priority=10,
            terminal=False,
            result=HookResult(decision=Decision.DENY, reason="bad"),
        )
        allower = MockHandler("allower", priority=20, terminal=False)
        chain.add(denier)
        chain.add(allower)

        result = chain.execute({"tool_name": "Write"})

        assert result.decided_by == "denier"

    def test_decided_by_set_for_terminal_denier(self) -> None:
        chain = HandlerChain()
        denier = MockHandler(
            "terminal-denier",
            priority=10,
            terminal=True,
            result=HookResult(decision=Decision.DENY, reason="bad"),
        )
        chain.add(denier)

        result = chain.execute({"tool_name": "Write"})

        assert result.decided_by == "terminal-denier"

    def test_decided_by_none_when_nothing_restricts(self) -> None:
        chain = HandlerChain()
        chain.add(MockHandler("allower", priority=10, terminal=False))

        result = chain.execute({"tool_name": "Write"})

        assert result.decided_by is None

    def test_decided_by_tracks_the_result_actually_shown(self) -> None:
        """Attribution must follow the DISPLAYED result (Plan 00190 Task 0.5).

        Plan 00242 Task 3.3 makes the rule deliberate and symmetric: the FIRST
        restrictive handler (highest priority) owns both the reason shown and
        the 'To disable:' footer, whether it is terminal or not. A later
        terminal deny still ends the chain, but it does not take over the
        response — so the reason and the config key can never disagree.
        """
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "first-denier",
                priority=10,
                terminal=False,
                result=HookResult(decision=Decision.DENY, reason="first reason"),
            )
        )
        chain.add(
            MockHandler(
                "terminal-denier",
                priority=20,
                terminal=True,
                result=HookResult(decision=Decision.DENY, reason="terminal reason"),
            )
        )

        result = chain.execute({"tool_name": "Write"})

        assert result.result.reason == "first reason"
        assert result.decided_by == "first-denier"
        assert result.terminated_by == "terminal-denier"

    def test_non_terminal_deny_keeps_attribution_over_a_laxer_terminal(self) -> None:
        """The Plan 00144 semantics must survive: a laxer terminal result does
        not wash out an earlier deny, so attribution stays with the denier."""
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "first-denier",
                priority=10,
                terminal=False,
                result=HookResult(decision=Decision.DENY, reason="first reason"),
            )
        )
        chain.add(MockHandler("terminal-allower", priority=20, terminal=True))

        result = chain.execute({"tool_name": "Write"})

        assert result.result.reason == "first reason"
        assert result.decided_by == "first-denier"

    def test_non_terminal_deny_survives_later_terminal_allow(self) -> None:
        """A later TERMINAL ALLOW still cannot wash out an earlier deny.

        Since Plan 00242 an ALLOW never ends the chain, so the terminal
        allower continues rather than terminating; the chain's outcome keeps
        the most restrictive decision already recorded either way.
        """
        chain = HandlerChain()
        denier = MockHandler(
            "denier",
            priority=10,
            terminal=False,
            result=HookResult(decision=Decision.DENY, reason="bad content"),
        )
        terminal_allower = MockHandler(
            "terminal-allower",
            priority=20,
            terminal=True,
            result=HookResult(decision=Decision.ALLOW, context=["tctx"]),
        )
        chain.add(denier)
        chain.add(terminal_allower)

        result = chain.execute({"tool_name": "Write"})

        assert result.result.decision == Decision.DENY
        assert result.result.reason == "bad content"
        assert result.terminated_by is None
        assert result.result.context == ["tctx"]

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
        """execute handles exceptions raised by handlers with FAIL FAST (strict mode)."""
        chain = HandlerChain()
        h1 = MockHandler("h1", raise_exception=ValueError("test error"))
        h2 = MockHandler("h2")

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=True)

        # STRICT MODE: Chain stops immediately, h2 never called
        assert h2.handle_called == 0
        assert result.handlers_executed == ["h1"]
        # Should return DENY to block operation when handler crashes
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "SYSTEM ERROR" in result.result.reason

    def test_execute_creates_error_context_on_exception(self) -> None:
        """execute creates error context when handler raises exception in strict mode."""
        chain = HandlerChain()
        h1 = MockHandler("h1", raise_exception=RuntimeError("boom"))
        h2 = MockHandler(
            "h2",
            terminal=True,
            result=HookResult(decision=Decision.ALLOW, context=["ctx2"]),
        )

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=True)

        # STRICT MODE: Chain stops at exception, h2 never called
        # Error context should be present
        assert any("RuntimeError" in ctx for ctx in result.result.context)
        # h2's context should NOT be present since chain stopped
        assert "ctx2" not in result.result.context
        assert result.result.decision == Decision.DENY

    def test_execute_fail_closed_stops_on_exception(self) -> None:
        """execute stops chain immediately on exception in strict mode (fail-closed)."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, raise_exception=Exception("error"))
        h2 = MockHandler("h2", priority=20, terminal=True)

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=True)

        # STRICT MODE: h1 crashes, chain stops, h2 never called
        assert result.terminated_by == "h1"
        assert h2.handle_called == 0
        assert result.result.decision == Decision.DENY

    def test_execute_fail_open_continues_on_exception(self) -> None:
        """execute continues chain on exception in non-strict mode (fail-open)."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, raise_exception=Exception("error"))
        h2 = MockHandler("h2", priority=20, terminal=True)

        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=False)

        # NON-STRICT MODE: h1 crashes but chain continues, h2 IS called
        assert h2.handle_called == 1
        # h2 is terminal with default ALLOW, so final result is ALLOW — and an
        # ALLOW never ends the chain (Plan 00242), so nothing terminated it
        assert result.terminated_by is None
        assert result.result.decision == Decision.ALLOW
        # Exception context should be accumulated
        assert any("Handler exception:" in ctx for ctx in result.result.context)

    def test_safety_blocking_handler_raise_denies_even_without_strict_mode(self) -> None:
        """A SAFETY+BLOCKING handler that raises denies, whatever strict_mode says.

        Plan 00466 N24 (M3/m1): a safety guard that crashes has not judged
        the call, so falling through to the next handler as "no match" is a
        bypass. This closes the class independently of ``daemon.strict_mode``,
        which is inert in every real install today (see N24).
        """
        chain = HandlerChain()
        h1 = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            raise_exception=ValueError("boom"),
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        h2 = MockHandler("h2", priority=20, terminal=True)
        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=False)

        assert h2.handle_called == 0
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "safety-guard" in result.result.reason
        assert "evaluation error" in result.result.reason.lower()
        assert "denied for safety" in result.result.reason.lower()

    def test_safety_blocking_handler_raise_in_matches_also_denies(self) -> None:
        """The fail-closed path also covers a raise from ``matches()``, not just ``handle()``.

        Plan 00466 N24 m1/m2: the per-guard fail-closed wrapper some handlers
        carry only covers part of their own code; the chain-level policy
        closes the gap structurally for every SAFETY+BLOCKING handler.
        """
        chain = HandlerChain()
        h1 = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            raise_in_matches=TypeError("unhashable type: 'list'"),
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        h2 = MockHandler("h2", priority=20, terminal=True)
        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=False)

        assert h1.handle_called == 0  # never reached handle() — matches() raised
        assert h2.handle_called == 0
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "safety-guard" in result.result.reason

    def test_non_safety_handler_raise_still_fails_open_without_strict_mode(self) -> None:
        """An advisory / non-safety handler that raises keeps today's fail-open behaviour."""
        chain = HandlerChain()
        h1 = MockHandler(
            "advisory",
            priority=10,
            raise_exception=ValueError("boom"),
            tags=[HandlerTag.ADVISORY],
        )
        h2 = MockHandler("h2", priority=20, terminal=True)
        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=False)

        assert h2.handle_called == 1
        assert result.result.decision == Decision.ALLOW
        assert any("Handler exception:" in ctx for ctx in result.result.context)

    def test_safety_tag_alone_without_blocking_still_fails_open(self) -> None:
        """SAFETY without BLOCKING does not trigger the new fail-closed path.

        The predicate is the SAFETY+BLOCKING combination specifically (the
        tag pair every hardened guard in this repository already carries),
        not SAFETY alone.
        """
        chain = HandlerChain()
        h1 = MockHandler(
            "safety-only",
            priority=10,
            raise_exception=ValueError("boom"),
            tags=[HandlerTag.SAFETY],
        )
        h2 = MockHandler("h2", priority=20, terminal=True)
        chain.add(h1)
        chain.add(h2)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=False)

        assert h2.handle_called == 1
        assert result.result.decision == Decision.ALLOW

    def test_safety_blocking_handler_raise_honours_strict_mode_message(self) -> None:
        """strict_mode's own message still wins when both conditions apply.

        Both mechanisms deny, so this only pins that strict_mode's existing
        wording is not silently replaced by the new SAFETY+BLOCKING wording.
        """
        chain = HandlerChain()
        h1 = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            raise_exception=ValueError("boom"),
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(h1)

        hook_input = {"tool_name": "Bash"}
        result = chain.execute(hook_input, strict_mode=True)

        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "SYSTEM ERROR" in result.result.reason

    def test_deadline_exceeded_denies_when_a_slow_handler_exhausts_the_whole_chain(self) -> None:
        """Plan 00466 N25: a chain deadline denies rather than letting a slow
        handler exhaust the CLIENT's own timeout (which fails the whole
        chain open).

        Plan 00466 N40 m1: the WHOLE chain is now ONE dispatched call, not
        one per handler -- so a handler slow enough to blow the budget makes
        the OUTER dispatch itself time out, and the response can only say
        "chain", not name `slow` or `guard` specifically: nothing is left
        running on the CALLING thread that could still say which handler it
        was. The straggler keeps evaluating in the background and reaches
        the SAME correct "safety-guard: not judged in time" verdict
        internally, but that verdict is discarded -- the caller already
        gave up. Polling for `slow` to finish rather than asserting it
        immediately keeps this deterministic.
        """
        chain = HandlerChain()
        slow = MockHandler("slow", priority=10, sleep_in_handle=0.05)
        guard = MockHandler(
            "safety-guard",
            priority=20,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(slow)
        chain.add(guard)

        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=0.01)

        deadline = time.perf_counter() + 2.0
        while slow.handle_called == 0 and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert slow.handle_called == 1
        # The deadline is hit before the guard is even asked whether it
        # matches -- there is no time budget left to run it at all.
        assert guard.matches_called == 0
        assert guard.handle_called == 0
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "chain" in result.result.reason
        assert "not judged in time" in result.result.reason.lower()
        assert result.terminated_by is None

    def test_deadline_measured_from_arrival_time_not_from_execute_call(self) -> None:
        """Plan 00466 N40 M1: the deadline clock starts at request ARRIVAL,
        not at ``execute()``'s own call -- executor queueing between the two
        must count against the budget too, or a request judged late by the
        client's own 30s timeout still looks on-time to the chain.

        A budget already exhausted before ``execute()`` was even called (a
        stale ``arrival_time``) denies the first SAFETY+BLOCKING handler
        immediately, though nothing here is actually slow.
        """
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(guard)

        stale_arrival = time.perf_counter() - 10.0
        result = chain.execute(
            {"tool_name": "Bash"},
            deadline_seconds=0.01,
            arrival_time=stale_arrival,
        )

        assert guard.matches_called == 0
        assert guard.handle_called == 0
        assert result.result.decision == Decision.DENY
        assert result.terminated_by == "safety-guard"

    def test_deadline_defaults_to_execute_call_time_when_arrival_time_omitted(self) -> None:
        """Backward compatible: every pre-existing caller that never passes
        ``arrival_time`` keeps measuring from ``execute()``'s own call."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, terminal=True)
        chain.add(h1)

        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=5.0)

        assert h1.handle_called == 1
        assert result.result.decision == Decision.ALLOW

    def test_deadline_exceeded_skips_an_advisory_handler_with_a_note(self) -> None:
        """A chain with no SAFETY+BLOCKING handler is skipped, not denied,
        on deadline. Plan 00466 N40 m1: `slow` alone exceeds the whole
        chain's dispatch budget, so the note names "chain", not `advisory`
        specifically -- see the module-level note on the redesign.
        """
        chain = HandlerChain()
        slow = MockHandler("slow", priority=10, sleep_in_handle=0.05)
        advisory = MockHandler("advisory", priority=20, tags=[HandlerTag.ADVISORY])
        chain.add(slow)
        chain.add(advisory)

        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=0.01)

        assert advisory.matches_called == 0
        assert result.result.decision == Decision.ALLOW
        assert any(
            "chain" in ctx.lower() and "budget" in ctx.lower() for ctx in result.result.context
        )

    def test_deadline_none_never_denies_on_its_own(self) -> None:
        """The default (no deadline passed) is unenforced -- backward compatible."""
        chain = HandlerChain()
        slow = MockHandler("slow", priority=10, sleep_in_handle=0.02)
        guard = MockHandler(
            "safety-guard",
            priority=20,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(slow)
        chain.add(guard)

        result = chain.execute({"tool_name": "Bash"})

        assert guard.handle_called == 1
        assert result.result.decision == Decision.ALLOW

    def test_deadline_not_exceeded_runs_every_handler_normally(self) -> None:
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10)
        h2 = MockHandler("h2", priority=20, terminal=True)
        chain.add(h1)
        chain.add(h2)

        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=5.0)

        assert h2.handle_called == 1
        assert result.result.decision == Decision.ALLOW

    def test_a_safety_blocking_handler_that_oversleeps_itself_is_denied_within_the_deadline(
        self,
    ) -> None:
        """Plan 00466 N34: the deadline now bounds a handler's OWN call, not
        only the gap before it. Without this, N25's between-handlers check
        never fires here -- this guard is the FIRST and ONLY handler, so
        nothing runs before it to exhaust the budget; only bounding its own
        execution can catch it. Mirrors the real finding: secret_file_guard
        measured at 48.958s on 4 MB input, past the 20s chain deadline,
        entirely inside its own call.

        Plan 00466 N40 m1: the WHOLE chain (here, just this one handler) is
        the dispatched unit -- the deny names "chain", not "safety-guard",
        since nothing is left on the calling thread to say which handler it
        was. See the module-level note on the redesign.
        """
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
            sleep_in_handle=5.0,
        )
        chain.add(guard)

        start = time.perf_counter()
        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=0.1)
        elapsed = time.perf_counter() - start

        # Bounded by the DEADLINE, not by the guard's own 5s sleep.
        assert elapsed < 2.0
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "chain" in result.result.reason
        assert "not judged in time" in result.result.reason.lower()
        assert result.terminated_by is None

    def test_a_slow_advisory_only_handler_that_oversleeps_itself_allows_with_an_advisory(
        self,
    ) -> None:
        """The non-SAFETY+BLOCKING mirror of the test above: bounded the same
        way, but skipped with a context note rather than denied. Plan 00466
        N40 m1: the note names "chain", not `slow-advisory` specifically --
        see the module-level note on the redesign.
        """
        chain = HandlerChain()
        advisory = MockHandler(
            "slow-advisory",
            priority=10,
            tags=[HandlerTag.ADVISORY],
            sleep_in_handle=5.0,
        )
        chain.add(advisory)

        start = time.perf_counter()
        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=0.1)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0
        assert result.result.decision == Decision.ALLOW
        assert any(
            "chain" in ctx.lower() and "budget" in ctx.lower() for ctx in result.result.context
        )

    def test_deadline_none_leaves_an_oversleeping_safety_handler_unbounded(self) -> None:
        """Plan 00466 N34: ``deadline_seconds=None`` disables the NEW
        per-handler bound too, not only the pre-existing between-handlers
        check -- the direct, synchronous call path is taken, unchanged.
        """
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
            sleep_in_handle=0.05,
        )
        chain.add(guard)

        result = chain.execute({"tool_name": "Bash"})

        # No pool involved on this path -- the call already returned
        # synchronously, so this is deterministic, not a race.
        assert guard.handle_called == 1
        assert result.result.decision == Decision.ALLOW

    def test_dispatch_pool_saturation_denies_a_safety_blocking_handler(self) -> None:
        """Plan 00466 N34 remedy 2's OTHER fail-closed case: a pool with no
        free capacity refuses the submission outright rather than queuing
        it -- an unbounded queue is exactly the "pile up threads" failure
        this exists to prevent. Plan 00466 N40 m1: the WHOLE chain is now
        the thing submitted to the pool, so saturation denies "chain", not
        `safety-guard` specifically -- see the module-level note.
        """
        import threading

        from claude_code_hooks_daemon.core.bounded_dispatch import BoundedDispatcher

        small_pool = BoundedDispatcher(max_inflight=1)
        occupied = threading.Event()
        release = threading.Event()

        def _occupy() -> None:
            occupied.set()
            release.wait(timeout=5.0)

        filler = threading.Thread(
            target=lambda: small_pool.run(_occupy, timeout=5.0, label="filler")
        )
        try:
            filler.start()
            assert occupied.wait(timeout=1.0)

            chain = HandlerChain()
            guard = MockHandler(
                "safety-guard",
                priority=10,
                terminal=True,
                tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
            )
            chain.add(guard)

            start = time.perf_counter()
            result = chain.execute(
                {"tool_name": "Bash"}, deadline_seconds=5.0, dispatcher=small_pool
            )
            elapsed = time.perf_counter() - start
        finally:
            release.set()
            filler.join(timeout=5.0)
            small_pool.shutdown(wait=True)

        # Refused immediately -- never waited anywhere near the 5s deadline.
        assert elapsed < 1.0
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "chain" in result.result.reason
        assert "not judged in time" in result.result.reason.lower()

    def test_oversized_bash_command_denies_a_safety_blocking_handler(self) -> None:
        """Plan 00466 N34 remedy 3: an oversized payload is denied BEFORE
        dispatch, naming the size and the limit -- not "not judged in time",
        since no timing was ever involved.
        """
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(guard)

        # The measured size is the whole SERIALISED tool_input (n24 review
        # m5), not the raw command string alone -- so this asserts on the
        # limit and the ballpark, not a literal byte count tied to JSON
        # punctuation overhead.
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "x" * 100}}
        result = chain.execute(hook_input, max_safety_input_bytes=50)

        assert guard.matches_called == 0
        assert guard.handle_called == 0
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "safety-guard" in result.result.reason
        assert "too large" in result.result.reason.lower()
        assert "50" in result.result.reason

    def test_oversized_write_content_skips_a_non_safety_blocking_handler(self) -> None:
        """A SAFETY handler without BLOCKING is skipped with a note, not denied."""
        chain = HandlerChain()
        advisory = MockHandler("safety-advisory", priority=10, tags=[HandlerTag.SAFETY])
        chain.add(advisory)

        hook_input = {"tool_name": "Write", "tool_input": {"content": "x" * 100}}
        result = chain.execute(hook_input, max_safety_input_bytes=50)

        assert advisory.matches_called == 0
        assert result.result.decision == Decision.ALLOW
        assert any(
            "safety-advisory" in ctx and "too large" in ctx.lower() for ctx in result.result.context
        )

    def test_oversized_file_path_denies_a_safety_blocking_handler(self) -> None:
        """Plan 00466 n24 review B2/m5: the ORIGINAL fixed-field size cap
        never measured ``file_path`` at all -- a long path was B2's actual
        vector (a ~90 KB path froze the whole daemon via a quadratic glob
        match, with nothing bounding it). Serialising the whole tool_input
        covers this without a dedicated field name.
        """
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(guard)

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/" + "p" * 100, "content": "ok"},
        }
        result = chain.execute(hook_input, max_safety_input_bytes=50)

        assert guard.handle_called == 0
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "too large" in result.result.reason.lower()

    def test_oversized_multiedit_edits_list_denies_a_safety_blocking_handler(self) -> None:
        """Plan 00466 n24 review m5: MultiEdit's bulk text lives in
        ``edits[]``, a list of dicts -- also unmeasured by the original
        fixed-field cap.
        """
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(guard)

        hook_input = {
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": "/tmp/x.py",
                "edits": [{"old_string": "a", "new_string": "b" * 200}],
            },
        }
        result = chain.execute(hook_input, max_safety_input_bytes=50)

        assert guard.handle_called == 0
        assert result.result.decision == Decision.DENY

    def test_non_safety_handler_is_unaffected_by_the_size_cap(self) -> None:
        """The size cap is scoped to SAFETY handlers -- an ordinary advisory
        still runs normally over an oversized payload.
        """
        chain = HandlerChain()
        ordinary = MockHandler("ordinary", priority=10)
        chain.add(ordinary)

        hook_input = {"tool_name": "Bash", "tool_input": {"command": "x" * 100}}
        result = chain.execute(hook_input, max_safety_input_bytes=50)

        assert ordinary.matches_called == 1
        assert ordinary.handle_called == 1
        assert result.result.decision == Decision.ALLOW

    def test_size_cap_none_disables_the_check(self) -> None:
        """The default: no size cap configured means no size-based denial,
        however large the payload.
        """
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(guard)

        hook_input = {"tool_name": "Bash", "tool_input": {"command": "x" * 10_000}}
        result = chain.execute(hook_input)

        assert guard.handle_called == 1
        assert result.result.decision == Decision.ALLOW

    def test_size_within_the_cap_runs_normally(self) -> None:
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(guard)

        hook_input = {"tool_name": "Bash", "tool_input": {"command": "x" * 10}}
        result = chain.execute(hook_input, max_safety_input_bytes=50)

        assert guard.handle_called == 1
        assert result.result.decision == Decision.ALLOW

    def test_a_lone_surrogate_in_the_measured_fields_does_not_crash_the_size_check(
        self,
    ) -> None:
        """Plan 00466 n24 review B1: ``str.encode("utf-8")`` (strict) raises
        ``UnicodeEncodeError`` on a lone surrogate -- reachable whenever the
        daemon's own ``json.loads`` turns a JSON ``"\\ud800"`` escape into a
        Python string, which a model's tool arguments can carry. Before the
        fix this exception escaped ``_safety_payload_size``, outside every
        handler's own try/except, and reached the controller's fail-OPEN
        catch-all -- a regression this branch introduced by adding the size
        check at all. The chain must still judge normally.
        """
        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
            result=HookResult.deny(reason="denied for a real reason"),
        )
        chain.add(guard)

        for field in ("command", "content", "new_string", "old_string"):
            hook_input = {"tool_name": "Bash", "tool_input": {field: "AKIA\ud800"}}
            result = chain.execute(hook_input, max_safety_input_bytes=1_000_000)
            assert guard.handle_called >= 1, field
            assert result.result.decision == Decision.DENY, field
            assert result.result.reason == "denied for a real reason", field

    def test_a_size_measurement_crash_denies_when_a_safety_blocking_handler_exists(
        self,
    ) -> None:
        """Defence in depth alongside the surrogate fix above: ANY exception
        computing the size (not only the specific surrogate case) must fail
        CLOSED, not reach the controller's fail-open catch-all, whenever a
        SAFETY+BLOCKING handler is registered for this chain.
        """
        import claude_code_hooks_daemon.core.chain as chain_module

        chain = HandlerChain()
        guard = MockHandler(
            "safety-guard",
            priority=10,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        chain.add(guard)

        def _boom(hook_input: dict[str, Any]) -> int:
            raise RuntimeError("boom")

        original = chain_module._safety_payload_size
        chain_module._safety_payload_size = _boom
        try:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": "x"}}
            result = chain.execute(hook_input, max_safety_input_bytes=50)
        finally:
            chain_module._safety_payload_size = original

        assert guard.handle_called == 0
        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert "boom" in result.result.reason or "RuntimeError" in result.result.reason

    def test_a_size_measurement_crash_degrades_gracefully_with_no_safety_blocking_handler(
        self,
    ) -> None:
        """The same crash, but nothing in the chain COULD have denied on the
        size cap anyway -- failing the whole chain over an unrelated
        measurement bug would be a pure availability regression with no
        security benefit, so this degrades to "cap not enforced" instead.
        """
        import claude_code_hooks_daemon.core.chain as chain_module

        chain = HandlerChain()
        advisory = MockHandler("ordinary", priority=10, tags=[HandlerTag.ADVISORY])
        chain.add(advisory)

        def _boom(hook_input: dict[str, Any]) -> int:
            raise RuntimeError("boom")

        original = chain_module._safety_payload_size
        chain_module._safety_payload_size = _boom
        try:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": "x"}}
            result = chain.execute(hook_input, max_safety_input_bytes=50)
        finally:
            chain_module._safety_payload_size = original

        assert advisory.handle_called == 1
        assert result.result.decision == Decision.ALLOW

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

        assert result.result.decision == Decision.ALLOW
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
        assert result.decision == Decision.DENY
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
            result=HookResult(decision=Decision.ALLOW, context=["info1"]),
        )
        h2 = MockHandler(
            "h2",
            priority=20,
            terminal=False,
            result=HookResult(decision=Decision.ALLOW, context=["info2"]),
        )
        h3 = MockHandler(
            "h3",
            priority=30,
            terminal=False,
            result=HookResult(decision=Decision.ALLOW, context=["info3"]),
        )

        # Terminal handler that makes final decision
        h4 = MockHandler(
            "h4",
            priority=40,
            terminal=True,
            result=HookResult(decision=Decision.DENY, reason="final decision", context=["info4"]),
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
        assert result.result.decision == Decision.DENY
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


class _LateStateWriter(Handler):
    """Sleeps inside ``matches()`` past the chain's deadline, then checks
    ``is_dispatch_cancelled()`` right before "writing" shared state --
    exactly the shape ``sensitive_content.py``'s ``_cached_dispatch`` write
    and ``github_auto_close_keywords.py``'s ``mark_disclosed`` call take
    (Plan 00466 N40 m2)."""

    def __init__(
        self, name: str, priority: int, sleep_before_check: float, outcome: dict[str, str]
    ) -> None:
        super().__init__(name=name, priority=priority, terminal=True)
        self._sleep_before_check = sleep_before_check
        self._outcome = outcome

    def matches(self, hook_input: dict[str, Any]) -> bool:
        time.sleep(self._sleep_before_check)
        from claude_code_hooks_daemon.core.dispatch_cancellation import is_dispatch_cancelled

        self._outcome["result"] = "skipped-cancelled" if is_dispatch_cancelled() else "written"
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult.allow()

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestDispatchCancellationReachesStragglingHandlerCode:
    """Plan 00466 N40 m2: a straggler's own state-mutating write, deep
    inside ``matches()``/``handle()``, must see cancellation once the
    caller has abandoned the whole chain -- the between-handler deadline
    check alone cannot help here, since it never interrupts a handler
    call ALREADY in progress.
    """

    def test_a_late_writes_after_the_deadline_is_skipped_not_written(self) -> None:
        chain = HandlerChain()
        outcome: dict[str, str] = {}
        writer = _LateStateWriter("late-writer", priority=10, sleep_before_check=0.2, outcome=outcome)
        chain.add(writer)

        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=0.02)

        # The caller gets its answer promptly -- well before the straggler's
        # own 0.2s sleep finishes.
        assert result.result.decision == Decision.ALLOW

        deadline = time.perf_counter() + 2.0
        while "result" not in outcome and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert outcome.get("result") == "skipped-cancelled"

    def test_a_write_within_the_deadline_still_lands(self) -> None:
        """Negative control: cancellation must not fire SPURIOUSLY for a
        call that finishes comfortably inside its own budget."""
        chain = HandlerChain()
        outcome: dict[str, str] = {}
        writer = _LateStateWriter("on-time-writer", priority=10, sleep_before_check=0.0, outcome=outcome)
        chain.add(writer)

        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=5.0)

        assert result.result.decision == Decision.ALLOW
        assert outcome.get("result") == "written"


class TestChainDecisions:
    """Tests for ChainExecutionResult.decisions (Plan 00209 verdict log).

    The pre-existing controller.py loop over ``handlers_matched`` attributes
    the SAME final chain decision to every matched handler, which is wrong
    for a non-terminal handler whose own decision got superseded by a later
    handler (Plan 00144's "most restrictive decision wins" rule). The verdict
    log needs each handler's OWN decision, captured once, in the front
    controller — not per handler opt-in.
    """

    def test_default_decisions_is_empty_list(self) -> None:
        """ChainExecutionResult.decisions defaults to an empty list."""
        result = HookResult.allow()
        exec_result = ChainExecutionResult(result=result)
        assert exec_result.decisions == []

    def test_decisions_records_one_entry_per_matched_handler(self) -> None:
        """Every matched handler gets exactly one HandlerVerdict entry."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, result=HookResult.allow())
        h2 = MockHandler("h2", priority=20, should_match=False)
        h3 = MockHandler("h3", priority=30, terminal=True, result=HookResult.deny(reason="blocked"))

        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        result = chain.execute({"tool_name": "Bash"})

        names = [d.handler for d in result.decisions]
        assert names == ["h1", "h3"]  # h2 never matched, so no verdict

    def test_decisions_capture_each_handlers_own_decision_not_the_merged_final(
        self,
    ) -> None:
        """A superseded non-terminal deny still shows as its OWN deny.

        Regression guard for the controller.py bug this plan fixes: naively
        attributing the final chain decision to every matched handler would
        report h2 (an ALLOW) as DENY here, because the final chain result is
        DENY (h1's non-terminal deny survives per Plan 00144).
        """
        chain = HandlerChain()
        h1 = MockHandler(
            "h1", priority=10, terminal=False, result=HookResult.deny(reason="non-terminal deny")
        )
        h2 = MockHandler("h2", priority=20, terminal=True, result=HookResult.allow())

        chain.add(h1)
        chain.add(h2)

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.decision == Decision.DENY  # chain-level outcome
        by_handler = {d.handler: d.decision for d in result.decisions}
        assert by_handler["h1"] == Decision.DENY
        assert by_handler["h2"] == Decision.ALLOW  # h2's OWN decision, not DENY

    def test_decisions_record_terminal_flag(self) -> None:
        """Each verdict records whether its handler is terminal."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, terminal=False, result=HookResult.allow())
        h2 = MockHandler("h2", priority=20, terminal=True, result=HookResult.allow())
        chain.add(h1)
        chain.add(h2)

        result = chain.execute({"tool_name": "Bash"})

        by_handler = {d.handler: d.terminal for d in result.decisions}
        assert by_handler["h1"] is False
        assert by_handler["h2"] is True

    def test_decisions_carry_optional_rule_from_hook_result(self) -> None:
        """A handler that sets HookResult.rule surfaces it on the verdict."""
        chain = HandlerChain()
        h1 = MockHandler(
            "h1",
            priority=10,
            terminal=True,
            result=HookResult(decision=Decision.DENY, reason="x", rule="blacklisted"),
        )
        chain.add(h1)

        result = chain.execute({"tool_name": "Bash"})

        assert result.decisions[0].rule == "blacklisted"

    def test_decisions_rule_defaults_to_none(self) -> None:
        """A handler that never sets rule surfaces None on the verdict."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, terminal=True, result=HookResult.allow())
        chain.add(h1)

        result = chain.execute({"tool_name": "Bash"})

        assert result.decisions[0].rule is None

    def test_decisions_skip_a_crashed_handler_in_strict_mode(self) -> None:
        """A handler that raises made no verdict — it is not recorded."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, raise_exception=ValueError("boom"))
        chain.add(h1)

        result = chain.execute({"tool_name": "Bash"}, strict_mode=True)

        assert result.decisions == []

    def test_decisions_skip_a_crashed_handler_in_non_strict_mode(self) -> None:
        """Fail-open mode also records no verdict for the crashed handler,
        while the chain continues and records the next handler's verdict."""
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, raise_exception=ValueError("boom"))
        h2 = MockHandler("h2", priority=20, terminal=True, result=HookResult.allow())
        chain.add(h1)
        chain.add(h2)

        result = chain.execute({"tool_name": "Bash"}, strict_mode=False)

        names = [d.handler for d in result.decisions]
        assert names == ["h2"]


class TestAllowNeverEndsTheChain:
    """Plan 00242: terminality is a property of the DECISION, not the handler.

    A DENY (or ASK/DEFER) from a terminal handler may end the chain; an ALLOW
    from a terminal handler continues to the next handler with its context
    accumulated. This is the general form of the Plan 00241 defect class (a
    terminal advisory ALLOW silently disabling every successor), and it holds
    for EVERY handler, whatever its ``terminal`` flag says.
    """

    def test_terminal_allow_does_not_stop_the_chain(self) -> None:
        chain = HandlerChain()
        terminal_allower = MockHandler(
            "terminal-allower",
            priority=10,
            terminal=True,
            result=HookResult(decision=Decision.ALLOW, context=["advice"]),
        )
        successor = MockHandler("successor", priority=20, terminal=False)
        chain.add(terminal_allower)
        chain.add(successor)

        result = chain.execute({"tool_name": "Bash"})

        assert successor.handle_called == 1
        assert result.terminated_by is None
        assert result.handlers_executed == ["terminal-allower", "successor"]

    def test_terminal_allow_keeps_its_context_when_the_chain_continues(self) -> None:
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "terminal-allower",
                priority=10,
                terminal=True,
                result=HookResult(decision=Decision.ALLOW, context=["first"]),
            )
        )
        chain.add(
            MockHandler(
                "successor",
                priority=20,
                terminal=False,
                result=HookResult(decision=Decision.ALLOW, context=["second"]),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.decision == Decision.ALLOW
        assert result.result.context == ["first", "second"]

    def test_a_successor_can_still_deny_after_a_terminal_allow(self) -> None:
        """The Plan 00241 defect class: the successor's deny must land."""
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "terminal-allower",
                priority=10,
                terminal=True,
                result=HookResult(decision=Decision.ALLOW, context=["advice"]),
            )
        )
        chain.add(
            MockHandler(
                "blocker",
                priority=20,
                terminal=True,
                result=HookResult(decision=Decision.DENY, reason="blocked by successor"),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.decision == Decision.DENY
        assert result.result.reason == "blocked by successor"
        assert result.decided_by == "blocker"
        assert result.terminated_by == "blocker"
        assert result.result.context == ["advice"]

    def test_terminal_deny_still_ends_the_chain(self) -> None:
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "blocker",
                priority=10,
                terminal=True,
                result=HookResult(decision=Decision.DENY, reason="no"),
            )
        )
        skipped = MockHandler("skipped", priority=20, terminal=False)
        chain.add(skipped)

        result = chain.execute({"tool_name": "Bash"})

        assert skipped.handle_called == 0
        assert result.terminated_by == "blocker"

    def test_terminal_ask_still_ends_the_chain(self) -> None:
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "asker",
                priority=10,
                terminal=True,
                result=HookResult(decision=Decision.ASK, reason="confirm"),
            )
        )
        skipped = MockHandler("skipped", priority=20, terminal=False)
        chain.add(skipped)

        result = chain.execute({"tool_name": "Bash"})

        assert skipped.handle_called == 0
        assert result.terminated_by == "asker"

    def test_terminal_continue_decision_does_not_stop_the_chain(self) -> None:
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "continuer",
                priority=10,
                terminal=True,
                result=HookResult(decision=Decision.CONTINUE),
            )
        )
        successor = MockHandler("successor", priority=20, terminal=False)
        chain.add(successor)

        chain.execute({"tool_name": "Bash"})

        assert successor.handle_called == 1

    def test_every_terminal_flag_combination_lets_a_later_deny_land(self) -> None:
        """No handler can silently disable another, whatever its flag."""
        for first_terminal in (True, False):
            for second_terminal in (True, False):
                chain = HandlerChain()
                chain.add(
                    MockHandler(
                        "first",
                        priority=10,
                        terminal=first_terminal,
                        result=HookResult(decision=Decision.ALLOW),
                    )
                )
                chain.add(
                    MockHandler(
                        "second",
                        priority=20,
                        terminal=second_terminal,
                        result=HookResult(decision=Decision.DENY, reason="late deny"),
                    )
                )

                result = chain.execute({"tool_name": "Bash"})

                assert result.result.decision == Decision.DENY, (first_terminal, second_terminal)
                assert result.decided_by == "second"


def _deny(name: str, priority: int, reason: str, *, terminal: bool = True) -> MockHandler:
    return MockHandler(
        name,
        priority=priority,
        terminal=terminal,
        result=HookResult(decision=Decision.DENY, reason=reason),
    )


def _advise(name: str, priority: int, *lines: str) -> MockHandler:
    return MockHandler(
        name,
        priority=priority,
        terminal=False,
        result=HookResult(decision=Decision.ALLOW, context=list(lines)),
    )


class TestCollectAllViolations:
    """``daemon.chain.collect_all_violations`` (Plan 00242, Phase 3).

    Off by default: a terminal deny short-circuits as before. On: the chain
    keeps running after a deny, collects every deny and every advisory, and
    returns ONE merged response led by the first (highest-priority) deny.
    """

    def test_default_execute_keeps_the_deny_short_circuit(self) -> None:
        chain = HandlerChain()
        chain.add(_deny("first", 10, "first reason"))
        second = _deny("second", 20, "second reason")
        chain.add(second)

        result = chain.execute({"tool_name": "Write"})

        assert second.handle_called == 0
        assert result.terminated_by == "first"

    def test_collect_all_runs_every_matching_handler_after_a_terminal_deny(self) -> None:
        chain = HandlerChain()
        chain.add(_deny("first", 10, "first reason"))
        second = _deny("second", 20, "second reason")
        third = _advise("third", 30, "some advice")
        chain.add(second)
        chain.add(third)

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        assert second.handle_called == 1
        assert third.handle_called == 1
        assert result.handlers_executed == ["first", "second", "third"]
        assert result.terminated_by is None

    def test_collect_all_leads_with_the_first_deny_and_attributes_it(self) -> None:
        chain = HandlerChain()
        chain.add(_deny("first", 10, "first reason"))
        chain.add(_deny("second", 20, "second reason"))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert result.result.reason.startswith("first reason")
        assert result.decided_by == "first"

    def test_collect_all_appends_every_other_deny_naming_its_handler(self) -> None:
        chain = HandlerChain()
        chain.add(_deny("first", 10, "first reason"))
        chain.add(_deny("second", 20, "second reason"))
        chain.add(_deny("third", 30, "third reason", terminal=False))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        reason = result.result.reason or ""
        assert "Also denied by: second" in reason
        assert "second reason" in reason
        assert "Also denied by: third" in reason
        assert "third reason" in reason
        assert reason.index("second reason") < reason.index("third reason")

    def test_collect_all_records_every_deny_verdict(self) -> None:
        chain = HandlerChain()
        chain.add(_deny("first", 10, "first reason"))
        chain.add(_deny("second", 20, "second reason"))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        assert [d.decision for d in result.decisions] == [Decision.DENY, Decision.DENY]

    def test_collect_all_puts_advisories_in_one_table(self) -> None:
        chain = HandlerChain()
        chain.add(_deny("blocker", 10, "blocked"))
        chain.add(_advise("hinter", 20, "use the Edit tool\nsecond line"))
        chain.add(_advise("reminder", 30, "remember the journal"))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        reason = result.result.reason or ""
        assert "| Handler | Advisory |" in reason
        assert "| hinter | use the Edit tool |" in reason
        assert "| reminder | remember the journal |" in reason
        # The full advisory text still travels as context, unchanged.
        assert result.result.context == ["use the Edit tool\nsecond line", "remember the journal"]

    def test_collect_all_with_a_single_deny_and_no_advisories_is_unchanged(self) -> None:
        chain = HandlerChain()
        chain.add(_deny("only", 10, "only reason"))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        assert result.result.reason == "only reason"

    def test_collect_all_without_any_deny_returns_a_plain_allow(self) -> None:
        chain = HandlerChain()
        chain.add(_advise("hinter", 20, "advice"))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        assert result.result.decision == Decision.ALLOW
        assert result.result.reason is None
        assert result.result.context == ["advice"]

    def test_collect_all_bounds_the_number_of_extra_denies(self) -> None:
        from claude_code_hooks_daemon.core.chain import COLLECT_ALL_MAX_EXTRA_DENIES

        chain = HandlerChain()
        chain.add(_deny("lead", 1, "lead reason"))
        for i in range(COLLECT_ALL_MAX_EXTRA_DENIES + 3):
            chain.add(_deny(f"extra-{i:02d}", 10 + i, f"extra reason {i:02d}"))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        reason = result.result.reason or ""
        assert reason.count("Also denied by:") == COLLECT_ALL_MAX_EXTRA_DENIES
        assert "3 more" in reason
        # The overflowed handlers are still NAMED, so nothing is silent.
        last = f"extra-{COLLECT_ALL_MAX_EXTRA_DENIES + 2:02d}"
        assert last in reason

    def test_collect_all_bounds_each_extra_deny_excerpt(self) -> None:
        from claude_code_hooks_daemon.core.chain import COLLECT_ALL_DENY_EXCERPT_CHARS

        chain = HandlerChain()
        chain.add(_deny("lead", 1, "lead reason"))
        chain.add(_deny("verbose", 10, "x" * (COLLECT_ALL_DENY_EXCERPT_CHARS * 3)))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        reason = result.result.reason or ""
        assert "x" * COLLECT_ALL_DENY_EXCERPT_CHARS in reason
        assert "x" * (COLLECT_ALL_DENY_EXCERPT_CHARS + 1) not in reason
        assert "truncated" in reason

    def test_collect_all_bounds_the_advisory_table(self) -> None:
        from claude_code_hooks_daemon.core.chain import (
            COLLECT_ALL_ADVISORY_EXCERPT_CHARS,
            COLLECT_ALL_MAX_ADVISORY_ROWS,
        )

        chain = HandlerChain()
        chain.add(_deny("lead", 1, "lead reason"))
        for i in range(COLLECT_ALL_MAX_ADVISORY_ROWS + 2):
            chain.add(
                _advise(f"adv-{i:02d}", 10 + i, "y" * (COLLECT_ALL_ADVISORY_EXCERPT_CHARS * 2))
            )

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        reason = result.result.reason or ""
        assert reason.count("| adv-") == COLLECT_ALL_MAX_ADVISORY_ROWS
        assert "2 more" in reason
        assert "y" * (COLLECT_ALL_ADVISORY_EXCERPT_CHARS + 1) not in reason

    def test_collect_all_never_lets_an_allow_end_the_chain_either(self) -> None:
        chain = HandlerChain()
        allower = MockHandler("allower", priority=10, terminal=True)
        chain.add(allower)
        chain.add(_deny("blocker", 20, "late"))

        result = chain.execute({"tool_name": "Write"}, collect_all=True)

        assert result.result.decision == Decision.DENY

    def test_collect_all_respects_allow_is_final(self) -> None:
        """PermissionRequest's approve-and-stop is unaffected by collect-all."""
        chain = HandlerChain(allow_is_final=True)
        chain.add(MockHandler("approver", priority=10, terminal=True))
        later = MockHandler("later", priority=20, terminal=False)
        chain.add(later)

        chain.execute({"tool_name": "Read"}, collect_all=True)

        assert later.handle_called == 0


class CommittingHandler(MockHandler):
    """Records every post-decision commit it receives (Plan 00242, Phase 2)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.commits: list[Decision] = []

    def commit_side_effects(self, hook_input: dict[str, Any], chain_decision: Decision) -> None:
        self.commits.append(chain_decision)


class ExplodingCommitHandler(CommittingHandler):
    def commit_side_effects(self, hook_input: dict[str, Any], chain_decision: Decision) -> None:
        raise RuntimeError("commit exploded")


class TestSideEffectCommit:
    """Every executed handler hears the chain's FINAL decision after the loop."""

    def test_base_handler_commit_is_a_no_op(self) -> None:
        handler = MockHandler("plain", priority=10)
        handler.commit_side_effects({"tool_name": "Bash"}, Decision.DENY)

    def test_executed_handlers_are_told_the_merged_decision(self) -> None:
        chain = HandlerChain()
        advisor = CommittingHandler(
            "advisor",
            priority=10,
            terminal=False,
            result=HookResult(decision=Decision.ALLOW, context=["hint"]),
        )
        blocker = CommittingHandler(
            "blocker",
            priority=20,
            terminal=True,
            result=HookResult(decision=Decision.DENY, reason="no"),
        )
        chain.add(advisor)
        chain.add(blocker)

        chain.execute({"tool_name": "Bash"})

        assert advisor.commits == [Decision.DENY]
        assert blocker.commits == [Decision.DENY]

    def test_an_allowed_call_commits_allow(self) -> None:
        chain = HandlerChain()
        advisor = CommittingHandler("advisor", priority=10, terminal=False)
        chain.add(advisor)

        chain.execute({"tool_name": "Bash"})

        assert advisor.commits == [Decision.ALLOW]

    def test_a_handler_the_chain_never_reached_is_not_committed(self) -> None:
        chain = HandlerChain()
        chain.add(_deny("blocker", 10, "no"))
        unreached = CommittingHandler("unreached", priority=20, terminal=False)
        chain.add(unreached)

        chain.execute({"tool_name": "Bash"})

        assert unreached.commits == []

    def test_a_non_matching_handler_is_not_committed(self) -> None:
        chain = HandlerChain()
        silent = CommittingHandler("silent", priority=10, should_match=False)
        chain.add(silent)

        chain.execute({"tool_name": "Bash"})

        assert silent.commits == []

    def test_commit_runs_after_the_whole_chain_in_collect_all_mode(self) -> None:
        chain = HandlerChain()
        first = CommittingHandler(
            "first",
            priority=10,
            terminal=False,
            result=HookResult(decision=Decision.ALLOW, context=["hint"]),
        )
        chain.add(first)
        chain.add(_deny("blocker", 20, "no"))

        chain.execute({"tool_name": "Bash"}, collect_all=True)

        assert first.commits == [Decision.DENY]

    def test_a_crashing_commit_is_logged_and_does_not_change_the_decision(self) -> None:
        chain = HandlerChain()
        chain.add(ExplodingCommitHandler("boom", priority=10, terminal=False))

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.decision == Decision.ALLOW
        assert any("commit exploded" in line for line in result.result.context)

    def test_a_crashed_handler_is_not_committed(self) -> None:
        chain = HandlerChain()
        crasher = CommittingHandler("crasher", priority=10, raise_exception=ValueError("x"))
        chain.add(crasher)

        chain.execute({"tool_name": "Bash"}, strict_mode=False)

        assert crasher.commits == []


class TestAllowIsFinalOptIn:
    """PermissionRequest's 'approve and stop' is an EVENT-level opt-in.

    ``HandlerChain(allow_is_final=True)`` restores allow-short-circuits for
    the one chain whose semantic is that an approval concludes the request.
    It is never the default and it is not a handler flag.
    """

    def test_default_chain_is_not_allow_final(self) -> None:
        assert HandlerChain().allow_is_final is False

    def test_allow_final_chain_stops_at_a_terminal_allow(self) -> None:
        chain = HandlerChain(allow_is_final=True)
        chain.add(
            MockHandler(
                "approver",
                priority=10,
                terminal=True,
                result=HookResult(decision=Decision.ALLOW),
            )
        )
        skipped = MockHandler("skipped", priority=20, terminal=False)
        chain.add(skipped)

        result = chain.execute({"tool_name": "Read"})

        assert skipped.handle_called == 0
        assert result.terminated_by == "approver"
        assert result.result.decision == Decision.ALLOW

    def test_allow_final_chain_does_not_stop_at_a_non_terminal_allow(self) -> None:
        chain = HandlerChain(allow_is_final=True)
        chain.add(
            MockHandler(
                "advisor",
                priority=10,
                terminal=False,
                result=HookResult(decision=Decision.ALLOW, context=["fyi"]),
            )
        )
        successor = MockHandler("successor", priority=20, terminal=True)
        chain.add(successor)

        chain.execute({"tool_name": "Read"})

        assert successor.handle_called == 1


class TestAllowOnlyFieldsAreAccumulated:
    """``guidance``/``updated_input``/``worktree_path`` travel like ``context``.

    The decision stays most-restrictive-wins, but these three fields are
    accumulated information rather than a decision, so a contentless early
    ALLOW winning the decision must not swallow a later handler's advisory
    remedy or input rewrite.
    """

    def test_a_bare_allow_does_not_swallow_a_later_allows_guidance(self) -> None:
        chain = HandlerChain()
        chain.add(MockHandler("bare", priority=10, result=HookResult(decision=Decision.ALLOW)))
        chain.add(
            MockHandler(
                "advisor",
                priority=20,
                result=HookResult(
                    decision=Decision.ALLOW,
                    context=["short summary"],
                    guidance="SUGGESTION: the remedy text",
                    updated_input={"command": "rewritten"},
                ),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.decision == Decision.ALLOW
        assert result.result.guidance == "SUGGESTION: the remedy text"
        assert result.result.updated_input == {"command": "rewritten"}
        assert result.result.context == ["short summary"]

    def test_a_bare_allow_does_not_swallow_a_later_allows_worktree_path(self) -> None:
        chain = HandlerChain()
        chain.add(MockHandler("bare", priority=10, result=HookResult(decision=Decision.ALLOW)))
        chain.add(
            MockHandler(
                "namer",
                priority=20,
                result=HookResult(decision=Decision.ALLOW, worktree_path="/repo/wt/feature"),
            )
        )

        result = chain.execute({"hook_event_name": "WorktreeCreate"})

        assert result.result.worktree_path == "/repo/wt/feature"

    def test_the_first_handler_to_set_a_field_owns_it(self) -> None:
        """Accumulation is first-non-None, matching the reason/footer rule."""
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "first",
                priority=10,
                result=HookResult(decision=Decision.ALLOW, guidance="first remedy"),
            )
        )
        chain.add(
            MockHandler(
                "second",
                priority=20,
                result=HookResult(decision=Decision.ALLOW, guidance="second remedy"),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.guidance == "first remedy"

    def test_a_deny_wins_the_decision_and_keeps_its_own_reason(self) -> None:
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "advisor",
                priority=10,
                result=HookResult(decision=Decision.ALLOW, guidance="SUGGESTION: rewrite it"),
            )
        )
        chain.add(
            MockHandler(
                "blocker",
                priority=20,
                terminal=True,
                result=HookResult(decision=Decision.DENY, reason="BLOCKED: forbidden command"),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.decision == Decision.DENY
        assert result.result.reason == "BLOCKED: forbidden command"
        assert result.result.guidance == "SUGGESTION: rewrite it"

    def test_a_denys_own_guidance_is_never_overwritten_by_an_allows(self) -> None:
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "advisor",
                priority=10,
                result=HookResult(decision=Decision.ALLOW, guidance="allow guidance"),
            )
        )
        chain.add(
            MockHandler(
                "blocker",
                priority=20,
                terminal=True,
                result=HookResult(
                    decision=Decision.DENY, reason="denied", guidance="deny guidance"
                ),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.guidance == "deny guidance"

    def test_a_later_denys_guidance_reaches_an_earlier_denys_response(self) -> None:
        """The first deny owns the reason; a later deny's remedy is not lost."""
        chain = HandlerChain()
        chain.add(_deny("first-blocker", 10, "first reason", terminal=False))
        chain.add(
            MockHandler(
                "second-blocker",
                priority=20,
                terminal=False,
                result=HookResult(
                    decision=Decision.DENY, reason="second reason", guidance="second remedy"
                ),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.reason == "first reason"
        assert result.result.guidance == "second remedy"

    def test_an_allows_rule_is_not_attributed_to_a_denys_response(self) -> None:
        """``rule`` sub-classifies ONE decision, so it never crosses to another."""
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "advisor",
                priority=10,
                result=HookResult(decision=Decision.ALLOW, rule="R-ADVISORY"),
            )
        )
        chain.add(
            MockHandler(
                "blocker",
                priority=20,
                terminal=True,
                result=HookResult(decision=Decision.DENY, reason="denied"),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.rule is None

    def test_a_rule_carries_between_results_that_share_a_verdict(self) -> None:
        chain = HandlerChain()
        chain.add(MockHandler("bare", priority=10, result=HookResult(decision=Decision.ALLOW)))
        chain.add(
            MockHandler(
                "advisor",
                priority=20,
                result=HookResult(decision=Decision.ALLOW, rule="R-ADVISORY"),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.rule == "R-ADVISORY"

    def test_a_project_handlers_input_rewrite_survives_an_earlier_bare_allow(self) -> None:
        """``updated_input`` is the PreToolUse rewrite channel — losing it is worse."""
        chain = HandlerChain()
        chain.add(MockHandler("bare", priority=10, result=HookResult(decision=Decision.ALLOW)))
        chain.add(
            MockHandler(
                "rewriter",
                priority=90,
                result=HookResult(
                    decision=Decision.ALLOW, updated_input={"command": "safe --version"}
                ),
            )
        )

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.updated_input == {"command": "safe --version"}

    def test_collect_all_mode_accumulates_the_same_fields(self) -> None:
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "advisor",
                priority=10,
                result=HookResult(
                    decision=Decision.ALLOW, context=["hint"], guidance="advisor remedy"
                ),
            )
        )
        chain.add(_deny("blocker", 20, "denied"))

        result = chain.execute({"tool_name": "Bash"}, collect_all=True)

        assert result.result.decision == Decision.DENY
        assert result.result.guidance == "advisor remedy"

    def test_a_handler_that_never_matched_contributes_nothing(self) -> None:
        chain = HandlerChain()
        chain.add(
            MockHandler(
                "silent",
                priority=10,
                should_match=False,
                result=HookResult(decision=Decision.ALLOW, guidance="never shown"),
            )
        )
        chain.add(MockHandler("bare", priority=20, result=HookResult(decision=Decision.ALLOW)))

        result = chain.execute({"tool_name": "Bash"})

        assert result.result.guidance is None


class TestUnexpectedDispatchOutcomeFailsLoud:
    """Plan 00466 N40 n2: the production path used ``assert isinstance(outcome,
    DispatchSaturated)`` to narrow the else-branch of the dispatch-outcome
    check -- an assert that ``-O`` strips, silently leaving ``detail``
    unbound instead of failing. Replaced with an explicit ``elif``/``else``
    that raises. This test drives a dispatcher whose ``run()`` returns
    neither a real result nor either known sentinel, to exercise that
    explicit failure directly (an assert-based narrowing would never be
    reached by a real ``BoundedDispatcher.run()``, so this can only be
    proven with a fake).
    """

    def test_an_unrecognised_dispatch_outcome_raises_instead_of_silently_falling_through(
        self,
    ) -> None:
        from claude_code_hooks_daemon.core.bounded_dispatch import BoundedDispatcher

        class _BogusOutcomeDispatcher(BoundedDispatcher[object]):
            """Returns neither a real result nor a known sentinel."""

            def run(self, fn: Any, *, timeout: float, label: str) -> Any:
                return object()

        chain = HandlerChain()
        chain.add(
            MockHandler(
                "safety-guard",
                priority=10,
                terminal=True,
                tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
            )
        )

        with pytest.raises(TypeError, match="unexpected type"):
            chain.execute(
                {"tool_name": "Bash"},
                deadline_seconds=5.0,
                dispatcher=_BogusOutcomeDispatcher(),
            )


@pytest.mark.parametrize(
    "deadline_seconds",
    [None, Timeout.CHAIN_DEADLINE_DEFAULT],
    ids=["synchronous-path", "shipped-default-threaded-path"],
)
class TestUnderShippedDefaultDeadline:
    """Plan 00466 N40 n4: a representative slice of core execute() behaviour,
    re-run under the shipped default ``deadline_seconds`` (the production
    THREADED path, via a real ``BoundedDispatcher`` dispatch) as well as the
    ``None`` synchronous path the rest of this suite almost exclusively
    exercises. Both parametrisations use fast MockHandlers, so a real dispatch
    against ``Timeout.CHAIN_DEADLINE_DEFAULT`` (20s) never approaches its own
    budget -- what this class actually verifies is that going through a real
    thread, semaphore and cancellation-token bind/reset produces the SAME
    observable decision as the synchronous path, not a timing property.
    """

    def test_empty_chain_returns_allow(self, deadline_seconds: float | None) -> None:
        chain = HandlerChain()

        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=deadline_seconds)

        assert result.result.decision == Decision.ALLOW
        assert result.handlers_executed == []
        assert result.terminated_by is None

    def test_matches_is_called_on_every_handler(self, deadline_seconds: float | None) -> None:
        chain = HandlerChain()
        h1 = MockHandler("h1", should_match=False)
        h2 = MockHandler("h2", should_match=True)
        chain.add(h1)
        chain.add(h2)

        chain.execute({"tool_name": "Bash"}, deadline_seconds=deadline_seconds)

        assert h1.matches_called == 1
        assert h2.matches_called == 1
        assert h2.handle_called == 1
        assert h1.handle_called == 0

    def test_a_terminal_deny_stops_the_chain(self, deadline_seconds: float | None) -> None:
        chain = HandlerChain()
        h1 = MockHandler("h1", priority=10, terminal=False)
        h2 = MockHandler(
            "h2",
            priority=20,
            terminal=True,
            result=HookResult(decision=Decision.DENY, reason="stop here"),
        )
        h3 = MockHandler("h3", priority=30, terminal=False)
        chain.add(h1)
        chain.add(h2)
        chain.add(h3)

        result = chain.execute({"tool_name": "Bash"}, deadline_seconds=deadline_seconds)

        assert h1.handle_called == 1
        assert h2.handle_called == 1
        assert h3.handle_called == 0
        assert result.terminated_by == "h2"
        assert result.result.decision == Decision.DENY

    def test_a_raising_handler_denies_only_in_strict_mode(
        self, deadline_seconds: float | None
    ) -> None:
        chain = HandlerChain()
        chain.add(MockHandler("boom", priority=10, raise_exception=ValueError("boom")))

        allowed = chain.execute(
            {"tool_name": "Bash"}, strict_mode=False, deadline_seconds=deadline_seconds
        )
        denied = chain.execute(
            {"tool_name": "Bash"}, strict_mode=True, deadline_seconds=deadline_seconds
        )

        assert allowed.result.decision == Decision.ALLOW
        assert denied.result.decision == Decision.DENY

    def test_the_first_restrictive_handler_wins_over_a_later_allow(
        self, deadline_seconds: float | None
    ) -> None:
        chain = HandlerChain()
        chain.add(_deny("blocker", 10, "denied", terminal=False))
        chain.add(
            MockHandler(
                "advisor",
                priority=20,
                result=HookResult(decision=Decision.ALLOW, context=["hint"]),
            )
        )

        result = chain.execute(
            {"tool_name": "Bash"}, collect_all=True, deadline_seconds=deadline_seconds
        )

        assert result.result.decision == Decision.DENY
        assert result.result.reason is not None
        assert result.result.reason.startswith("denied")
