"""AutonomyNoticeHandler - say plainly when autonomy is off (Plan 00498 Task 2.3).

The handlers that DRIVE work (declared crons, the failsafe-recovery advice, goal
injection, recovery and stand-in crons, the goal-ledger stop challenge) are not
consulted where the project's ``autonomy:`` config turns autonomy off for the
session's environment. Silence alone would be ambiguous: a session cannot tell a
deliberate quiet from a broken advisory. So on SessionStart this states, once,
that autonomy is off, in which environment, and what to change.

It is a notice, not a driver: it asks for nothing, so it is never gated itself,
and it is silent wherever autonomy is on (the default for every project that has
no ``autonomy:`` block).
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.utils.autonomy import autonomy_verdict


class AutonomyNoticeHandler(SessionStartHandlerBase):
    """State at session start that autonomy is off here, and why."""

    def __init__(self) -> None:
        """Initialise as a non-terminal advisory."""
        super().__init__(
            handler_id=HandlerID.AUTONOMY_NOTICE,
            priority=Priority.AUTONOMY_NOTICE,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.ENVIRONMENT,
                HandlerTag.WORKFLOW,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire only where the project's ``autonomy:`` config turns autonomy off here."""
        return not autonomy_verdict(hook_input).allowed

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """One line: autonomy is off, in which environment, and how to change it."""
        return AdvisoryResult(
            decision=Decision.ALLOW, context=[autonomy_verdict(hook_input).explain()]
        )

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## autonomy_notice — autonomy is off in this environment\n\n"
            "When the project's `autonomy:` config does not list this session's "
            "environment (`host`, `docker`, `podman`, `lxc`, `generic`) or role alias, "
            "no cron is asked for, no failsafe-recovery or goal advice is given, no "
            "stop is challenged on behalf of other plans and no stand-in cron is "
            "required. SessionStart says so once. Do only what you were asked in this "
            "conversation and stop when it is done; the plain `STOPPING BECAUSE:` "
            "explanation still applies, and every guard still runs."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: the notice is silent where autonomy is on."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="autonomy notice - says autonomy is off at session start",
                command='echo "test"',
                description=(
                    "With an `autonomy:` block that omits this session's environment, "
                    "session start carries one AUTONOMY OFF line naming the environment "
                    "and the config to change. Silent where autonomy is on."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"AUTONOMY OFF|autonomy"],
                safety_notes="Advisory only; asks for nothing and never blocks.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event",
                requires_main_thread=False,
            ),
        ]
