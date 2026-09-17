"""A subagent deletes no cron (Plan 00423 Task 3.2).

Issue #40's reported incident, verbatim: a finished subagent re-woke on
failsafe ticks and, on its last wake, deleted the project's single failsafe
recovery cron on its own initiative to stop the nudges. The coordinator's
session was then live with no recovery coverage, and nothing said so.

The rule the handler enforces is deliberately WIDER than "the failsafe cron",
and the reason is a limit rather than a preference: ``session_crons`` reaches
``Stop``, not ``PreToolUse``, so at the moment a ``CronDelete`` is judged the
daemon holds an opaque id and nothing that maps it to a schedule or a prompt.
A handler claiming to protect one named cron would in fact be guessing. "A
subagent deletes no cron" is the rule the payload can actually support, and it
costs nothing real: session crons belong to the coordinator's session, which is
the session that created them.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_cron_delete_blocker import (
    CRON_DELETE_TOOL,
    SubagentCronDeleteBlockerHandler,
)


def _event(tool_name: str, **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"cronId": "cron-abc123"},
        **extra,
    }


class TestTheScopeCarriesTheRoleTest:
    """The handler does NOT re-derive main-vs-sub; the chain gate does it.

    Keying on ``agent_id`` here as well would be a second copy of a rule that
    already has one home, and two copies of a safety rule drift. `scope=SUB`
    is the whole role test, and these assertions pin that it is declared.
    """

    def test_the_handler_is_scoped_to_sub(self) -> None:
        assert SubagentCronDeleteBlockerHandler().scope is HandlerScope.SUB

    def test_the_handler_does_not_read_agent_id_itself(self) -> None:
        handler = SubagentCronDeleteBlockerHandler()
        # No agent_id anywhere in the payload, and it still matches+denies:
        # admission is the chain's job, so reaching handle() at all already
        # means the event was a subagent's.
        assert handler.matches(_event(CRON_DELETE_TOOL)) is True
        assert handler.handle(_event(CRON_DELETE_TOOL)).decision is Decision.DENY


class TestWhatItMatches:
    def test_a_cron_delete_matches(self) -> None:
        assert SubagentCronDeleteBlockerHandler().matches(_event(CRON_DELETE_TOOL)) is True

    def test_cron_create_does_not_match(self) -> None:
        """Only DELETION is destructive. A subagent creating a cron is noisy,
        not harmful, and this handler is not the place to rule on it."""
        assert SubagentCronDeleteBlockerHandler().matches(_event("CronCreate")) is False

    def test_cron_list_does_not_match(self) -> None:
        assert SubagentCronDeleteBlockerHandler().matches(_event("CronList")) is False

    def test_an_unrelated_tool_does_not_match(self) -> None:
        assert SubagentCronDeleteBlockerHandler().matches(_event("Bash")) is False

    def test_a_missing_tool_name_does_not_match(self) -> None:
        assert SubagentCronDeleteBlockerHandler().matches({"hook_event_name": "PreToolUse"}) is False


class TestTheDenial:
    def test_it_denies(self) -> None:
        result = SubagentCronDeleteBlockerHandler().handle(_event(CRON_DELETE_TOOL))
        assert result.decision is Decision.DENY

    def test_the_reason_names_the_coordinator_as_the_route(self) -> None:
        """A deny that does not say what to do instead is a dead end.

        The subagent's legitimate move is to report the cron to its
        coordinator, so the reason has to name that, not merely refuse.
        """
        reason = SubagentCronDeleteBlockerHandler().handle(_event(CRON_DELETE_TOOL)).reason or ""
        assert "coordinator" in reason.lower()

    def test_the_reason_names_the_harm(self) -> None:
        reason = SubagentCronDeleteBlockerHandler().handle(_event(CRON_DELETE_TOOL)).reason or ""
        assert "recovery" in reason.lower()


class TestItIsOnByDefault:
    def test_enabled_by_default(self) -> None:
        """A safety control a project has to remember to switch on is one that
        is off in every project that has not had the incident yet."""
        assert SubagentCronDeleteBlockerHandler().get_default_enabled() is True


class TestTheAcceptanceTestsAreHonestAboutTheHarness:
    """The harness marks every probe synthetic, and a scoped handler declines a
    synthetic event by construction — so a probe asserting this DENY would
    assert an ALLOW forever. That has to be DECLARED, not left to be
    discovered by whoever reads a green run."""

    def test_every_acceptance_test_declares_why_the_harness_cannot_drive_it(self) -> None:
        tests = SubagentCronDeleteBlockerHandler().get_acceptance_tests()
        assert tests, "guard the guard: an empty list would pass the loop below"
        for test in tests:
            assert test.harness_cannot_produce, test.title

    def test_the_declared_reason_names_the_synthetic_marker(self) -> None:
        for test in SubagentCronDeleteBlockerHandler().get_acceptance_tests():
            assert "synthetic" in (test.harness_cannot_produce or "").lower()
