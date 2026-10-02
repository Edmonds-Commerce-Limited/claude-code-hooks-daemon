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

**The cron must work (Plan 00479 M2).** One resume-tagged cron is not enough: its
pinned schedule must fire in ``(now, resume_at + 1 day]``
(``schedule_fires_in_window``, read in UTC: the vendored Claude Code docs do not
say which zone ``CronCreate`` reads, so the day of tolerance absorbs the
difference). A pinned minute that has passed next matches a year later and would
never wake the session, so that is refused with the reason and the directive. A
resume time that has come or gone is first moved a margin ahead
(``renew_pause``) so the directive's expression is in the future; the pause is
NEVER cleared here, which would leave the session with no resume cron.

**Entry (M3).** A session that crosses the ceiling without a new prompt or tool
call can still reach a Stop, so this gate also enters the pause
(``try_start_pause``) and delivers the directive as the block. That first block
is delivered even on ``stop_hook_active``: the model has not seen it yet.

``matches`` reads the record once and hands it to ``handle`` (one read per Stop).
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
from claude_code_hooks_daemon.utils.usage_pause import UsagePause
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    PauseEnvironment,
    active_usage_pause,
    render_pause_directive,
    render_stop_directive,
    renew_pause,
    schedule_fires_in_window,
    try_start_pause,
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

        # The seams entry reads the world through; tests substitute fakes.
        self._env = PauseEnvironment()
        # What ``matches`` found, handed to ``handle`` so the record is read once per Stop.
        self._found: dict[str, tuple[UsagePause, bool]] = {}

    def get_default_enabled(self) -> bool:
        """On by default; inert unless a usage pause is recorded or the ceiling is reached."""
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A session whose usage pause record is live, or that has just crossed its ceiling.

        Reads the record once and remembers it for :meth:`handle`. Total: any
        failure reading the record or the ceiling is "not paused".
        """
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if not session_id:
            return False
        pause = active_usage_pause(session_id, now=self._env.clock())
        fresh = False
        if pause is None:
            pause = try_start_pause(hook_input, self._env)
            fresh = pause is not None
        if pause is None:
            return False
        self._found[session_id] = (pause, fresh)
        return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Verify ``session_crons`` against the one-resume-cron rule."""
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        found = self._found.pop(session_id, None)
        if found is None:
            return BlockingResult(decision=Decision.ALLOW)
        pause, fresh = found
        env = self._env
        if fresh:
            # Entered on this very Stop: the model has not seen the directive, so it is
            # delivered whatever ``stop_hook_active`` says; the next Stop reads a live record.
            return BlockingResult.deny(render_pause_directive(pause, tz=env.tz))
        crons = parse_session_crons(hook_input)
        if crons is None:
            return BlockingResult(decision=Decision.ALLOW)
        # A resume time that has come or gone (the model was slow) would pin the cron to a
        # minute that has passed: move it ahead and give the model the new expression. The
        # pause is never cleared here, which would leave the session with no resume cron.
        pause = renew_pause(pause, env)
        problem = self._problem(pause, crons)
        if problem is None:
            return BlockingResult(decision=Decision.ALLOW)
        if is_stop_hook_active(hook_input):
            logger.warning(
                "usage pause: session_crons still holds %d cron(s), not exactly a usable "
                "resume cron, on stop re-entry; allowing the stop so the session is not trapped",
                len(crons),
            )
            return BlockingResult(decision=Decision.ALLOW)
        return BlockingResult.deny(
            render_stop_directive(pause, found=len(crons), tz=env.tz, problem=problem or None)
        )

    def _problem(self, pause: UsagePause, crons: list[SessionCron]) -> str | None:
        """None when ``crons`` is exactly one usable resume cron; else why not ("" if obvious)."""
        if len(crons) != 1 or not _is_resume_cron(crons[0]):
            return ""
        env = self._env
        if schedule_fires_in_window(
            crons[0].schedule, now=env.clock(), resume_at=pause.resume_at, tz=env.tz
        ):
            return None
        return (
            f"Its schedule `{crons[0].schedule}` does not fire between now and a day after "
            "the resume time (a pinned minute that has passed next fires a YEAR later). "
            "CronDelete it and create it again with the expression given below, which is in UTC."
        )

    def get_rules(self) -> list[Rule]:
        """The single Rule backing this handler's deny."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## usage_pause_stop_gate — a paused session stops only on its resume cron\n\n"
            "While a session is paused on its host usage ceiling (`usage_pause_gate`), a "
            "stop is accepted only once `session_crons` holds exactly ONE cron: the "
            "usage-resume cron (prompt starting `[tick:usage-resume]`) whose pinned schedule "
            "really fires before a day after the resume time. Otherwise the "
            "block repeats the directive: `CronList`, `CronDelete` every cron, "
            "`CronCreate` the one resume cron, stop again (the cron tools are deferred; "
            "`ToolSearch` loads them). A session that reaches a Stop over its ceiling "
            "is paused here too. A stop that re-enters after "
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
