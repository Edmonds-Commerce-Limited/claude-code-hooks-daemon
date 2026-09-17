"""A scoped handler is skipped before `matches()` is ever consulted (Plan 00423).

The gate belongs in the chain, not in each handler's `matches()`. Two reasons,
both learned elsewhere in this codebase:

- A per-handler check is 142 opportunities to forget one, and a handler that
  forgets is a handler still nudging subagents — the exact defect issue #40
  reports. One gate cannot be forgotten.
- `matches()` is the handler's own question about the payload. Whether the
  handler should be consulted AT ALL is the registry's question, and answering
  it inside `matches()` would put a policy decision where a content decision
  lives.

Skipped means skipped entirely: not matched, not executed, no context, no
verdict. A handler that ran and returned ALLOW is NOT the same as one that
never ran — most-restrictive-wins aggregates the former, and `verdicts.jsonl`
records it.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.result_types import Decision
from claude_code_hooks_daemon.daemon.synthetic_traffic import SYNTHETIC_SOURCE_FIELD

_AGENT_ID = "agent_01H9XQK2M4N7P"


class _Recorder(Handler):
    """Matches everything and records that it was asked."""

    def __init__(self, handler_id: str, scope: HandlerScope) -> None:
        super().__init__(handler_id=handler_id, priority=Priority.DEFAULT, terminal=False)
        self.scope = scope
        self.matches_called = False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        self.matches_called = True
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=[f"ran:{self.name}"])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


def _event(**extra: Any) -> dict[str, Any]:
    return {"hook_event_name": "PreToolUse", "tool_name": "Write", **extra}


_MAIN = _event(session_id="real-session")
_SUB = _event(session_id="real-session", agent_id=_AGENT_ID)
_SYNTHETIC = _event(session_id="real-session", **{SYNTHETIC_SOURCE_FIELD: "playbook-probe"})


def _chain(*handlers: Handler) -> HandlerChain:
    chain = HandlerChain()
    for handler in handlers:
        chain.add(handler)
    return chain


def _run(scope: HandlerScope, hook_input: dict[str, Any]) -> _Recorder:
    handler = _Recorder("scoped-probe", scope)
    _chain(handler).execute(hook_input)
    return handler


class TestTheGateRunsBeforeMatches:
    def test_a_main_scoped_handler_is_not_even_asked_on_a_subagent_event(self) -> None:
        assert not _run(HandlerScope.MAIN, _SUB).matches_called

    def test_a_sub_scoped_handler_is_not_even_asked_on_the_main_thread(self) -> None:
        assert not _run(HandlerScope.SUB, _MAIN).matches_called

    def test_a_main_scoped_handler_is_asked_on_the_main_thread(self) -> None:
        assert _run(HandlerScope.MAIN, _MAIN).matches_called

    def test_an_all_scoped_handler_is_asked_on_every_event(self) -> None:
        for event in (_MAIN, _SUB, _SYNTHETIC):
            assert _run(HandlerScope.ALL, event).matches_called


class TestTheDefaultChangesNothing:
    """A handler nobody has scoped must behave exactly as before."""

    def test_a_handler_constructed_without_a_scope_defaults_to_all(self) -> None:
        handler = _Recorder("unscoped", HandlerScope.ALL)
        assert handler.scope is HandlerScope.ALL

    def test_the_base_handler_defaults_to_all_without_being_told(self) -> None:
        class _Plain(Handler):
            def matches(self, hook_input: dict[str, Any]) -> bool:
                return True

            def handle(self, hook_input: dict[str, Any]) -> HookResult:
                return HookResult(decision=Decision.ALLOW)

            def get_claude_md(self) -> str | None:
                return None

            def get_acceptance_tests(self) -> list[Any]:
                return []

        assert _Plain(handler_id="plain").scope is HandlerScope.ALL


class TestASkippedHandlerLeavesNoTrace:
    """Skipped is not the same as ran-and-allowed."""

    def test_it_is_absent_from_handlers_matched_and_executed(self) -> None:
        handler = _Recorder("scoped-probe", HandlerScope.MAIN)
        result = _chain(handler).execute(_SUB)
        assert handler.name not in result.handlers_matched
        assert handler.name not in result.handlers_executed

    def test_its_context_does_not_reach_the_response(self) -> None:
        handler = _Recorder("scoped-probe", HandlerScope.MAIN)
        result = _chain(handler).execute(_SUB)
        assert not any("ran:scoped-probe" in line for line in (result.result.context or []))


class TestTheSyntheticTrap:
    """A fabricated event must not be treated as the main thread.

    Without this, enabling any `scope: MAIN` handler reddens the acceptance
    suite — `orchestrator_simulate`'s docstring records that failure happening
    on the day blocking was first enabled.
    """

    def test_a_main_scoped_handler_is_skipped_for_a_fabricated_event(self) -> None:
        assert not _run(HandlerScope.MAIN, _SYNTHETIC).matches_called

    def test_a_sub_scoped_handler_is_skipped_for_a_fabricated_event(self) -> None:
        assert not _run(HandlerScope.SUB, _SYNTHETIC).matches_called


class TestScopingOneHandlerDoesNotSilenceTheChain:
    def test_an_unscoped_sibling_still_runs_when_a_scoped_one_is_skipped(self) -> None:
        scoped = _Recorder("scoped-probe", HandlerScope.MAIN)
        sibling = _Recorder("sibling", HandlerScope.ALL)
        result = _chain(scoped, sibling).execute(_SUB)
        assert not scoped.matches_called
        assert sibling.matches_called
        assert sibling.name in result.handlers_executed


class TestADenyingScopedHandlerStillDeniesWhereItApplies:
    """Switching a handler off by scope must not switch it off everywhere."""

    def test_the_deny_survives_on_an_admitted_event(self) -> None:
        class _Denier(_Recorder):
            def handle(self, hook_input: dict[str, Any]) -> HookResult:
                return HookResult(decision=Decision.DENY, reason="nope")

        denier = _Denier("denier", HandlerScope.MAIN)
        assert _chain(denier).execute(_MAIN).result.decision is Decision.DENY

    def test_and_is_absent_on_a_refused_one(self) -> None:
        class _Denier(_Recorder):
            def handle(self, hook_input: dict[str, Any]) -> HookResult:
                return HookResult(decision=Decision.DENY, reason="nope")

        denier = _Denier("denier", HandlerScope.MAIN)
        assert _chain(denier).execute(_SUB).result.decision is not Decision.DENY


@pytest.mark.parametrize("scope", list(HandlerScope), ids=lambda s: s.value)
def test_every_scope_admits_at_least_one_real_event(scope: HandlerScope) -> None:
    """Guard the guard: a scope that admits nothing would pass every test above."""
    assert any(_run(scope, event).matches_called for event in (_MAIN, _SUB))
