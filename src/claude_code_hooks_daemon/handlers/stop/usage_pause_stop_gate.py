"""UsagePauseStopGateHandler - a paused session stops only on the resume cron.

Plan 00479 Task 4.3. A hook cannot create or delete a cron, so the usage pause
(``usage_pause_gate``) DIRECTS the model to replace every cron with one one-shot
resume cron, and this handler VERIFIES it on ``Stop``: ``session_crons`` must
hold exactly ONE entry, the usage-resume cron (recognised by its
``[tick:usage-resume]`` sentinel). Anything else repeats the directive, the
pattern ``cron_stop_enforcer`` uses for declared crons.

**Ordering.** Priority 6 puts it ahead of ``cron_stop_enforcer`` (7) and
``auto_continue_stop``, and it is non-terminal for the reason those two are
(see ``cron_stop_enforcer``'s "Ordering note"): a Stop handler that matches
every stop and is terminal would shadow everything behind it. While paused,
every continuation-forcing Stop handler stands down on the same predicate this
handler matches on (``utils.usage_pause_gate.is_usage_paused``), so this is the
only voice on a paused stop.

**Never a trap.** A stop that re-enters after this deny (``stop_hook_active``) is
allowed and logged, like every other one-shot Stop block: a session that cannot
fix its crons must still be able to stop. The next fresh stop is checked again.
An ABSENT ``session_crons`` is "no information", never "no crons exist", and
allows.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.utils.cron_enforcement import SessionCron, parse_session_crons
from claude_code_hooks_daemon.utils.cron_tick import TickKind, classify_tick
from claude_code_hooks_daemon.utils.stop_hook_helpers import is_stop_hook_active
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    active_usage_pause,
    render_stop_directive,
)

logger = logging.getLogger(__name__)

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.USAGE_PAUSE_STOP,
    blocked="a stop while a usage-paused session's crons are not exactly the one resume cron",
    why="A paused session is woken only by its resume cron, so any other cron would drive it past the usage ceiling and a missing one would never wake it",
    fix="CronList, CronDelete every cron, CronCreate the one resume cron as the pause directive gave it, then stop again",
    verbose=(
        "The session is PAUSED on its usage ceiling (Plan 00479). It may stop once\n"
        "session_crons holds exactly ONE cron: the usage-resume cron. The directive\n"
        "in the block message lists the steps."
    ),
)


def _is_resume_cron(cron: SessionCron) -> bool:
    tick = classify_tick(cron.prompt)
    return tick is not None and tick.kind is TickKind.USAGE_RESUME


class UsagePauseStopGateHandler(StopHandlerBase):
    """Allow a paused session's stop only when its crons are exactly the resume cron."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.USAGE_PAUSE_STOP_GATE,
            priority=Priority.USAGE_PAUSE_STOP_GATE,
            terminal=False,
            # Session crons belong to the COORDINATOR's session (Plan 00423).
            scope=HandlerScope.MAIN,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.WORKFLOW,
                HandlerTag.BLOCKING,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def get_default_enabled(self) -> bool:
        """On by default; inert unless a usage pause is recorded for the session."""
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only a session whose usage pause record is live."""
        return active_usage_pause(str(hook_input.get(HookInputField.SESSION_ID) or "")) is not None

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Verify ``session_crons`` against the one-resume-cron rule."""
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        pause = active_usage_pause(session_id)
        if pause is None:
            return BlockingResult(decision=Decision.ALLOW)
        crons = parse_session_crons(hook_input)
        if crons is None:
            return BlockingResult(decision=Decision.ALLOW)
        if len(crons) == 1 and _is_resume_cron(crons[0]):
            return BlockingResult(decision=Decision.ALLOW)
        if is_stop_hook_active(hook_input):
            logger.warning(
                "usage pause: session_crons still holds %d cron(s), not exactly the resume "
                "cron, on stop re-entry; allowing the stop so the session is not trapped",
                len(crons),
            )
            return BlockingResult(decision=Decision.ALLOW)
        return BlockingResult.deny(render_stop_directive(pause, found=len(crons)))

    def get_rules(self) -> list[Rule]:
        """The single Rule backing this handler's deny."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## usage_pause_stop_gate — a paused session stops only on its resume cron\n\n"
            "While a session is paused on its host usage ceiling (`usage_pause_gate`), a "
            "stop is accepted only once `session_crons` holds exactly ONE cron: the "
            "usage-resume cron (prompt starting `[tick:usage-resume]`). Otherwise the "
            "block repeats the directive: `CronList`, `CronDelete` every cron, "
            "`CronCreate` the one resume cron, stop again. A stop that re-enters after "
            "the block is allowed, so the session is never trapped."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One case, declared as harness-undrivable (see ``usage_pause_tool_gate``)."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="usage pause stop gate - a paused session with no resume cron cannot stop",
                command="echo 'session_crons: [] while usage-paused'",
                description=(
                    "With a live usage pause and a session_crons list that is not exactly "
                    "the one resume cron, the Stop is blocked with the pause directive."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"CronCreate"],
                safety_notes="Blocks only while a usage pause record is live for the session.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=True,
                harness_cannot_produce=(
                    "The deny needs a live usage-pause record for the probe's session, and a "
                    "probe cannot create one without altering the state it observes; the Stop "
                    "scope gate also declines a synthetic event. Verified by unit tests and "
                    "the Plan 00479 Task 4.8 live probe."
                ),
            ),
            AcceptanceTest(
                title="usage pause stop gate - an ordinary stop in an unpaused session",
                command="echo 'ordinary stop'",
                description=(
                    "Near-miss: with no usage pause recorded for the session (the default) "
                    "an empty session_crons is not this handler's business."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: the gate must be inert unless a pause is recorded.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=False,
                hook_input={
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "session_crons": [],
                },
            ),
        ]
