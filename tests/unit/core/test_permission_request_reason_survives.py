"""A PermissionRequest refusal must explain itself.

``_format_permission_request_response`` emitted ``decision.behavior`` and, from
``context``, an ``additionalContext`` — but never read ``self.reason``. So a
denial arrived carrying no explanation at all, while the sibling PreToolUse
formatter has always emitted ``permissionDecisionReason`` for exactly this.

This is reachable, not theoretical. ``AutoApproveReadsHandler`` denies a
non-read tool that reaches ``handle()`` with a three-line reason naming the tool
and saying which tools are auto-approved
(``handlers/permission_request/auto_approve_reads.py:84``). Every word of it was
discarded.

The channel already exists and is already used on this event:
``PERMISSION_REQUEST_SCHEMA`` permits ``additionalContext`` inside
``hookSpecificOutput``, and the formatter already writes ``context`` there. The
nested ``decision`` object cannot carry it — it permits only ``behavior`` and
``updatedInput`` — so this is not a case of choosing between two channels.

Found by cross-producting every decision/reason/context/guidance combination
against every strict schema: 76 of 104 deny/ask-with-reason cases preserved the
reason, and this was among the 28 that did not.
"""

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import validate_response

_EVENT = "PermissionRequest"
_REASON = "BLOCKED: Permission request for non-read tool 'Bash'"


class TestPermissionRequestRefusalExplainsItself:
    """The reason is the only thing that tells a user WHY."""

    @pytest.mark.parametrize("decision", [Decision.DENY, Decision.ASK])
    def test_the_reason_reaches_the_response(self, decision: Decision) -> None:
        response = HookResult(decision=decision, reason=_REASON).to_json(_EVENT)

        assert _REASON in str(response), (
            f"a {decision.value} on {_EVENT} discarded its reason entirely, so the "
            "user is refused with no explanation"
        )

    @pytest.mark.parametrize("decision", [Decision.DENY, Decision.ASK])
    def test_the_response_is_still_schema_valid(self, decision: Decision) -> None:
        """The reason must go somewhere the schema actually permits."""
        response = HookResult(decision=decision, reason=_REASON).to_json(_EVENT)

        assert not validate_response(_EVENT, response)

    def test_the_decision_still_survives_alongside_the_reason(self) -> None:
        """Adding an explanation must not disturb the decision itself."""
        response = HookResult(decision=Decision.DENY, reason=_REASON).to_json(_EVENT)

        assert response["hookSpecificOutput"]["decision"] == {"behavior": "deny"}

    def test_reason_and_context_both_survive_together(self) -> None:
        """They share one channel, so neither may overwrite the other."""
        response = HookResult(
            decision=Decision.DENY, reason=_REASON, context=["extra context line"]
        ).to_json(_EVENT)

        combined = response["hookSpecificOutput"]["additionalContext"]
        assert _REASON in combined
        assert "extra context line" in combined

    def test_an_allow_without_a_reason_is_unchanged(self) -> None:
        """The common path must not grow an empty context key.

        A silent allow short-circuits in ``to_json`` before any event formatter
        runs, so the answer is ``{}`` rather than an allow-shaped envelope.
        """
        assert HookResult(decision=Decision.ALLOW).to_json(_EVENT) == {}

    def test_an_allow_with_context_does_not_gain_a_reason(self) -> None:
        """Only a refusal's reason is promoted; an allow's is not an explanation."""
        response = HookResult(
            decision=Decision.ALLOW, reason="should not appear", context=["ctx"]
        ).to_json(_EVENT)

        assert response["hookSpecificOutput"]["additionalContext"] == "ctx"

    def test_the_real_handler_refusal_carries_its_explanation(self) -> None:
        """End-to-end against the handler that actually produces this."""
        from claude_code_hooks_daemon.handlers.permission_request.auto_approve_reads import (
            AutoApproveReadsHandler,
        )

        result = AutoApproveReadsHandler().handle(
            {"tool_name": "Bash", "permission_mode": "bypassPermissions"}
        )
        response = result.to_json(_EVENT)

        assert not validate_response(_EVENT, response)
        if result.decision == Decision.DENY:
            assert "non-read tool" in str(
                response
            ), "the handler's own refusal text did not reach the response"
