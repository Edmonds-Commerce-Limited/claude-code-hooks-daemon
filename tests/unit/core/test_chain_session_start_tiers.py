"""Plan 00416 Task 1.2 — rendering the tier into the emitted SessionStart block.

``HandlerChain`` stays fully generic: it knows nothing about "SessionStart" as
a concept. What it gains here is a generic per-handler context hook
(``context_transform``), applied to each matched handler's OWN context lines
before they are flattened into the merged response — this is the only point
in the dispatch pipeline where a context line is still paired with the
handler that produced it. The router wires the SessionStart-specific tier
transform in (see ``test_router_session_start_tiers.py``); this file proves
the hook itself: applied when configured, left alone otherwise, and per
handler rather than once for the whole merged block.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult


class _ContextHandler(Handler):
    """A handler that always matches and returns fixed context."""

    def __init__(self, name: str, context: list[str], priority: int = 50) -> None:
        super().__init__(name=name, priority=priority, terminal=False)
        self._context = context

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=list(self._context))

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="context handler",
                command="echo test",
                description="test fixture",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                test_type=TestType.CONTEXT,
            )
        ]


def _shout(handler: Handler, context: list[str]) -> list[str]:
    """A trivial, easily-asserted transform: upper-case each line."""
    return [line.upper() for line in context]


class TestContextTransformHook:
    def test_no_transform_configured_leaves_context_untouched(self) -> None:
        chain = HandlerChain()
        chain.add(_ContextHandler("h1", ["hello"]))
        result = chain.execute({})
        assert result.result.context == ["hello"]

    def test_configured_transform_is_applied_per_handler(self) -> None:
        chain = HandlerChain(context_transform=_shout)
        chain.add(_ContextHandler("h1", ["hello"]))
        result = chain.execute({})
        assert result.result.context == ["HELLO"]

    def test_transform_receives_the_producing_handler(self) -> None:
        seen: list[str] = []

        def _record(handler: Handler, context: list[str]) -> list[str]:
            seen.append(handler.name)
            return context

        chain = HandlerChain(context_transform=_record)
        chain.add(_ContextHandler("h1", ["a"]))
        chain.add(_ContextHandler("h2", ["b"], priority=60))
        chain.execute({})
        assert seen == ["h1", "h2"]

    def test_transform_applies_independently_to_each_handler(self) -> None:
        """Each handler's OWN lines are transformed before merging — proves
        the hook runs per handler, not once against the flattened block."""
        chain = HandlerChain(context_transform=_shout)
        chain.add(_ContextHandler("h1", ["one"]))
        chain.add(_ContextHandler("h2", ["two"], priority=60))
        result = chain.execute({})
        assert result.result.context == ["ONE", "TWO"]

    def test_transform_is_skipped_for_a_handler_with_no_context(self) -> None:
        calls = 0

        def _count(handler: Handler, context: list[str]) -> list[str]:
            nonlocal calls
            calls += 1
            return context

        chain = HandlerChain(context_transform=_count)
        chain.add(_ContextHandler("silent", []))
        chain.execute({})
        assert calls == 0
