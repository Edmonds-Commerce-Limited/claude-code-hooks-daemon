"""Plan 00271 Task 2.6 — PermissionRequest deny reason goes to decision.message.

The docs define ``decision.message`` as "For deny only: tells Claude why the
permission was denied". The daemon used to route the reason into
``hookSpecificOutput.additionalContext``, a field the docs do not define for
this event at all — so the fix for the "refusal arrived bare" bug likely
delivered nothing (audit item 4). ``updatedPermissions`` and ``interrupt``
become schema-expressible too.
"""

from __future__ import annotations

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import validate_response

_EVENT = "PermissionRequest"


class TestDenyMessage:
    def test_deny_reason_lands_in_decision_message(self) -> None:
        payload = HookResult(decision=Decision.DENY, reason="reads only").to_json(_EVENT)
        decision = payload["hookSpecificOutput"]["decision"]
        assert decision["behavior"] == "deny"
        assert decision["message"] == "reads only"
        assert validate_response(_EVENT, payload) == []

    def test_deny_context_joins_the_message(self) -> None:
        payload = HookResult(decision=Decision.DENY, reason="no", context=["ask a human"]).to_json(
            _EVENT
        )
        message = payload["hookSpecificOutput"]["decision"]["message"]
        assert "no" in message
        assert "ask a human" in message

    def test_allow_carries_no_message(self) -> None:
        payload = HookResult(decision=Decision.ALLOW, context=["fyi"]).to_json(_EVENT)
        assert "message" not in payload["hookSpecificOutput"]["decision"]
        assert validate_response(_EVENT, payload) == []


class TestSchemaExpressesDocumentedDenyFields:
    def test_updated_permissions_validates(self) -> None:
        response = {
            "hookSpecificOutput": {
                "hookEventName": _EVENT,
                "decision": {
                    "behavior": "allow",
                    "updatedPermissions": [
                        {
                            "type": "addRules",
                            "rules": [{"toolName": "Read"}],
                            "behavior": "allow",
                            "destination": "session",
                        }
                    ],
                },
            }
        }
        assert validate_response(_EVENT, response) == []

    def test_interrupt_validates(self) -> None:
        response = {
            "hookSpecificOutput": {
                "hookEventName": _EVENT,
                "decision": {"behavior": "deny", "message": "stop", "interrupt": True},
            }
        }
        assert validate_response(_EVENT, response) == []
