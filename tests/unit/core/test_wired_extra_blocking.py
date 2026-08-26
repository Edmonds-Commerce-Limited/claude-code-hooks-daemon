"""Plan 00271 Task 2.3 — correct block serialisation for wired-extra events.

The docs give these events real blocking mechanisms: a top-level
``decision: "block"`` for UserPromptExpansion, PostToolUseFailure,
PostToolBatch, TaskCreated and ConfigChange, and ``continue: false`` +
``stopReason`` for TeammateIdle and TaskCompleted. The daemon used to
serialise a DENY on any of them through the systemMessage fallback, emitting
the undefined token ``{"decision": "deny"}`` — which VALIDATED under the
permissive fail-open schema and was ignored by Claude Code, silently
(audit item 9).
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.hook_result import (
    REFUSAL_CAPABLE_EVENTS,
    Decision,
    HookResult,
)
from claude_code_hooks_daemon.core.response_schemas import validate_response

_TOP_LEVEL_EVENTS = [
    "UserPromptExpansion",
    "PostToolUseFailure",
    "PostToolBatch",
    "TaskCreated",
    "ConfigChange",
]
_CONTINUE_FALSE_EVENTS = ["TeammateIdle", "TaskCompleted"]
_HSO_CONTEXT_EVENTS = {"UserPromptExpansion", "PostToolUseFailure", "PostToolBatch"}


class TestRefusalClaims:
    @pytest.mark.parametrize("event", _TOP_LEVEL_EVENTS + _CONTINUE_FALSE_EVENTS)
    def test_deny_is_claimed_deliverable(self, event: str) -> None:
        assert event in REFUSAL_CAPABLE_EVENTS[Decision.DENY]


class TestTopLevelBlockSerialisation:
    @pytest.mark.parametrize("event", _TOP_LEVEL_EVENTS)
    def test_deny_emits_documented_block_token(self, event: str) -> None:
        payload = HookResult(decision=Decision.DENY, reason="nope").to_json(event)
        assert payload["decision"] == "block"
        assert payload["reason"] == "nope"
        assert validate_response(event, payload) == []

    @pytest.mark.parametrize("event", _TOP_LEVEL_EVENTS)
    def test_old_undefined_deny_token_is_rejected_by_schema(self, event: str) -> None:
        assert validate_response(event, {"decision": "deny", "reason": "x"}) != []

    @pytest.mark.parametrize("event", sorted(_HSO_CONTEXT_EVENTS))
    def test_allow_context_travels_in_additional_context(self, event: str) -> None:
        payload = HookResult(decision=Decision.ALLOW, context=["note"]).to_json(event)
        assert payload["hookSpecificOutput"]["additionalContext"] == "note"
        assert validate_response(event, payload) == []

    @pytest.mark.parametrize("event", ["TaskCreated", "ConfigChange"])
    def test_allow_context_still_serialises_validly(self, event: str) -> None:
        payload = HookResult(decision=Decision.ALLOW, context=["note"]).to_json(event)
        assert validate_response(event, payload) == []


class TestContinueFalseSerialisation:
    @pytest.mark.parametrize("event", _CONTINUE_FALSE_EVENTS)
    def test_deny_emits_continue_false(self, event: str) -> None:
        payload = HookResult(decision=Decision.DENY, reason="not done").to_json(event)
        assert payload["continue"] is False
        assert payload["stopReason"] == "not done"
        assert validate_response(event, payload) == []

    @pytest.mark.parametrize("event", _CONTINUE_FALSE_EVENTS)
    def test_old_undefined_deny_token_is_rejected_by_schema(self, event: str) -> None:
        assert validate_response(event, {"decision": "deny", "reason": "x"}) != []

    @pytest.mark.parametrize("event", _CONTINUE_FALSE_EVENTS)
    def test_silent_allow_is_empty(self, event: str) -> None:
        assert HookResult(decision=Decision.ALLOW).to_json(event) == {}
