"""FailsafeCronBlockageSuppressorHandler - zero-token cadence for a stably
human-input-blocked session (Plan 00298).

The failsafe recovery cron (``recovery_cron_advisor``) fires the canonical
cron prompt hourly while the REPL is idle, to recover from EXTERNAL
interruptions (API error, rate limit, 5-hour usage limit, network failure). A
session that is blocked ONLY on human input is not that state -- every tick
against it is a guaranteed no-op that still costs one full model turn (prompt
in, generation out, transcript write, stop-hook round trip) for nothing.

This handler is the ``UserPromptSubmit`` half of the design: it recognises a
DELIVERED canonical-cron-prompt tick and, when ``auto_continue_stop`` has
recorded a still-valid "blocked only on human input" marker for THIS session,
blocks the prompt before it ever reaches the model (Claude Code's documented
``UserPromptSubmit`` "block" behaviour -- the prompt is dropped, not
forwarded). That is genuinely zero-token, unlike a convention/prompt-text
backoff which still costs a turn to read and act on.

**Minimal by design (owner ruling, Plan 00298 BRAINSTORM.md: "sounds complex
and brittle to me").** One marker, one session-scoped validity check, no
fallback chains. See ``blockage_marker`` for the shared primitive and
``auto_continue_stop._HUMAN_BLOCKED_PATTERNS`` for the narrow write-side
pattern set.

**Plan 00337 Phase 4 adds the middle case.** Plan 00298 left only two
outcomes: a session that DECLARED it was blocked paid nothing, and every other
session paid a full model turn per hour forever. The strongest fix is the one
that needs no cooperation from the agent, so this handler now asks the
daemon-side goal ledger "is work owed?" rather than asking the agent "are you
stuck?" -- a false self-reported "done" is the commonest way an agent stops
wrongly, and the cron is the net that catches it.

The resulting truth table (full derivation in Plan 00337's
``DESIGN-cadence.md``):

===========  ==========  ===============================================
work owed    declared    outcome
===========  ==========  ===============================================
yes          no          ALLOW every tick; the case the cron exists for
yes          yes         back off, capped
no           yes         DENY -- Plan 00298's behaviour, unchanged
no           no          back off, capped
===========  ==========  ===============================================

"Could not determine whether work is owed" is a THIRD value, not a synonym for
"no". It reads as owed on the undeclared path, so a plan directory the daemon
cannot resolve costs a wasted tick instead of a silently withdrawn safety net.
On the declared path it reads as row 3, because the declaration alone
justified suppression before Phase 4 and this must not become less safe.

The backoff is capped (``cron_cadence.MAX_CADENCE_HOURS``) and so is never
silence: hourly, then every 2 hours, then every 4, and no sparser.

**Fails open everywhere**: no marker, wrong session, expired marker, corrupt
marker, or no resolvable project context all ALLOW the tick through
unchanged -- suppression is a positive assertion made only when every
condition is individually verified, never the default. A genuine external
interruption during the blocked window is still bounded by "however long the
owner takes to respond" (BRAINSTORM.md), and the expiry itself further bounds
an unresponsive owner's silence.

**Never terminal.** ``idle_housekeeping_advisory`` and
``standing_authorisations`` also key off the same canonical cron prompt and
must keep running on every NON-suppressed tick. A non-terminal DENY still
survives later handlers regardless of registration order
(``core/router.py``: "a non-terminal deny now survives later handlers"), so
staying non-terminal costs nothing on the suppressed path either.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT_MARKER,
)
from claude_code_hooks_daemon.utils.blockage_marker import (
    MARKER_FILENAME,
    clear_marker,
    marker_is_valid,
    read_marker,
)
from claude_code_hooks_daemon.utils.cron_cadence import (
    CADENCE_FILENAME,
    next_tick_decision,
    read_cadence,
    reset_cadence,
    write_cadence,
)
from claude_code_hooks_daemon.utils.goal_ledger import (
    LEDGER_FILENAME,
    GoalLedger,
    resolve_plan_dir,
)

logger = logging.getLogger(__name__)

_DEFAULT_EXPIRY_HOURS: Final[float] = 24.0
_SECONDS_PER_HOUR: Final[int] = 3600
_UNKNOWN_SESSION: Final[str] = "unknown"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.FAILSAFE_CRON_SUPPRESSED,
    blocked="A delivered failsafe-cron tick, while a 'blocked only on human input' marker is live",
    why="Every tick against a session blocked only on human input is a guaranteed no-op model turn",
    fix="Nothing to do -- this is expected. Send a real message to clear the marker and resume ticks",
    verbose=(
        "This session recorded a 'blocked only on human input' marker (Plan "
        "00298) still within its expiry window, so this failsafe-cron tick "
        "was dropped before reaching the model -- no turn spent. A real "
        "(non-cron) user prompt clears the marker immediately; the marker's "
        "own expiry restores full hourly cron coverage automatically if the "
        "owner stays silent for longer."
    ),
)

_BACKOFF_RULE: Final[Rule] = Rule(
    rule_id=RuleID.FAILSAFE_CRON_BACKED_OFF,
    blocked="A delivered failsafe-cron tick, while this session is producing nothing and owes no ledgered work",
    why="An hourly tick against a session with nothing to recover costs a full model turn and finds nothing",
    fix="Nothing to do -- ticks continue, just less often. Any real user message restores hourly cadence",
    verbose=(
        "This session has no still-live goal on the daemon-side ledger, so "
        "the failsafe cron has nothing to recover and this tick was dropped "
        "before reaching the model (Plan 00337 Phase 4). Unlike the "
        "declaration-driven suppression, this needs nothing from the agent "
        "and never stops ticks entirely: the cadence thins to every 2 hours, "
        "then every 4, and no sparser -- a session interrupted by a rate "
        "limit still recovers once the limit lifts. Any genuine (non-cron) "
        "user prompt resets it to hourly immediately."
    ),
)


class FailsafeCronBlockageSuppressorHandler(UserPromptSubmitHandlerBase):
    """Suppress a delivered failsafe-cron tick while the session is stably
    blocked only on human input (Plan 00298)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.FAILSAFE_CRON_BLOCKAGE_SUPPRESSOR,
            priority=Priority.FAILSAFE_CRON_BLOCKAGE_SUPPRESSOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.AUTOMATION,
                HandlerTag.NON_TERMINAL,
                HandlerTag.BLOCKING,
                # PLANNING is the ONLY route by which the registry injects
                # `track_plans_in_project` (registry.py, gated on
                # `plan_workflow is not None and "planning" in instance.tags`),
                # and Phase 4 needs the configured plan directory to ask the
                # goal ledger whether work is owed. Surveyed before adding: the
                # tag has exactly one behavioural read in src/ -- that gate --
                # and nothing else classifies, counts or documents by it.
                #
                # One consequence a project should know about: tags also feed
                # the generic `enable_tags`/`disable_tags` config filters, so a
                # project that disables the `planning` tag now disables this
                # handler too.
                HandlerTag.PLANNING,
            ],
        )
        # Config option (hours); overridden by the registry from handler
        # options via setattr.
        self._expiry_hours: float = _DEFAULT_EXPIRY_HOURS
        # Injectable wall clock (tests substitute a fake). Not a config option.
        self._clock: Callable[[], float] = time.time
        # Injected by the registry for planning-tagged handlers. Self-defaulted
        # because the injection block does not run at all when plan_workflow is
        # None -- so a missing tag reads as None rather than raising, which is
        # why the tag is asserted by a test instead of trusted.
        self._track_plans_in_project: str | None = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match a delivered canonical-cron-prompt tick, OR any real prompt
        while there is session state a genuine reply should clear.

        The cadence file is checked as well as the marker, and that is not
        belt-and-braces: in the row this backoff exists for ("nothing owed,
        nothing declared") there is by definition NO marker, so a marker-only
        test would refuse to match the owner's reply, ``handle()`` would never
        run, and the cadence would never reset. The symptom would be invisible
        -- ticks simply staying sparse after the owner came back.
        """
        prompt = hook_input.get(HookInputField.PROMPT)
        if not isinstance(prompt, str):
            return False
        if CANONICAL_CRON_PROMPT_MARKER in prompt:
            return True
        try:
            untracked_dir = ProjectContext.daemon_untracked_dir()
        except RuntimeError:
            return False
        return (untracked_dir / MARKER_FILENAME).exists() or (
            untracked_dir / CADENCE_FILENAME
        ).exists()

    def _work_is_owed(self) -> bool | None:
        """Whether the goal ledger still holds live work for this project.

        Three-valued on purpose. ``None`` means "could not determine", and the
        caller must treat that like "work is owed" rather than like "nothing
        owed" -- ``resolve_plan_dir`` falls back to the config model's DEFAULT
        directory when nothing was injected, so a project that configured a
        different one would otherwise scan the wrong tree, find nothing, and
        have its safety net withdrawn silently. Collapsing the two would make
        the most likely misconfiguration also the most dangerous one.

        NOT a pure read, despite the name: ``live_plan_numbers`` takes the
        ledger lock, reconciles every entry against the plan directory and
        persists any retirements it finds. That is idempotent and cheap at
        hourly cadence, but this handler is a genuine second writer of
        ``goal-ledger.json`` and a reader of this code should know it.

        Returns:
            True if at least one ledgered goal is still In Progress, False if
            none is, None if the question could not be answered.
        """
        try:
            untracked_dir = ProjectContext.daemon_untracked_dir()
            plan_dir = resolve_plan_dir(ProjectContext.project_root(), self._track_plans_in_project)
        except RuntimeError as e:
            logger.debug("failsafe_cron cadence: plan context unavailable: %s", e)
            return None
        if not plan_dir.is_dir():
            # Defence in depth against the fallback above: a directory that is
            # not there is far likelier to be a wrong guess than an empty plan
            # tree, and "unknown" is the safe reading of a wrong guess.
            logger.debug("failsafe_cron cadence: plan dir %s does not exist", plan_dir)
            return None
        try:
            return bool(GoalLedger(untracked_dir / LEDGER_FILENAME).live_plan_numbers(plan_dir))
        except OSError as e:
            logger.warning("failsafe_cron cadence: ledger consult failed: %s", e)
            return None

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Suppress a cron tick when a still-valid marker exists for this
        session; clear the marker on any genuine (non-cron) prompt.

        Args:
            hook_input: The UserPromptSubmit event's hook input.

        Returns:
            DENY (blocks/erases the prompt) only for a cron-prompt tick with
            a valid marker. ALLOW in every other case, including every
            failure mode -- a real prompt that fails to clear the marker
            (e.g. an unlink error) still gets through unchanged.
        """
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or _UNKNOWN_SESSION)
        try:
            untracked_dir = ProjectContext.daemon_untracked_dir()
        except RuntimeError as e:
            logger.debug("failsafe_cron_blockage_suppressor: no project context: %s", e)
            return BlockingResult(decision=Decision.ALLOW)
        marker_path = untracked_dir / MARKER_FILENAME
        cadence_path = untracked_dir / CADENCE_FILENAME

        prompt = hook_input.get(HookInputField.PROMPT)
        is_cron_prompt = isinstance(prompt, str) and CANONICAL_CRON_PROMPT_MARKER in prompt

        if not is_cron_prompt:
            # A genuine (non-cron) prompt means the owner is back -- clear any
            # stale marker now instead of waiting up to expiry_hours for it to
            # lapse on its own, and reset the cadence to hourly for the same
            # reason. Both are fail-open (they log and swallow OSError), so
            # this never blocks the prompt.
            clear_marker(marker_path)
            reset_cadence(cadence_path)
            return BlockingResult(decision=Decision.ALLOW)

        marker = read_marker(marker_path)
        now = self._clock()
        expiry_seconds = self._expiry_hours * _SECONDS_PER_HOUR
        declared = marker_is_valid(marker, session_id, now, expiry_seconds)

        try:
            owed = self._work_is_owed()
        except (RuntimeError, OSError) as e:
            # _work_is_owed handles its own known failures; this is the outer
            # guarantee that a NEW one cannot turn into a silently withdrawn
            # safety net.
            logger.warning("failsafe_cron cadence: owed-work consult raised: %s", e)
            owed = None

        if not declared:
            # Rows 1 and 4. With work owed -- or unresolvable, which must read
            # as owed -- this is the case the cron exists for and must never be
            # thinned. Only a confident "nothing owed" earns a backoff.
            if owed is not False:
                reset_cadence(cadence_path)
                return BlockingResult(decision=Decision.ALLOW)
            return self._apply_backoff(cadence_path, session_id)

        if owed is True:
            # Row 2: the agent says it is blocked, but the ledger still holds
            # live work. Suppressing outright would be unsafe and hourly would
            # be wasteful, so thin out instead of choosing either extreme.
            return self._apply_backoff(cadence_path, session_id)

        # Row 3: declared, and nothing owed -- Plan 00298's behaviour, kept
        # bit-for-bit. `owed is None` lands here too, deliberately: the
        # declaration alone justified suppression before Phase 4, and the
        # ledger's blind spot must not make this path LESS safe than it was.
        reset_cadence(cadence_path)
        logger.info(
            "failsafe_cron_blockage_suppressor: suppressing cron tick for session %s",
            session_id,
        )
        return BlockingResult(decision=Decision.DENY, reason=RuleFormatter().verbose(_RULE))

    def _apply_backoff(self, cadence_path: Path, session_id: str) -> BlockingResult:
        """Advance the cadence and drop or deliver this tick accordingly.

        Args:
            cadence_path: Full path to the cadence state file.
            session_id: The current session.

        Returns:
            DENY when the cadence says this tick is between deliveries, ALLOW
            otherwise. Never DENYs indefinitely -- the cadence is capped.
        """
        deliver, next_state = next_tick_decision(read_cadence(cadence_path), session_id=session_id)
        write_cadence(cadence_path, next_state)
        if deliver:
            return BlockingResult(decision=Decision.ALLOW)
        logger.info(
            "failsafe_cron_blockage_suppressor: backing off cron tick for session %s (every %sh)",
            session_id,
            next_state.cadence_hours,
        )
        return BlockingResult(decision=Decision.DENY, reason=RuleFormatter().verbose(_BACKOFF_RULE))

    def get_rules(self) -> list[Rule]:
        """Return both Rules backing this handler's DENY paths.

        Two, not one, because the situations differ in what the agent can do
        about them: suppression needs a declaration and stops ticks entirely
        until a real prompt; the backoff needs nothing and never stops them.
        """
        return [_RULE, _BACKOFF_RULE]

    def get_claude_md(self) -> str | None:
        """Document the suppression contract."""
        return (
            "## failsafe_cron_blockage_suppressor — zero-token cadence for "
            "human-input blockage\n\n"
            "When a Stop is allowed with a narrow 'blocked only on human "
            "input' STOPPING BECAUSE: shape, `auto_continue_stop` records a "
            "session-scoped marker. This handler recognises a DELIVERED "
            "failsafe-cron tick (the canonical prompt from "
            "`recovery_cron_advisor`) and, while a still-valid marker exists "
            "for the session, blocks the tick before it reaches the model — "
            "genuinely zero-token, not just cheaper. A real (non-cron) user "
            "prompt clears the marker; the marker also expires "
            "(`expiry_hours`, default 24) so an extended silence restores "
            "full hourly coverage automatically. Never terminal: other "
            "handlers keyed on the same canonical prompt still run.\n\n"
            "**A session that declares nothing is backed off, not left at "
            "hourly** (Plan 00337). When the daemon-side goal ledger holds no "
            "still-live goal, ticks thin out — hourly, then every 2 hours, "
            "then every 4, and **never sparser than that**, so a session "
            "interrupted by a rate limit still recovers once the limit lifts. "
            "This needs nothing from you: there is no phrasing to get right "
            "and no way to over-suppress by staying quiet. Any real user "
            "message resets it to hourly immediately.\n\n"
            "**A session with work still owed on the ledger is never thinned** "
            "— that is the case the cron exists for. Nor is a plan directory "
            "the daemon cannot resolve treated as 'nothing owed': it counts as "
            "owed, so a misconfiguration costs a wasted tick rather than a "
            "withdrawn safety net.\n\n"
            "**On by default** (dogfooding purpose). Disable with:\n\n"
            "```yaml\n"
            "handlers:\n"
            "  user_prompt_submit:\n"
            "    failsafe_cron_blockage_suppressor:\n"
            "      enabled: false\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="No marker: a delivered cron tick is allowed through unchanged",
                command='echo "test"',
                description=(
                    "Default state check. With no blockage marker recorded, "
                    "submitting the canonical failsafe-cron prompt must be "
                    "allowed through unchanged (ALLOW, no suppression)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Advisory-adjacent handler; this test asserts the SAFE default "
                    "(no suppression without a marker)."
                ),
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
