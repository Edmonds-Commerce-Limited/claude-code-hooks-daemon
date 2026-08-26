"""Plan 00271 Task 2.5 — PreToolUse ``updatedInput`` and ``defer``.

The docs give PreToolUse four outcomes (allow/deny/ask/defer) plus
``updatedInput``, which replaces the tool's ENTIRE input object before it
runs — and is the only way to auto-answer AskUserQuestion/ExitPlanMode in
non-interactive mode. Neither was expressible (audit items 1 and 2); this
unblocks Plan 00270's command-rewrite mode.
"""

from __future__ import annotations

from claude_code_hooks_daemon.core.hook_result import (
    REFUSAL_CAPABLE_EVENTS,
    Decision,
    HookResult,
)
from claude_code_hooks_daemon.core.response_schemas import validate_response
from claude_code_hooks_daemon.core.result_types import GatingResult, decisions_of

_EVENT = "PreToolUse"


class TestDeferDecision:
    def test_defer_is_a_decision(self) -> None:
        assert Decision.DEFER.value == "defer"

    def test_defer_is_claimed_for_pre_tool_use_only(self) -> None:
        assert REFUSAL_CAPABLE_EVENTS[Decision.DEFER] == frozenset({_EVENT})

    def test_gating_tier_carries_defer(self) -> None:
        assert Decision.DEFER in decisions_of(GatingResult)

    def test_gating_defer_factory(self) -> None:
        result = GatingResult.defer()
        assert result.decision == Decision.DEFER

    def test_defer_serialises_to_documented_token(self) -> None:
        payload = HookResult(decision=Decision.DEFER).to_json(_EVENT)
        assert payload["hookSpecificOutput"]["permissionDecision"] == "defer"
        assert validate_response(_EVENT, payload) == []

    def test_defer_omits_ignored_fields(self) -> None:
        """The docs say reason/updatedInput/additionalContext are ignored on defer."""
        result = HookResult(
            decision=Decision.DEFER,
            reason="later",
            context=["ctx"],
            updated_input={"command": "x"},
        )
        payload = result.to_json(_EVENT)
        hso = payload["hookSpecificOutput"]
        assert "permissionDecisionReason" not in hso
        assert "updatedInput" not in hso
        assert "additionalContext" not in hso


class TestUpdatedInput:
    def test_allow_with_updated_input_serialises(self) -> None:
        result = HookResult(decision=Decision.ALLOW, updated_input={"command": "npm run lint"})
        payload = result.to_json(_EVENT)
        assert payload["hookSpecificOutput"]["updatedInput"] == {"command": "npm run lint"}
        assert validate_response(_EVENT, payload) == []

    def test_ask_with_updated_input_serialises(self) -> None:
        result = HookResult(
            decision=Decision.ASK, reason="confirm rewrite", updated_input={"command": "safe"}
        )
        payload = result.to_json(_EVENT)
        hso = payload["hookSpecificOutput"]
        assert hso["permissionDecision"] == "ask"
        assert hso["updatedInput"] == {"command": "safe"}
        assert validate_response(_EVENT, payload) == []

    def test_absent_updated_input_is_not_emitted(self) -> None:
        payload = HookResult(decision=Decision.ALLOW, context=["hi"]).to_json(_EVENT)
        assert "updatedInput" not in payload["hookSpecificOutput"]
