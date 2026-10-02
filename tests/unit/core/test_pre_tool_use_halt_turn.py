"""Plan 00479 Task 4.2 prerequisite: a PreToolUse deny that also halts the turn.

The vendored hooks contract (remote-docs/code.claude.com/docs/en/hooks.md) lists
``continue`` and ``stopReason`` as universal output fields and says "For
``PreToolUse`` and ``PostToolUse`` hooks, the stop applies even when the tool
call fails". A handler asks for it with ``halt_turn`` / ``stop_reason`` on its
result; the chain must keep that request when other handlers' results combine.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import validate_response
from claude_code_hooks_daemon.core.result_types import GatingResult

_EVENT = "PreToolUse"


class _Fixed(Handler):
    """A handler that returns a canned result for every input."""

    def __init__(
        self, name: str, priority: int, result: HookResult, *, terminal: bool = False
    ) -> None:
        super().__init__(name=name, priority=priority, terminal=terminal)
        self._result = result

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return self._result

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestSchema:
    def test_schema_accepts_continue_false_and_stop_reason(self) -> None:
        payload = {
            "continue": False,
            "stopReason": "paused",
            "hookSpecificOutput": {"hookEventName": _EVENT, "permissionDecision": "deny"},
        }
        assert validate_response(_EVENT, payload) == []

    def test_schema_rejects_non_boolean_continue(self) -> None:
        assert validate_response(_EVENT, {"continue": "no"}) != []

    def test_schema_rejects_non_string_stop_reason(self) -> None:
        assert validate_response(_EVENT, {"stopReason": 3}) != []

    def test_schema_still_rejects_unknown_top_level_key(self) -> None:
        assert validate_response(_EVENT, {"bogus": True}) != []


class TestSerialisation:
    def test_halting_deny_emits_continue_false_and_stop_reason(self) -> None:
        result = GatingResult.deny_and_halt("tool denied", stop_reason="usage pause")
        payload = result.to_json(_EVENT)
        assert payload["continue"] is False
        assert payload["stopReason"] == "usage pause"
        assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "tool denied" in payload["hookSpecificOutput"]["permissionDecisionReason"]
        assert validate_response(_EVENT, payload) == []

    def test_stop_reason_falls_back_to_deny_reason_without_continuation_suffix(self) -> None:
        result = GatingResult(decision=Decision.DENY, reason="why", halt_turn=True)
        payload = result.to_json(_EVENT)
        assert payload["stopReason"] == "why"

    def test_plain_deny_is_unchanged(self) -> None:
        payload = GatingResult.deny("nope").to_json(_EVENT)
        assert set(payload) == {"hookSpecificOutput"}
        assert set(payload["hookSpecificOutput"]) == {
            "hookEventName",
            "permissionDecision",
            "permissionDecisionReason",
        }

    def test_plain_allow_is_still_silent(self) -> None:
        assert HookResult(decision=Decision.ALLOW).to_json(_EVENT) == {}

    def test_plain_deny_bytes_pinned(self) -> None:
        payload = HookResult(decision=Decision.DENY, reason="r").to_json(_EVENT)
        hso = payload["hookSpecificOutput"]
        assert payload == {"hookSpecificOutput": hso}
        assert hso["hookEventName"] == _EVENT
        assert hso["permissionDecision"] == "deny"
        assert hso["permissionDecisionReason"].startswith("r")

    def test_halt_requires_deny(self) -> None:
        with pytest.raises(ValidationError):
            HookResult(decision=Decision.ALLOW, halt_turn=True)

    def test_stop_reason_requires_halt(self) -> None:
        with pytest.raises(ValidationError):
            HookResult(decision=Decision.DENY, reason="r", stop_reason="x")


class TestChainCombination:
    def _run(self, *handlers: Handler) -> HookResult:
        chain = HandlerChain()
        for handler in handlers:
            chain.add(handler)
        return chain.execute({"tool_name": "Bash"}).result

    def test_halt_survives_an_earlier_advisory_allow(self) -> None:
        result = self._run(
            _Fixed("advisor", 10, HookResult(decision=Decision.ALLOW, context=["fyi"])),
            _Fixed("gate", 20, GatingResult.deny_and_halt("d", stop_reason="s"), terminal=True),
        )
        assert result.decision == Decision.DENY
        assert result.halt_turn is True
        assert result.stop_reason == "s"
        payload = result.to_json(_EVENT)
        assert payload["continue"] is False
        assert payload["stopReason"] == "s"

    def test_halt_survives_an_earlier_plain_deny(self) -> None:
        result = self._run(
            _Fixed("plain", 10, GatingResult.deny("first")),
            _Fixed("gate", 20, GatingResult.deny_and_halt("d", stop_reason="s")),
        )
        assert result.decision == Decision.DENY
        assert result.reason is not None and "first" in result.reason
        assert result.halt_turn is True
        assert result.stop_reason == "s"

    def test_halt_survives_an_earlier_ask(self) -> None:
        result = self._run(
            _Fixed("asker", 10, GatingResult.ask("confirm?")),
            _Fixed("gate", 20, GatingResult.deny_and_halt("d", stop_reason="s")),
        )
        assert result.decision == Decision.DENY
        assert result.halt_turn is True
        assert result.stop_reason == "s"
        assert result.to_json(_EVENT)["continue"] is False

    def test_halt_survives_collect_all_merge(self) -> None:
        chain = HandlerChain()
        chain.add(_Fixed("plain", 10, GatingResult.deny("first")))
        chain.add(_Fixed("gate", 20, GatingResult.deny_and_halt("d", stop_reason="s")))
        result = chain.execute({"tool_name": "Bash"}, collect_all=True).result
        assert result.halt_turn is True
        assert result.stop_reason == "s"

    def test_no_halt_requested_means_none_emitted(self) -> None:
        result = self._run(
            _Fixed("a", 10, GatingResult.deny("x")),
            _Fixed("b", 20, HookResult(decision=Decision.ALLOW, context=["c"])),
        )
        assert result.halt_turn is False
        assert "continue" not in result.to_json(_EVENT)
