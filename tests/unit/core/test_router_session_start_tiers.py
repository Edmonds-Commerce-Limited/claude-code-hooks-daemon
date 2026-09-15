"""Plan 00416 Task 1.2 — the router wires SessionStart tier tagging in.

``HandlerChain`` (see ``test_chain_session_start_tiers.py``) is generic; this
is the one place that says "SessionStart's per-handler context gets the tier
transform, nothing else does" — mirroring how ``_ALLOW_IS_FINAL_EVENTS``
already scopes ``allow_is_final`` to PermissionRequest alone.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.router import EventRouter


class _ContextHandler(Handler):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, priority=50, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=["do the thing"])

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


class TestSessionStartChainGetsTheTierTransform:
    def test_session_start_chain_has_a_context_transform(self) -> None:
        router = EventRouter()
        chain = router.get_chain(EventType.SESSION_START)
        assert chain.context_transform is not None

    def test_session_start_output_is_tagged_with_a_tier(self) -> None:
        router = EventRouter()
        router.register(EventType.SESSION_START, _ContextHandler("h1"))
        result = router.route(EventType.SESSION_START, {})
        assert result.result.context == ["[INFO] do the thing"]


class TestOtherEventsAreUnaffected:
    def test_pre_tool_use_chain_has_no_context_transform(self) -> None:
        router = EventRouter()
        chain = router.get_chain(EventType.PRE_TOOL_USE)
        assert chain.context_transform is None

    def test_session_end_chain_has_no_context_transform(self) -> None:
        router = EventRouter()
        chain = router.get_chain(EventType.SESSION_END)
        assert chain.context_transform is None

    def test_other_events_context_is_never_tagged(self) -> None:
        router = EventRouter()
        router.register(EventType.NOTIFICATION, _ContextHandler("h1"))
        result = router.route(EventType.NOTIFICATION, {})
        assert result.result.context == ["do the thing"]
