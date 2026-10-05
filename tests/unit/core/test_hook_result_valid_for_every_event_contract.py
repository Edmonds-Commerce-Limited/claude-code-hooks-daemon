"""The daemon's own responses must validate against EVERY event's output contract.

Claude Code validates hook output strictly, so a `hookSpecificOutput` on an
event that defines none (SessionEnd, PreCompact, Notification, ...) invalidates
the whole document. The init.sh fail-open answers had that defect; this pins
that `HookResult.to_json` - the daemon's single serialisation choke point -
does not, for every event the contracts name and every decision a handler can
return. The contract is read from `contracts/claude-code-hooks/`, the one copy.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS
from tests.support.event_output_contract import contract_violations, load_event_contracts

#: Every WIRED event the contracts name. An unwired event has no dispatch and
#: no schema, so the daemon never answers it and there is nothing to validate.
_EVENTS = sorted(event for event in load_event_contracts() if event in RESPONSE_SCHEMAS)


class TestToJsonValidatesAgainstTheContractForEveryEvent:
    @pytest.mark.parametrize("event", _EVENTS)
    @pytest.mark.parametrize("decision", [Decision.ALLOW, Decision.DENY, Decision.ASK])
    def test_advisory_and_refusal_responses_are_contract_valid(
        self, event: str, decision: Decision
    ) -> None:
        result = HookResult(decision=decision, reason="because", context=["some advice"])

        response = result.to_json(event)

        assert contract_violations(event, response) == [], response

    @pytest.mark.parametrize("event", _EVENTS)
    def test_a_silent_allow_is_contract_valid(self, event: str) -> None:
        assert contract_violations(event, HookResult.allow().to_json(event)) == []

    @pytest.mark.parametrize("event", _EVENTS)
    def test_the_advisory_text_reaches_the_wire(self, event: str) -> None:
        """Valid is not enough: an advisory dropped to `{}` would also validate."""
        response = HookResult.allow(context=["some advice"]).to_json(event)

        assert "some advice" in str(response), response
