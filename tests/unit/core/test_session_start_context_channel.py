"""Plan 00271 Task 2.7 — SessionStart context reaches the documented channel.

The docs define ``hookSpecificOutput.additionalContext`` on SessionStart as
the field that puts text into CLAUDE's context before the first prompt, and
describe ``systemMessage`` as a USER-facing warning. The daemon's schema
hard-coded "does NOT accept hookSpecificOutput" (a claim that is no longer
true) and emitted advisory context as ``systemMessage`` only (audit item 6).

The serialiser now emits BOTH: ``additionalContext`` (the documented Claude
channel) and ``systemMessage`` (preserving the previous observable behaviour
for users). Live verification of what the installed Claude Code does with
each is recorded as deferred in the plan JOURNAL.
"""

from __future__ import annotations

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import validate_response

_EVENT = "SessionStart"


class TestContextChannels:
    def test_context_reaches_additional_context(self) -> None:
        payload = HookResult(decision=Decision.ALLOW, context=["branch: main"]).to_json(_EVENT)
        assert payload["hookSpecificOutput"]["additionalContext"] == "branch: main"
        assert validate_response(_EVENT, payload) == []

    def test_context_still_reaches_system_message(self) -> None:
        """Belt-and-braces: the previous channel is preserved until live-verified."""
        payload = HookResult(decision=Decision.ALLOW, context=["branch: main"]).to_json(_EVENT)
        assert payload["systemMessage"] == "branch: main"

    def test_silent_allow_stays_empty(self) -> None:
        assert HookResult(decision=Decision.ALLOW).to_json(_EVENT) == {}

    def test_guidance_joins_context(self) -> None:
        payload = HookResult(decision=Decision.ALLOW, context=["a"], guidance="do b").to_json(
            _EVENT
        )
        combined = payload["hookSpecificOutput"]["additionalContext"]
        assert "a" in combined and "do b" in combined


class TestDocumentedFieldsValidate:
    def test_session_title_and_friends_validate(self) -> None:
        response = {
            "hookSpecificOutput": {
                "hookEventName": _EVENT,
                "additionalContext": "ctx",
                "initialUserMessage": "start here",
                "sessionTitle": "my-session",
                "watchPaths": ["/tmp/x"],
                "reloadSkills": True,
            }
        }
        assert validate_response(_EVENT, response) == []

    def test_deny_is_still_impossible(self) -> None:
        """SessionStart has no decision control; a DENY substitutes loudly."""
        payload = HookResult(decision=Decision.DENY, reason="no").to_json(_EVENT)
        assert "decision" not in payload
        assert validate_response(_EVENT, payload) == []
