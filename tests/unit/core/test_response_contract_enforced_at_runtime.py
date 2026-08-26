"""An invalid response must never reach Claude Code, and a deny must never weaken.

The response schemas were a real contract that production never consulted: only
``server.py``'s docstring mentioned the module, so ``validate_response`` ran in
tests alone. Meanwhile ``_format_system_message_response`` deliberately emits
``{"decision": ...}`` for a DENY on an event that cannot express one, its comment
saying "This will fail schema validation as expected" — a tripwire wired to a
detector that was switched off. The live effect was a silent DOWNGRADE: the deny
vanishes from the wire response, the handler believes it blocked, nothing blocked.

Enforcement lives in ``to_json`` because that is the single choke point. All three
production call sites (``front_controller``, ``daemon/server``, ``daemon/controller``)
funnel through it, so a check there cannot be bypassed by adding a fourth.

**Why enforcement does not reuse the daemon error response.**
``generate_daemon_error_response`` is fail-open for every event except
Stop/SubagentStop — it returns ``HookResult.allow(context=...)``. Routing a
contract failure through it would turn a failed DENY into an ALLOW, converting a
block into a permit. A guard whose failure mode is "permit the thing you were
trying to stop" is worse than no guard. So the fallback here is chosen per event
to be **never weaker than what the handler asked for**.
"""

import logging

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import validate_response

#: Events whose schema can carry a refusal.
_DECISION_CAPABLE = ("PreToolUse", "PostToolUse", "Stop", "SubagentStop")

#: Events that physically cannot express a refusal on the wire.
_MESSAGE_ONLY = ("SessionStart", "SessionEnd", "Notification")


class TestEveryEmittedResponseSatisfiesItsSchema:
    """The property: to_json never returns something the schema rejects."""

    @pytest.mark.parametrize("event_name", _DECISION_CAPABLE + _MESSAGE_ONLY)
    @pytest.mark.parametrize("decision", [Decision.ALLOW, Decision.DENY, Decision.ASK])
    def test_no_decision_on_any_event_produces_an_invalid_response(
        self, event_name: str, decision: Decision
    ) -> None:
        """Including the combinations the serialiser used to fail deliberately."""
        response = HookResult(decision=decision, reason="because").to_json(event_name)

        assert not validate_response(event_name, response), (
            f"to_json emitted {response} for {decision.value} on {event_name}, "
            "which its own schema rejects"
        )


class TestARefusalIsNeverSilentlyWeakened:
    """The safety half — strictness must not invert a block into a permit."""

    @pytest.mark.parametrize("event_name", _DECISION_CAPABLE)
    def test_a_deny_stays_a_deny_on_events_that_can_express_one(self, event_name: str) -> None:
        """Enforcement must not downgrade a refusal it could have carried."""
        response = HookResult(decision=Decision.DENY, reason="dangerous").to_json(event_name)

        # The refusal MARKER differs by event and both spellings are correct:
        # PreToolUse says "deny" in permissionDecision, while PostToolUse, Stop
        # and SubagentStop say "block" in a top-level decision field. Asserting
        # only "deny" would fail on the events that are behaving correctly.
        serialised = str(response)
        assert Decision.DENY.value in serialised or "block" in serialised, (
            f"a DENY on {event_name} produced {response}, which carries no refusal — "
            "the guard turned a block into a permit"
        )

    @pytest.mark.parametrize("event_name", _MESSAGE_ONLY)
    def test_an_inexpressible_refusal_is_loud_rather_than_silent(
        self, event_name: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """These events cannot block, so the failure must at least be visible.

        Silence is the one unacceptable outcome: the handler asked for something
        the event cannot do, and previously the request simply evaporated.
        """
        with caplog.at_level(logging.ERROR):
            response = HookResult(decision=Decision.DENY, reason="dangerous").to_json(event_name)

        assert not validate_response(event_name, response)
        assert caplog.records, (
            f"a DENY on {event_name} cannot be expressed and was dropped without "
            "any log record — exactly the silent downgrade this guards against"
        )

    @pytest.mark.parametrize("event_name", _MESSAGE_ONLY)
    def test_the_surviving_response_still_carries_the_reason(self, event_name: str) -> None:
        """The operator needs to see WHAT the handler tried to refuse."""
        response = HookResult(decision=Decision.DENY, reason="uniquereason123").to_json(event_name)

        assert "uniquereason123" in str(
            response
        ), f"the reason was discarded along with the decision on {event_name}"


class TestTheSubstituteIsValidForEveryEventAndDecision:
    """The fallback must never be the thing that breaks.

    ``_safe_substitute_response`` is only reached when the primary response is
    already invalid, and no ALLOW or CONTINUE currently produces one — so this
    is unreachable today. It is still worth holding, for two reasons.

    First, the fallback assumed ``systemMessage`` for anything that was not a
    refusal, and none of the five decision-capable events permits that key. The
    ``remaining`` check would then have raised ``RuntimeError`` from inside
    ``to_json`` — a guard whose failure mode is crashing the serialiser is worse
    than the bug it guards against.

    Second, the message it produced was simply untrue: "a handler returned
    'allow' for PreToolUse, which cannot express it". PreToolUse expresses allow
    perfectly well.

    Unreachable-today is exactly the condition under which this rots unnoticed,
    which is why the property is asserted over the full cross-product rather
    than over the paths that currently fire.
    """

    @pytest.mark.parametrize("event_name", _DECISION_CAPABLE + _MESSAGE_ONLY)
    @pytest.mark.parametrize("decision", list(Decision))
    def test_the_substitute_satisfies_the_schema(self, event_name: str, decision: Decision) -> None:
        result = HookResult(decision=decision, reason="why")
        substitute = result._safe_substitute_response(event_name)

        errors = validate_response(event_name, substitute)
        assert not errors, (
            f"the substitute for {decision.value} on {event_name} is itself invalid "
            f"({substitute} -> {errors}), so to_json would raise instead of recovering"
        )

    @pytest.mark.parametrize("event_name", _DECISION_CAPABLE)
    def test_a_non_refusal_substitute_does_not_claim_the_event_cannot_express_it(
        self, event_name: str
    ) -> None:
        """These events express allow fine; the message must not say otherwise."""
        substitute = HookResult(decision=Decision.ALLOW)._safe_substitute_response(event_name)

        assert "cannot express" not in str(substitute), (
            f"the substitute for an ALLOW on {event_name} claims the event cannot "
            "express it, which is false and would mislead whoever reads the log"
        )


class TestOrdinaryResponsesAreUntouched:
    """Enforcement must be invisible for the overwhelmingly common cases."""

    @pytest.mark.parametrize("event_name", _DECISION_CAPABLE + _MESSAGE_ONLY)
    def test_a_silent_allow_is_still_an_empty_dict(self, event_name: str) -> None:
        assert HookResult(decision=Decision.ALLOW).to_json(event_name) == {}

    def test_an_advisory_context_is_unchanged(self) -> None:
        response = HookResult(decision=Decision.ALLOW, context=["note"]).to_json("SessionStart")

        assert response == {
            "systemMessage": "note",
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "note",
            },
        }

    def test_a_pre_tool_use_deny_keeps_its_shape(self) -> None:
        response = HookResult(decision=Decision.DENY, reason="nope").to_json("PreToolUse")

        output = response["hookSpecificOutput"]
        assert output["permissionDecision"] == "deny"
        assert output["hookEventName"] == "PreToolUse"
        assert "nope" in output["permissionDecisionReason"]
