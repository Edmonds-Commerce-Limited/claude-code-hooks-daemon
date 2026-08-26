"""Plan 00271 Task 2.2 — UserPromptSubmit blocking is documented and must work.

The docs put UserPromptSubmit in the top-level ``decision: "block"`` group
(with ``reason`` shown to the user). The daemon previously had no way to emit
that, dropped a DENY silently, and yet marked the event ``can_block=True`` —
three sources of truth disagreeing (audit item 5).
"""

from __future__ import annotations

from claude_code_hooks_daemon.constants.events import EventID
from claude_code_hooks_daemon.core.hook_result import (
    REFUSAL_CAPABLE_EVENTS,
    Decision,
    HookResult,
)
from claude_code_hooks_daemon.core.response_schemas import validate_response

_EVENT = "UserPromptSubmit"


class TestClaimTables:
    def test_refusal_table_claims_deny(self) -> None:
        assert _EVENT in REFUSAL_CAPABLE_EVENTS[Decision.DENY]

    def test_events_catalogue_agrees(self) -> None:
        assert EventID.USER_PROMPT_SUBMIT.can_block is True


class TestSerialisation:
    def test_deny_emits_top_level_block(self) -> None:
        result = HookResult(decision=Decision.DENY, reason="prompt rejected")
        payload = result.to_json(_EVENT)
        assert payload["decision"] == "block"
        assert payload["reason"] == "prompt rejected"
        assert validate_response(_EVENT, payload) == []

    def test_deny_with_context_keeps_additional_context(self) -> None:
        result = HookResult(
            decision=Decision.DENY, reason="no", context=["policy: prompts must name a plan"]
        )
        payload = result.to_json(_EVENT)
        assert payload["decision"] == "block"
        assert (
            "policy: prompts must name a plan"
            in payload["hookSpecificOutput"]["additionalContext"]
        )

    def test_allow_with_context_is_unchanged(self) -> None:
        result = HookResult(decision=Decision.ALLOW, context=["git status: clean"])
        payload = result.to_json(_EVENT)
        assert "decision" not in payload
        assert payload["hookSpecificOutput"]["additionalContext"] == "git status: clean"
        assert validate_response(_EVENT, payload) == []

    def test_silent_allow_is_empty(self) -> None:
        assert HookResult(decision=Decision.ALLOW).to_json(_EVENT) == {}
