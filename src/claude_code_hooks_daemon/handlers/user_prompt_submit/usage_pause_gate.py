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

**Hold.** While the record is live every further prompt -- cron tick,
supervisor message, human -- is blocked before it reaches the model, at zero
token cost. Two other gates keep the turn itself quiet: the PreToolUse gate
refuses every tool but the three cron tools, and the Stop gate accepts a stop
only once exactly the resume cron remains. The one exception here is the resume
cron's own tick.

**Exit (Task 4.6).** The resume tick re-reads usage. A window past its
``resets_at`` is absent from the snapshot, so a reading from before the reset
cannot keep the session paused. Below the ceiling the record is cleared and the
model is told to re-establish its declared crons and continue; still over (the
weekly window, say) the record is refreshed and the model is told to schedule
the next resume cron and stop again.

**Fail open (Task 4.7).** No ceiling for the host, an unknown hostname, no
snapshot, a snapshot with no windows, no project context, a record that cannot
be written: none of them pauses a session, and a debug line says which.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import tzinfo
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.data_layer import latest_usage
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT,
    declares_failsafe_cron,
)
from claude_code_hooks_daemon.utils.config_cache import load_config_cached
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.usage_pause import (
    UsagePause,
    clear_usage_pause,
    write_usage_pause,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    UsageBreach,
    active_usage_pause,
    build_pause,
    find_breaches,
    is_resume_tick,
    render_pause_directive,
    render_resume_lifted_directive,
    render_still_over_directive,
    resume_schedule,
    session_ceiling,
    untracked_dir,
)

logger = logging.getLogger(__name__)

_UNKNOWN_SESSION: Final[str] = "unknown"
_RECOVERY_ADVISOR_EVENT: Final[str] = "post_tool_use"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.USAGE_PAUSE_PROMPT,
    blocked="A prompt, cron tick or supervisor message while the session is paused on its usage ceiling",
    why="The session stopped taking on work to keep the account under its usage ceiling, and each prompt would cost a full model turn",
    fix="Nothing to do -- the session resumes by itself at the window reset, through its one resume cron",
    verbose=(
        "This session is PAUSED (Plan 00479): a usage window reached the ceiling\n"
        "configured for this host. The prompt was dropped before reaching the model,\n"
        "so it cost no turn. The session's crons were replaced by ONE resume cron,\n"
        "which fires after the window resets, re-reads usage, and either resumes the\n"
        "work or pauses again.\n\n"
        "Nothing needs doing. To lift the ceiling for this host, edit `hosts:` in\n"
        ".claude/hooks-daemon.yaml and restart the daemon."
    ),
)


class UsagePauseGateHandler(UserPromptSubmitHandlerBase):
    """Record and enforce the usage pause on UserPromptSubmit."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.USAGE_PAUSE_GATE,
            priority=Priority.USAGE_PAUSE_GATE,
            # Non-terminal: on every prompt it ALLOWS (almost always) the other
            # UserPromptSubmit advisories must still run. A DENY survives later
            # handlers regardless (core/router.py).
            terminal=False,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.WORKFLOW,
                HandlerTag.BLOCKING,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Injectable seams (tests substitute fakes). None are config options.
        self._clock: Callable[[], float] = time.time
        self._config_loader: Callable[[], Config] = self._default_config_loader
        self._usage_loader: Callable[[float], UsageSnapshot | None] = self._default_usage_loader
        self._tz: tzinfo | None = None  # None: the machine's local zone, which CronCreate reads

    def get_default_enabled(self) -> bool:
        """On by default; inert for a host with no usage ceiling."""
        return True

    @staticmethod
    def _default_usage_loader(now: float) -> UsageSnapshot | None:
        return latest_usage(now=now)

    @staticmethod
    def _default_config_loader() -> Config:
        """The project's daemon config; defaults (no ceiling) when it cannot be loaded."""
        try:
            return load_config_cached(
                ProjectContext.project_root() / ".claude" / "hooks-daemon.yaml"
            )
        except (RuntimeError, ValidationError, OSError, ValueError) as exc:
            logger.debug("usage_pause_gate: cannot load config, so no ceiling: %s", exc)
            return Config()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every prompt: the ceiling check is cheap and each skip logs its reason."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Hold, resume or enter the pause for this prompt."""
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or _UNKNOWN_SESSION)
        now = self._clock()
        if is_resume_tick(hook_input):
            return self._resume(hook_input, session_id, now)
        held = active_usage_pause(session_id, now=now)
        if held is not None:
            return self._hold(held)
        return self._maybe_enter(hook_input, session_id, now)

    def _breaches(self, hook_input: dict[str, Any], now: float) -> list[UsageBreach]:
        """The windows over this host's ceiling, logging why when there are none."""
        hostname = effective_hostname(hook_input)
        ceiling = session_ceiling(self._config_loader(), hook_input)
        if ceiling.five_hour is None and ceiling.seven_day is None:
            logger.debug("usage_pause_gate: no usage ceiling for host %r, not pausing", hostname)
            return []
        snapshot = self._usage_loader(now)
        if snapshot is None:
            logger.debug("usage_pause_gate: no usage snapshot (no rate_limits seen), not pausing")
            return []
        breaches = find_breaches(snapshot, ceiling)
        if not breaches:
            logger.debug("usage_pause_gate: usage below the ceiling for host %r", hostname)
        return breaches

    def _hold(self, pause: UsagePause) -> BlockingResult:
        schedule = resume_schedule(pause.resume_at, tz=self._tz)
        reason = (
            f"{RuleFormatter().verbose(_RULE)}\n\n"
            f"Paused on: {pause.reason}. Resumes about {schedule.hhmm} "
            f"({schedule.local_text})."
        )
        logger.info("usage_pause_gate: dropping a prompt while paused until %s", schedule.hhmm)
        return BlockingResult(decision=Decision.DENY, reason=reason)

    def _maybe_enter(
        self, hook_input: dict[str, Any], session_id: str, now: float
    ) -> BlockingResult:
        breaches = self._breaches(hook_input, now)
        if not breaches:
            return BlockingResult(decision=Decision.ALLOW)
        pause = self._record(session_id, breaches, now)
        if pause is None:
            return BlockingResult(decision=Decision.ALLOW)
        logger.warning("usage_pause_gate: pausing session %s: %s", session_id, pause.reason)
        return BlockingResult(
            decision=Decision.ALLOW, context=[render_pause_directive(pause, tz=self._tz)]
        )

    def _record(
        self, session_id: str, breaches: list[UsageBreach], now: float
    ) -> UsagePause | None:
        """Write the pause record; None (no pause) when it cannot be written."""
        directory = untracked_dir()
        if directory is None:
            return None
        pause = build_pause(session_id, breaches, now=now)
        try:
            write_usage_pause(directory, pause)
        except (OSError, ValueError) as exc:
            # The Stop and PreToolUse gates read this record, so a directive
            # without one could not be enforced. Not pausing is the safe side.
            logger.warning("usage_pause_gate: pause record not written, not pausing: %s", exc)
            return None
        return pause

    def _resume(self, hook_input: dict[str, Any], session_id: str, now: float) -> BlockingResult:
        """The resume cron fired: pause again if still over the ceiling, else lift."""
        breaches = self._breaches(hook_input, now)
        if breaches:
            pause = self._record(session_id, breaches, now)
            if pause is not None:
                logger.warning("usage_pause_gate: still over the ceiling: %s", pause.reason)
                return BlockingResult(
                    decision=Decision.ALLOW,
                    context=[render_still_over_directive(pause, tz=self._tz)],
                )
        self._lift(session_id)
        return BlockingResult(decision=Decision.ALLOW, context=[self._lifted_directive(hook_input)])

    def _lift(self, session_id: str) -> None:
        directory = untracked_dir()
        if directory is None:
            return
        try:
            clear_usage_pause(directory, session_id)
        except OSError as exc:
            # The record expires on its own at resume_at plus a grace.
            logger.warning("usage_pause_gate: could not clear the pause record: %s", exc)

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
            "then stop. **Do not act on that prompt's request.**\n\n"
            "While paused every other prompt is dropped before it reaches you "
            "(`R-USAGE-PAUSE-PROMPT`, no turn spent), every tool except `CronList`, "
            "`CronDelete` and `CronCreate` is denied and halts the turn "
            "(`usage_pause_tool_gate`), and a stop is accepted only once exactly the one "
            "resume cron remains (`usage_pause_stop_gate`).\n\n"
            "The resume cron's prompt starts `[tick:usage-resume]`; paste it verbatim. "
            "When it fires usage is re-read: below the ceiling you are told to "
            "re-establish the declared crons and continue; still over, to schedule the "
            "next resume cron and stop again.\n\n"
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
