"""UsagePauseGateHandler - pause a session at its host usage ceiling (Plan 00479).

The entry, hold and exit of the usage pause, on ``UserPromptSubmit``:

**Entry (Task 4.1).** When a live usage window is at or above the ceiling the
session's host sets, the pause is recorded (``utils.usage_pause``, read by the
ccy supervisor and by every other gate) and the model is directed to replace
all of its crons with ONE one-shot resume cron at the window's reset, then
stop. ``decision: "block"`` reaches the USER only and is never added to the
model's context, so the directive travels as ``additionalContext`` on an
ALLOWED prompt: the one prompt that trips the ceiling is the only one that can
carry it. The directive tells the model not to act on that prompt's request.
The PreToolUse and Stop gates share the same entry (``try_start_pause``), so a
session that never receives a new prompt still pauses.

**Hold.** While the record is live every further prompt -- cron tick,
supervisor message, human -- is blocked before it reaches the model, at zero
token cost, after the ceiling is re-resolved: a host that no longer has a
ceiling, or whose windows are back under it or past their reset, lifts the pause
instead of holding, so a stale record can never lock the owner out. Two other
gates keep the turn itself quiet: the PreToolUse gate refuses every tool but the
cron tools, and the Stop gate accepts a stop only once exactly the resume cron
remains. The one exception here is the resume cron's own tick.

**Exit (Task 4.6).** The resume tick re-reads usage. A window past its
``resets_at`` is absent from the snapshot, so a reading from before the reset
cannot keep the session paused. Below the ceiling the record is cleared and the
model is told to re-establish its declared crons and continue; still over (the
weekly window, say) the record is refreshed and the model is told to schedule
the next resume cron and stop again. A record that cannot be cleared is never
reported as lifted.

**Fail open (Task 4.7).** No ceiling for the host, an unknown hostname, no
snapshot, a snapshot with no windows, no session id, no project context, a
record that cannot be written: none of them pauses a session, and a debug line
says which.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import tzinfo
from typing import Any, Final

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT,
    declares_failsafe_cron,
)
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.usage_pause import UsagePause
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    PauseEnvironment,
    active_usage_pause,
    clear_pause,
    current_breaches,
    default_usage_loader,
    is_resume_tick,
    load_project_config,
    render_lift_not_recorded_note,
    render_pause_directive,
    render_resume_lifted_directive,
    render_still_over_directive,
    resume_schedule,
    start_pause,
    try_start_pause,
)

logger = logging.getLogger(__name__)

_RECOVERY_ADVISOR_EVENT: Final[str] = "post_tool_use"

#: The command a human runs to lift a pause by hand (typed as `! <command>` in a session).
CLEAR_COMMAND: Final[str] = "bin/hooks-daemon usage-pause clear"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.USAGE_PAUSE_PROMPT,
    blocked="A prompt, cron tick or supervisor message while the session is paused on its usage ceiling",
    why="The session stopped taking on work to keep the account under its usage ceiling, and each prompt would cost a full model turn",
    fix=f"Nothing to do -- the session resumes by itself at the window reset; a human can lift it now with `! {CLEAR_COMMAND}`",
    verbose=(
        "This session is PAUSED (Plan 00479): a usage window reached the ceiling\n"
        "configured for this host. The prompt was dropped before reaching the model,\n"
        "so it cost no turn. The session's crons were replaced by ONE resume cron,\n"
        "which fires after the window resets, re-reads usage, and either resumes the\n"
        "work or pauses again.\n\n"
        "The ceiling is re-checked on every prompt, so the pause lifts by itself as\n"
        "soon as this host has no ceiling (edit `hosts:` in .claude/hooks-daemon.yaml;\n"
        "the daemon reads it on its next config load) or every window is back under\n"
        "it or past its reset. A human can lift it at once by typing, in the session:\n\n"
        f"    ! {CLEAR_COMMAND}\n\n"
        "(`usage-pause status` shows the record.) The record also expires on its own\n"
        "an hour after the resume time."
    ),
)


class UsagePauseGateHandler(UserPromptSubmitHandlerBase):
    """Record and enforce the usage pause on UserPromptSubmit."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.USAGE_PAUSE_GATE,
            priority=Priority.USAGE_PAUSE_GATE,
            # Terminal: a held prompt is a DENY and must reach no later handler
            # (they would act on a prompt the model never sees: the owner-reply
            # handlers clear their markers on it). An ALLOW never ends the chain
            # (core/chain.py, tests/integration/test_allow_never_ends_the_chain.py),
            # so the entry and lift directives, which ride on ALLOWs, are unaffected.
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.WORKFLOW, HandlerTag.BLOCKING],
        )
        # Injectable seams (tests substitute fakes). None are config options.
        self._clock: Callable[[], float] = time.time
        self._config_loader: Callable[[], Config] = load_project_config
        self._usage_loader: Callable[[float], UsageSnapshot | None] = default_usage_loader
        self._tz: tzinfo | None = None  # None: the machine's local zone, which CronCreate reads

    def get_default_enabled(self) -> bool:
        """On by default; inert for a host with no usage ceiling."""
        return True

    def _env(self) -> PauseEnvironment:
        return PauseEnvironment(self._clock, self._config_loader, self._usage_loader, self._tz)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every prompt: the ceiling check is cheap and each skip logs its reason."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Hold, resume or enter the pause for this prompt.

        A prompt with no session id never pauses and is never held: every other
        reader of the record fails open on an empty id.
        """
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if not session_id:
            logger.debug("usage_pause_gate: no session id on the prompt, not judging it")
            return BlockingResult(decision=Decision.ALLOW)
        env = self._env()
        if is_resume_tick(hook_input):
            return self._resume(hook_input, session_id, env)
        held = active_usage_pause(session_id, now=env.clock())
        if held is not None:
            return self._hold_or_lift(hook_input, session_id, held, env)
        pause = try_start_pause(hook_input, env)
        if pause is None:
            return BlockingResult(decision=Decision.ALLOW)
        return BlockingResult(
            decision=Decision.ALLOW, context=[render_pause_directive(pause, tz=env.tz)]
        )

    def _hold_or_lift(
        self, hook_input: dict[str, Any], session_id: str, held: UsagePause, env: PauseEnvironment
    ) -> BlockingResult:
        """Re-resolve the ceiling for a held prompt: lift if it no longer applies."""
        if not current_breaches(hook_input, env):
            logger.warning("usage_pause_gate: the ceiling no longer applies, lifting the pause")
            return self._lift(hook_input, session_id, held, env)
        schedule = resume_schedule(held.resume_at, tz=env.tz)
        reason = (
            f"{RuleFormatter().verbose(_RULE)}\n\n"
            f"Paused on: {held.reason}. Resumes about {schedule.hhmm} "
            f"({schedule.local_text})."
        )
        logger.info("usage_pause_gate: dropping a prompt while paused until %s", schedule.hhmm)
        return BlockingResult(decision=Decision.DENY, reason=reason)

    def _resume(
        self, hook_input: dict[str, Any], session_id: str, env: PauseEnvironment
    ) -> BlockingResult:
        """The resume cron fired: pause again if still over the ceiling, else lift."""
        breaches = current_breaches(hook_input, env)
        pause = start_pause(session_id, breaches, env)
        if pause is not None:
            logger.warning("usage_pause_gate: still over the ceiling: %s", pause.reason)
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[render_still_over_directive(pause, tz=env.tz)],
            )
        record = active_usage_pause(session_id, now=env.clock())
        return self._lift(hook_input, session_id, record, env)

    def _lift(
        self,
        hook_input: dict[str, Any],
        session_id: str,
        record: UsagePause | None,
        env: PauseEnvironment,
    ) -> BlockingResult:
        """Clear the record and tell the model; never claim a lift that was not recorded."""
        if not clear_pause(session_id):
            expires = record.expires_at if record is not None else env.clock()
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[render_lift_not_recorded_note(expires_at=expires, tz=env.tz)],
            )
        return BlockingResult(decision=Decision.ALLOW, context=[self._lifted_directive(hook_input)])

    def _lifted_directive(self, hook_input: dict[str, Any]) -> str:
        """The lift directive naming the crons this host declares."""
        config = self._config_loader()
        hostname = effective_hostname(hook_input)
        jobs = config.persistent_crons.active_jobs(hostname)
        recovery_on = config.get_handler_config(
            _RECOVERY_ADVISOR_EVENT, HandlerID.RECOVERY_CRON_ADVISOR.config_key
        ).enabled
        failsafe = (
            CANONICAL_CRON_PROMPT
            if recovery_on and not declares_failsafe_cron(config, hostname)
            else None
        )
        return render_resume_lifted_directive(jobs=jobs, failsafe_prompt=failsafe)

    def get_rules(self) -> list[Rule]:
        """The Rule backing the held-prompt block."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## usage_pause_gate — a session pauses at its host usage ceiling\n\n"
            "When `hosts:` gives this host a `usage_ceiling` and a live usage window "
            "reaches it, the session PAUSES (it does not end). The prompt that trips it "
            "carries a directive: `CronList`, `CronDelete` every cron, `CronCreate` ONE "
            "one-shot resume cron at the window reset (the exact expression is given), "
            "then stop. **Do not act on that prompt's request.** The cron tools are "
            "deferred: load them with `ToolSearch` if their schemas are not loaded.\n\n"
            "While paused every other prompt is dropped before it reaches you "
            "(`R-USAGE-PAUSE-PROMPT`, no turn spent), every tool except `CronList`, "
            "`CronDelete`, `CronCreate` and `ToolSearch` is denied and halts the turn "
            "(`usage_pause_tool_gate`), and a stop is accepted only once exactly the one "
            "resume cron remains, scheduled to fire in time (`usage_pause_stop_gate`).\n\n"
            "The resume cron's prompt starts `[tick:usage-resume]`; paste it verbatim. "
            "When it fires usage is re-read: below the ceiling you are told to "
            "re-establish the declared crons and continue; still over, to schedule the "
            "next resume cron and stop again.\n\n"
            "The ceiling is re-checked on every held prompt, so the pause lifts by itself "
            "when it no longer applies; a human can lift it at once with "
            f"`! {CLEAR_COMMAND}`. "
            "No ceiling, no usage data or an unknown host never pauses anything."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One safe-default case: with no ceiling configured a prompt is allowed through."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="usage pause gate - a prompt while the session is usage-paused is blocked",
                command='echo "a prompt while usage-paused"',
                description=(
                    "With a live usage pause for the session, every prompt except the resume "
                    "cron's own tick is blocked before it reaches the model."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"PAUSED"],
                safety_notes="Blocks only while a usage pause record is live for the session.",
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
                harness_cannot_produce=(
                    "The block needs a live usage-pause record for the probe's session, and a "
                    "probe cannot create one without altering the state it observes; with none "
                    "the gate allows by design. Verified by unit tests and the Plan 00479 "
                    "Task 4.8 live probe."
                ),
            ),
            AcceptanceTest(
                title="usage pause gate - no ceiling for the host allows the prompt",
                command='echo "test"',
                description=(
                    "With no `hosts:` usage ceiling for this host (the default), or no "
                    "usage data, a prompt is allowed through unchanged."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Asserts the SAFE default: missing data or configuration never pauses "
                    "a session."
                ),
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
