"""Wired events that SHIP a handler must have a real response contract.

``_permissive_response_schema`` is a deliberate fail-open for newly-wired events,
and its docstring states the premise that earns it: such events "ship no built-in
handler", so the daemon "only ever emits a passthrough response". Constraining a
contract nobody exercises would be guesswork, so accepting anything is right.

That premise is false for exactly two events. ``WorktreeCreate`` and
``WorktreeRemove`` both ship handlers, and ``HookResult.to_json`` has a bespoke
branch emitting ``{"worktreePath": ...}`` for the first. So of the twenty events
holding the permissive schema, the two that actually emit a response are the two
with nothing describing it.

The cost is not cosmetic, because ``_format_system_message_response`` contains a
deliberate tripwire: for an event that cannot express DENY/ASK it returns
``{"decision": ...}`` specifically so schema validation FAILS, its own comment
saying "This will fail schema validation as expected". A permissive schema
accepts that response, so for these two events the tripwire is disarmed — the
identical payload that raises an error on SessionStart raises none here.

Measured before this file existed, via ``validate_response`` on
``HookResult(decision=DENY).to_json(event)``:

    SessionStart    -> {'decision': 'deny', ...}  1 error
    PreCompact      -> {'decision': 'deny', ...}  1 error
    WorktreeCreate  -> {'decision': 'deny', ...}  0 errors
    WorktreeRemove  -> {'decision': 'deny', ...}  0 errors
"""

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import (
    RESPONSE_SCHEMAS,
    validate_response,
)

_WORKTREE_EVENTS = ("WorktreeCreate", "WorktreeRemove")
_WORKTREE_PATH = "/workspace/.claude/worktrees/refactor-auth-4f2a1c9b"


class TestWorktreeEventsHaveARealContract:
    """The two permissive events that actually emit responses."""

    @pytest.mark.parametrize("event_name", _WORKTREE_EVENTS)
    def test_schema_is_not_the_permissive_fallback(self, event_name: str) -> None:
        """A handler-shipping event must not hold the fail-open schema."""
        schema = RESPONSE_SCHEMAS[event_name]

        assert schema.get("additionalProperties") is not True, (
            f"{event_name} ships a built-in handler and emits a real response, but "
            "holds the permissive fail-open schema, which accepts anything"
        )

    @pytest.mark.parametrize("event_name", _WORKTREE_EVENTS)
    def test_the_schema_rejects_the_deliberate_invalid_payload(self, event_name: str) -> None:
        """The SCHEMA must reject ``{"decision": ...}`` for these events.

        Asserted against the raw payload rather than against ``to_json`` output,
        because ``to_json`` now enforces the contract and substitutes a valid
        response. The property that must hold forever is that the schema would
        catch it — that is what makes the enforcement layer able to act. Testing
        it through ``to_json`` would only re-test the enforcement.
        """
        assert validate_response(event_name, {"decision": "deny", "reason": "nope"}), (
            f"{event_name}'s schema accepts a decision field it cannot express, "
            "so the enforcement layer has nothing to detect"
        )

    @pytest.mark.parametrize("event_name", _WORKTREE_EVENTS)
    def test_an_inexpressible_deny_is_surfaced_not_dropped(self, event_name: str) -> None:
        """The end-to-end outcome: loud and valid, never silent."""
        response = HookResult(decision=Decision.DENY, reason="uniquereason456").to_json(event_name)

        assert not validate_response(event_name, response)
        assert "uniquereason456" in str(
            response
        ), f"the refusal reason was discarded on {event_name} instead of surfaced"

    @pytest.mark.parametrize("event_name", _WORKTREE_EVENTS)
    def test_a_silent_allow_is_still_valid(self, event_name: str) -> None:
        """Tightening must not break the overwhelmingly common response."""
        response = HookResult(decision=Decision.ALLOW).to_json(event_name)

        assert response == {}
        assert not validate_response(event_name, response)

    @pytest.mark.parametrize("event_name", _WORKTREE_EVENTS)
    def test_an_advisory_system_message_is_valid(self, event_name: str) -> None:
        """Both events fall through to the systemMessage-only formatter."""
        response = HookResult(decision=Decision.ALLOW, context=["heads up"]).to_json(event_name)

        assert "systemMessage" in response
        assert not validate_response(event_name, response)

    def test_the_created_worktree_path_is_valid(self) -> None:
        """WorktreeCreate's bespoke branch must satisfy its own schema.

        Claude Code parses this hook's stdout as a raw path, so this key is the
        entire point of the event — a schema that rejected it would be worse
        than no schema at all.
        """
        response = HookResult(worktree_path=_WORKTREE_PATH).to_json("WorktreeCreate")

        assert response == {"worktreePath": _WORKTREE_PATH}
        assert not validate_response("WorktreeCreate", response)

    def test_worktree_remove_does_not_accept_a_path(self) -> None:
        """Only WorktreeCreate returns a path; the schemas must differ.

        Without this the two could share one loose schema and still pass every
        test above, losing the distinction that WorktreeRemove has no path to
        report.
        """
        assert validate_response(
            "WorktreeRemove", {"worktreePath": _WORKTREE_PATH}
        ), "WorktreeRemove accepted a worktreePath it never emits"
