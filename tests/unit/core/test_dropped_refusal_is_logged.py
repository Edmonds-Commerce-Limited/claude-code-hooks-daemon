"""A refusal an event cannot carry must be logged, even when the response is valid.

Enforcement in ``to_json`` fires on an INVALID response. There is a corner where
the response is perfectly valid and the refusal still vanishes:

    Stop         ASK  -> {}
    PostToolUse  ASK  -> {}
    Status       DENY -> {"text": "Claude"}

``Stop`` and ``PostToolUse`` can express ``block`` but not ``ask``; ``Status``
renders a status line and can express nothing. So the decision is dropped, the
response validates, enforcement stays quiet, and the handler believes it
interrupted something. That is the same silent downgrade this module exists to
prevent, hiding in the one place the schema check cannot see it.

**Why this is worth catching despite being unreachable in this repository.**
``Decision.ASK`` appears in zero handler files here — built-in, project handlers
and plugins alike — so no shipped handler can trigger it. But
``tests/integration/test_every_handler_response_validates.py`` sweeps only
``claude_code_hooks_daemon.handlers``. A CLIENT project handler is a supported
extension point, lives outside this repository, and is never covered by that
sweep. For a client, this is not unreachable at all — it is simply undetectable.

**Why it logs rather than substitutes.** The emitted response is already the
best the event permits: ``Status`` genuinely cannot refuse, and injecting an
error into a status line would put noise on every prompt forever. What is
missing is not a different response, it is any record that the handler asked for
something impossible.
"""

import logging

import pytest

from claude_code_hooks_daemon.core.hook_result import (
    REFUSAL_CAPABLE_EVENTS,
    Decision,
    HookResult,
)
from claude_code_hooks_daemon.core.response_schemas import RESPONSE_SCHEMAS

#: (event, decision) pairs where the refusal is silently dropped today.
_DROPPED = [
    ("Stop", Decision.ASK),
    ("SubagentStop", Decision.ASK),
    ("PostToolUse", Decision.ASK),
    ("Status", Decision.DENY),
    ("Status", Decision.ASK),
]

#: (event, decision) pairs the wire format genuinely carries.
_CARRIED = [
    ("PreToolUse", Decision.DENY),
    ("PreToolUse", Decision.ASK),
    ("PostToolUse", Decision.DENY),
    ("Stop", Decision.DENY),
    ("PermissionRequest", Decision.DENY),
]


class TestADroppedRefusalIsLogged:
    """The record that was missing."""

    @pytest.mark.parametrize("event_name,decision", _DROPPED)
    def test_a_dropped_refusal_produces_a_log_record(
        self, event_name: str, decision: Decision, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR):
            HookResult(decision=decision, reason="I meant to interrupt").to_json(event_name)

        assert caplog.records, (
            f"a {decision.value} on {event_name} was dropped with no log record, so a "
            "handler asking for something impossible gets silence"
        )

    @pytest.mark.parametrize("event_name,decision", _DROPPED)
    def test_the_log_names_the_event_and_the_reason(
        self, event_name: str, decision: Decision, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A record nobody can act on is barely better than none."""
        with caplog.at_level(logging.ERROR):
            HookResult(decision=decision, reason="UNIQUEREASON789").to_json(event_name)

        combined = " ".join(record.getMessage() for record in caplog.records)
        assert event_name in combined
        assert "UNIQUEREASON789" in combined


class TestTheCommonPathStaysSilent:
    """Logging a dropped refusal must not make normal operation noisy."""

    @pytest.mark.parametrize("event_name,decision", _CARRIED)
    def test_a_carried_refusal_logs_nothing(
        self, event_name: str, decision: Decision, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR):
            HookResult(decision=decision, reason="blocked").to_json(event_name)

        assert not caplog.records, (
            f"a {decision.value} on {event_name} IS carried on the wire, so logging it "
            "as dropped would be a false alarm on a hot path"
        )

    @pytest.mark.parametrize("event_name", sorted(RESPONSE_SCHEMAS))
    def test_an_allow_never_logs(self, event_name: str, caplog: pytest.LogCaptureFixture) -> None:
        """The overwhelmingly common case, on every event."""
        with caplog.at_level(logging.ERROR):
            HookResult(decision=Decision.ALLOW).to_json(event_name)

        assert not caplog.records


class TestTheCapabilityTableMatchesTheSchemas:
    """Guard the guard — a hand-written table is exactly what goes stale.

    ``REFUSAL_CAPABLE_EVENTS`` decides whether a dropped refusal is reported.
    If it drifts from the schemas it either goes quiet on a real drop or cries
    wolf on a hot path, and nothing else would notice.
    """

    def test_every_listed_event_can_really_carry_that_decision(self) -> None:
        """Each claim in the table must be true of the emitted response."""
        wrong: list[str] = []
        for decision, events in REFUSAL_CAPABLE_EVENTS.items():
            for event_name in events:
                response = str(HookResult(decision=decision, reason="x").to_json(event_name))
                carried = (
                    decision.value in response
                    or "block" in response
                    # TeammateIdle/TaskCompleted block via continue: false.
                    or "'continue': False" in response
                )
                if not carried:
                    wrong.append(f"{decision.value} on {event_name}")

        assert not wrong, (
            f"the capability table claims these are carried on the wire, but the "
            f"response contains no refusal: {wrong}"
        )

    def test_the_table_names_only_real_events(self) -> None:
        """A typo would silently disable reporting for that event."""
        unknown = sorted(
            {
                event_name
                for events in REFUSAL_CAPABLE_EVENTS.values()
                for event_name in events
                if event_name not in RESPONSE_SCHEMAS
            }
        )

        assert not unknown, f"capability table names non-existent event(s): {unknown}"
