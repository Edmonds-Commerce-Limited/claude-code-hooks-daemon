"""UsagePauseToolGateHandler - a usage-paused session uses only the cron tools.

Plan 00479 Task 4.2. A session paused on its host usage ceiling has one job
left: replace its crons with the resume cron. So while the pause record is live
(``utils.usage_pause``) the only tools allowed are ``CronList``, ``CronDelete``
and ``CronCreate``; every other call is denied.

The deny also HALTS the turn (``continue: false`` plus a ``stopReason``,
``GatingResult.deny_and_halt``). A plain deny only refuses one call and the
model would try another; a turn that was already running when the ceiling was
reached stops at its next tool call instead of continuing to spend usage.

Terminal, first on the event: its deny is the final word on the call, and it
must not be pre-empted by a later handler's own (non-halting) deny.

Reads the same single predicate every usage-pause gate does
(``utils.usage_pause_gate.hook_is_usage_paused``) and fails open: no project
context, no record, another session -- nothing is paused.
"""

from __future__ import annotations

from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    PAUSE_ALLOWED_TOOLS,
    hook_is_usage_paused,
    tool_allowed_while_paused,
)

_ALLOWED_TEXT: Final[str] = ", ".join(sorted(PAUSE_ALLOWED_TOOLS))

_STOP_REASON: Final[str] = (
    "Session paused on its usage ceiling: only the cron tools are allowed until the "
    "resume cron fires."
)

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.USAGE_PAUSE_TOOL,
    blocked=f"any tool except {_ALLOWED_TEXT} while the session is paused on its usage ceiling",
    why="The session stopped taking on work to keep the account under its usage ceiling",
    fix="Replace the session's crons with the one resume cron, then stop; the session resumes at the window reset",
    verbose=(
        "WHY BLOCKED:\n"
        "This session is PAUSED (Plan 00479): a usage window reached the ceiling\n"
        "configured for this host. Until it resumes, the only tools allowed are\n"
        f"{_ALLOWED_TEXT}. The turn is halted so it cannot keep spending usage.\n\n"
        "DO INSTEAD:\n"
        "  1. CronList, then CronDelete every cron listed.\n"
        "  2. CronCreate ONE one-shot resume cron, exactly as the pause directive\n"
        "     gave it (its prompt starts [tick:usage-resume]).\n"
        "  3. Stop. The session resumes by itself at the window reset."
    ),
)


class UsagePauseToolGateHandler(PreToolUseHandlerBase):
    """Deny and halt every tool but the three cron tools while the session is paused."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.USAGE_PAUSE_TOOL_GATE,
            priority=Priority.USAGE_PAUSE_TOOL_GATE,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.WORKFLOW],
        )

    def get_default_enabled(self) -> bool:
        """On by default; inert unless a usage pause is recorded for the session."""
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A tool outside the allowed set, in a session whose pause record is live."""
        if tool_allowed_while_paused(hook_input.get(HookInputField.TOOL_NAME)):
            return False
        return hook_is_usage_paused(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny the call and halt the turn."""
        return GatingResult.deny_and_halt(RuleFormatter().verbose(_RULE), stop_reason=_STOP_REASON)

    def get_rules(self) -> list[Rule]:
        """The single Rule backing this handler's deny."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## usage_pause_tool_gate — a usage-paused session uses only the cron tools\n\n"
            "While a session is paused on its host usage ceiling (see `usage_pause_gate`) "
            "every tool except `CronList`, `CronDelete` and `CronCreate` is denied, and "
            "the deny halts the turn (`continue: false`). Replace the session's crons "
            "with the one resume cron the pause directive describes, then stop. The "
            "session resumes by itself at the window reset."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One case, declared as harness-undrivable.

        The deny needs a live pause record for the probe's session, and a probe
        cannot write one without changing the very state it is meant to observe;
        without it the gate (correctly) allows. The behaviour is covered by unit
        tests, and by the Plan 00479 Task 4.8 live probe with a synthetic
        snapshot above the ceiling.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="usage pause tool gate - a non-cron tool is denied while paused",
                command="Bash a command while the session is usage-paused",
                description=(
                    "With a live usage pause for the session, a Bash call is denied and "
                    "the turn halted; CronList, CronDelete and CronCreate are allowed."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"paused", r"CronCreate"],
                safety_notes="Denies only while a usage pause record is live for the session.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The deny needs a live usage-pause record for the probe's session, and "
                    "a probe cannot create one without altering the state it observes; with "
                    "none, the gate allows by design. Verified by unit tests and the Plan "
                    "00479 Task 4.8 live probe."
                ),
            ),
            AcceptanceTest(
                title="usage pause tool gate - an ordinary tool call in an unpaused session",
                command="echo 'a session with no usage pause'",
                description=(
                    "Near-miss: with no usage pause recorded for the session (the default, "
                    "and every host without a usage ceiling) no tool is touched."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: the gate must be inert unless a pause is recorded.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                dispatch_as_bash=True,
            ),
        ]
