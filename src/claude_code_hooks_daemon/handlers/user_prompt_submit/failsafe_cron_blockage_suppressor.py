"""FailsafeCronBlockageSuppressorHandler - zero-token cadence for a stably
human-input-blocked session (Plan 00298).

The failsafe recovery cron (``recovery_cron_advisor``) fires the canonical
cron prompt hourly while the REPL is idle, to recover from EXTERNAL
interruptions (API error, rate limit, 5-hour usage limit, network failure). A
session that is blocked ONLY on human input is not that state -- every tick
against it is a guaranteed no-op that still costs one full model turn (prompt
in, generation out, transcript write, stop-hook round trip) for nothing.

This handler is the ``UserPromptSubmit`` half of the design: it recognises a
DELIVERED canonical-cron-prompt tick and, while THIS session holds a live
blocked session mode (awaiting-human, entered by ``auto_continue_stop``, or
goal-loop blocked) in the daemon's session-modes registry, blocks the prompt
before it ever reaches the model (Claude Code's documented
``UserPromptSubmit`` "block" behaviour -- the prompt is dropped, not
forwarded). That is genuinely zero-token, unlike a convention/prompt-text
backoff which still costs a turn to read and act on.

**Minimal by design (owner ruling, Plan 00298 BRAINSTORM.md: "sounds complex
and brittle to me").** One registry lookup, one session-scoped policy, no
fallback chains. See ``utils.session_modes`` for the policy and
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

**Fails open everywhere**: no mode, another session's mode, an expired mode,
or an unreadable registry all ALLOW the tick through unchanged (the last with a
WARNING) -- suppression is a positive assertion made only when every
condition is individually verified, never the default. A genuine external
interruption during the blocked window is still bounded by "however long the
owner takes to respond" (BRAINSTORM.md), and the mode's fixed lifetime further
bounds an unresponsive owner's silence.

**Which prompt is the owner (Plan 00388).** A prompt exits the blocked modes and
resets the cadence only if it carries no daemon tick sentinel
(``utils.cron_tick``). Every
cron prompt the daemon supplies has one -- the failsafe, the background
watchdog, every ``persistent_crons`` job -- so in a multi-cron session another
cron's tick never reads as the owner coming back. A declared job's tick is
dropped under a blocked mode too unless the job sets
``runs_while_awaiting_human``; the watchdog's never is. A cron whose prompt
the daemon never wrote still reads as the owner, which fails toward clearing.

**Never terminal.** ``idle_housekeeping_advisory`` and
``standing_authorisations`` also key off the same canonical cron prompt and
must keep running on every NON-suppressed tick. A non-terminal DENY still
survives later handlers regardless of registration order
(``core/router.py``: "a non-terminal deny now survives later handlers"), so
staying non-terminal costs nothing on the suppressed path either.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.data_layer import get_data_layer
from claude_code_hooks_daemon.core.focus_mode import failsafe_focus_line
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.handlers.post_tool_use.recovery_cron_advisor import (
    CANONICAL_CRON_PROMPT_MARKER,
    is_failsafe_prompt,
)
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.cron_cadence import (
    CADENCE_FILENAME,
    next_tick_decision,
    read_cadence,
    reset_cadence,
    write_cadence,
)
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.cron_tick import DaemonTick, TickKind, classify_tick
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.goal_ledger import (
    LEDGER_FILENAME,
    GoalLedger,
    resolve_plan_dir,
)
from claude_code_hooks_daemon.utils.session_modes import (
    BLOCKED_LABELS,
    SessionPolicy,
    TickAction,
    is_genuine_human_prompt,
)

logger = logging.getLogger(__name__)

_UNKNOWN_SESSION: Final[str] = "unknown"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.FAILSAFE_CRON_SUPPRESSED,
    blocked="A delivered failsafe-cron tick, while the session is in the awaiting-human mode",
    why="Every tick against a session blocked only on human input is a guaranteed no-op model turn",
    fix="Nothing to do -- this is expected. Send a real message to end the mode and resume ticks",
    verbose=(
        "This session is in a blocked session mode -- awaiting-human, entered "
        "when a stop declared it was blocked only on human input (Plan 00298), "
        "or goal-loop blocked -- and the mode is still within its lifetime, so "
        "this failsafe-cron tick was dropped before reaching the model -- no "
        "turn spent. A real (non-cron) user prompt ends the mode immediately; "
        "the mode's own expiry restores full hourly cron coverage "
        "automatically if the owner stays silent for longer."
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

_DECLARED_RULE: Final[Rule] = Rule(
    rule_id=RuleID.DECLARED_CRON_SUPPRESSED,
    blocked=(
        "A delivered persistent_crons tick, while the session is in the awaiting-human, "
        "goal-blocked or focus mode"
    ),
    why=(
        "A declared job's tick against a session blocked only on human input, or focused on "
        "one task, costs a full model turn"
    ),
    fix=(
        "Nothing to do -- this is expected. Send a real message (or `hooks-daemon focus off`) "
        "to end the mode and resume ticks"
    ),
    verbose=(
        "This session is in a focus mode (the human pointed it at one task; "
        "every declared job is dropped, Plan 00501), or in a blocked session "
        "mode (awaiting-human, or goal-loop blocked) still within its lifetime, and this tick carries a "
        "declared persistent_crons job's [tick:job:<id>] sentinel, so it was "
        "dropped before reaching the model -- no turn spent (Plan 00388). Only "
        "ticks the daemon supplied the prompt for are recognised; a real user "
        "prompt ends the mode and every cron resumes, and the mode's own expiry "
        "restores them if the owner stays silent for longer. A job whose "
        "declaration sets `runs_while_awaiting_human: true` is exempt and its "
        "ticks are delivered under an awaiting-human mode (Plan 00470); the "
        "failsafe and every job without the option are still dropped."
    ),
)


def _session_of(hook_input: dict[str, Any]) -> str:
    """The payload's session id, or the shared fallback bucket the writer also uses."""
    return str(hook_input.get(HookInputField.SESSION_ID, "") or _UNKNOWN_SESSION)


def _policy(session_id: str) -> SessionPolicy:
    """``session_id``'s mode policy from the registry; empty when it cannot be read.

    An unreadable registry delivers the tick (suppression is never the
    default), and the WARNING makes the lost suppression visible.
    """
    try:
        return get_data_layer().session_modes.policy(session_id)
    except (RuntimeError, OSError) as e:
        log_and_continue(
            logger,
            e,
            reason="the session-modes registry cannot be read, so no mode suppresses this tick",
        )
        return SessionPolicy.from_entries(())


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
        # Injectable config source (tests substitute a fixed Config).
        self._config_loader: Callable[[], Config] = self._default_config_loader
        # Injected by the registry for planning-tagged handlers. Self-defaulted
        # because the injection block does not run at all when plan_workflow is
        # None -- so a missing tag reads as None rather than raising, which is
        # why the tag is asserted by a test instead of trusted.
        self._track_plans_in_project: str | None = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match a delivered canonical-cron-prompt tick, OR any real prompt
        while there is session state a genuine reply should clear.

        The cadence file is checked as well as the mode, and that is not
        belt-and-braces: in the row this backoff exists for ("nothing owed,
        nothing declared") there is by definition NO blocked mode, so a mode-only
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
        if (untracked_dir / CADENCE_FILENAME).exists():
            return True
        return _policy(_session_of(hook_input)).is_blocked

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
            log_and_continue(
                logger,
                e,
                reason="without a plan context the cadence cannot consult the goal ledger (None), so the default hourly cadence applies",
                level=logging.DEBUG,
            )
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
            log_and_continue(
                logger,
                e,
                reason="the goal ledger cannot be consulted (None), so the default hourly cadence applies; the WARNING names the failure",
            )
            return None

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Suppress a cron tick while this session is in a blocked mode;
        exit the blocked modes on any genuine (non-cron) prompt.

        Args:
            hook_input: The UserPromptSubmit event's hook input.

        Returns:
            DENY (blocks/erases the prompt) only for a cron-prompt tick the
            session's mode policy drops or thins. ALLOW in every other case,
            including every failure mode -- a real prompt that fails to exit
            the mode (e.g. a registry write error) still gets through unchanged.
        """
        session_id = _session_of(hook_input)
        try:
            untracked_dir = ProjectContext.daemon_untracked_dir()
        except RuntimeError as e:
            logger.debug("failsafe_cron_blockage_suppressor: no project context: %s", e)
            return BlockingResult(decision=Decision.ALLOW)
        cadence_path = untracked_dir / CADENCE_FILENAME

        prompt = hook_input.get(HookInputField.PROMPT)
        tick = classify_tick(prompt)
        # By sentinel, or by the heading literal a failsafe cron created before
        # the sentinel existed carries alone (Plan 00388).
        is_failsafe_tick = isinstance(prompt, str) and is_failsafe_prompt(prompt)

        if tick is None and not is_failsafe_tick:
            self._note_untagged_prompt(prompt, session_id, cadence_path)
            return BlockingResult(decision=Decision.ALLOW)

        policy = _policy(session_id)

        if not is_failsafe_tick and tick is not None:
            # Another daemon cron's tick is never the owner, so it touches
            # neither the session's modes nor the cadence (Plan 00388).
            return self._handle_other_tick(
                tick,
                policy=policy,
                session_id=session_id,
                hostname=effective_hostname(hook_input),
            )

        try:
            owed = self._work_is_owed()
        except (RuntimeError, OSError) as e:
            # _work_is_owed handles its own known failures; this is the outer
            # guarantee that a NEW one cannot turn into a silently withdrawn
            # safety net.
            log_and_continue(
                logger,
                e,
                reason="a new failure in the owed-work consult leaves owed unknown (None); the WARNING names it so a withdrawn safety net is visible",
            )
            owed = None

        failsafe = tick if tick is not None else DaemonTick(TickKind.FAILSAFE)
        action = policy.tick_action(failsafe, runs_while_blocked=False, work_owed=owed)

        focus_task = policy.focus_task
        if action is TickAction.DELIVER_NAMING_FOCUS and focus_task is not None:
            # Ruling 04: a focused session still gets its safety net, told which
            # task it is on. Never thinned: focus is the human's, not idleness.
            reset_cadence(cadence_path)
            return BlockingResult(
                decision=Decision.ALLOW, context=[failsafe_focus_line(focus_task)]
            )

        if action is TickAction.THIN:
            # Row 2: the session is blocked, but the ledger still holds live
            # work. Suppressing outright would be unsafe and hourly would be
            # wasteful, so thin out instead of choosing either extreme.
            return self._apply_backoff(cadence_path, session_id)

        if action is not TickAction.DROP:
            # Rows 1 and 4. With work owed -- or unresolvable, which must read
            # as owed -- this is the case the cron exists for and must never be
            # thinned. Only a confident "nothing owed" earns a backoff.
            if owed is not False:
                reset_cadence(cadence_path)
                return BlockingResult(decision=Decision.ALLOW)
            return self._apply_backoff(cadence_path, session_id)

        # Row 3: blocked, and nothing owed -- Plan 00298's suppression. `owed
        # is None` lands here too (the policy thins only on a confident "owed"):
        # the declaration alone justified suppression before Phase 4, and the
        # ledger's blind spot must not make this path LESS safe than it was.
        reset_cadence(cadence_path)
        logger.info(
            "failsafe_cron_blockage_suppressor: suppressing cron tick for session %s",
            session_id,
        )
        return BlockingResult(
            decision=Decision.DENY, reason=RuleFormatter().verbose(_RULE), rule=_RULE.rule_id
        )

    @staticmethod
    def _note_untagged_prompt(prompt: object, session_id: str, cadence_path: Path) -> None:
        """End this session's BLOCKED modes and cadence when the prompt is its owner.

        Only a genuine human prompt in the SAME session is the owner coming back
        (Plan 00501 Task 2.1, ledger N378). A line the ccy supervisor typed, a
        task notification or other machine traffic is not, and a prompt in
        another session touches only that session's registry entries: both
        leave this session's modes and the cadence alone. A registry write
        failure is logged at WARNING and the prompt is still allowed.
        """
        if not is_genuine_human_prompt(prompt):
            logger.info(
                "failsafe_cron_blockage_suppressor: machine-typed prompt in session %s "
                "is not the owner; modes and cadence kept",
                session_id,
            )
            return
        try:
            registry = get_data_layer().session_modes
            for label in BLOCKED_LABELS:
                registry.exit(session_id, label)
        except (RuntimeError, OSError) as e:
            log_and_continue(
                logger,
                e,
                reason="the owner's prompt could not end the session's blocked mode, so ticks stay suppressed until it expires; the prompt itself is allowed",
            )
        cadence = read_cadence(cadence_path)
        if cadence is None or cadence.session_id == session_id:
            reset_cadence(cadence_path)

    def _default_config_loader(self) -> Config:
        """The project's daemon config; defaults when it cannot be loaded.

        Defaults declare no job, so an unloadable config leaves every declared
        job suppressed -- the behaviour before the per-job option existed.
        """
        try:
            config_path = ProjectContext.project_root() / ".claude" / "hooks-daemon.yaml"
            return load_config_cached(config_path)
        except (RuntimeError, ValidationError, OSError, ValueError) as exc:
            logger.debug("failsafe_cron_blockage_suppressor: cannot load config: %s", exc)
            return default_config()

    def _handle_other_tick(
        self, tick: DaemonTick, *, policy: SessionPolicy, session_id: str, hostname: str
    ) -> BlockingResult:
        """Decide a recognised tick from a cron other than the failsafe.

        A declared ``persistent_crons`` job stands down with a blocked mode (Task
        2.4, Plan 00392 N1): the session said it is blocked only on the human,
        and the observed case was an ``issue-sdlc`` tick finding every issue
        parked on one. A job that sets ``runs_while_awaiting_human`` is
        delivered regardless (Plan 00470 Task 5.1): its work does not depend on
        the pending question. The watchdog never stands down -- reaping runaway
        background processes is not blocked on the human, and an idle wait is
        exactly the window it was created to cover.

        Args:
            tick: The recognised tick, never the failsafe.
            policy: This session's mode policy.
            session_id: The current session.
            hostname: The session's effective hostname; a job declared only for
                other hosts is not vouched for here (Plan 00470 Task 6.1).

        Returns:
            DENY when the session's modes drop the tick, else ALLOW.
        """
        runs = (
            tick.kind is TickKind.DECLARED
            and policy.is_blocked
            and tick.job_id is not None
            and self._config_loader().persistent_crons.runs_while_awaiting_human(
                tick.job_id, hostname
            )
        )
        action = policy.tick_action(tick, runs_while_blocked=runs, work_owed=None)
        if action is not TickAction.DROP:
            return BlockingResult(decision=Decision.ALLOW)
        logger.info(
            "failsafe_cron_blockage_suppressor: suppressing declared cron %s for session %s",
            tick.job_id,
            session_id,
        )
        reason = (
            f"{RuleFormatter().verbose(_DECLARED_RULE)}\n\nDeclared job: {tick.job_id}\n"
            f"Session mode: {policy.explain_clause()}"
        )
        return BlockingResult(decision=Decision.DENY, reason=reason, rule=_DECLARED_RULE.rule_id)

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
        return BlockingResult(
            decision=Decision.DENY,
            reason=RuleFormatter().verbose(_BACKOFF_RULE),
            rule=_BACKOFF_RULE.rule_id,
        )

    def get_rules(self) -> list[Rule]:
        """Return the Rules backing this handler's DENY paths.

        Separate rules because the situations differ in what the agent can do
        about them: suppression needs a declaration and stops ticks entirely
        until a real prompt; the backoff needs nothing and never stops them;
        a declared job's suppression names a different cron.
        """
        return [_RULE, _BACKOFF_RULE, _DECLARED_RULE]

    def get_claude_md(self) -> str | None:
        """Document the suppression contract."""
        return (
            "## failsafe_cron_blockage_suppressor — zero-token cadence for "
            "human-input blockage\n\n"
            "When a Stop is allowed with a narrow 'blocked only on human "
            "input' STOPPING BECAUSE: shape, `auto_continue_stop` puts the "
            "session into the awaiting-human mode in the daemon's session-modes "
            "registry. This handler recognises a DELIVERED "
            "failsafe-cron tick (the canonical prompt from "
            "`recovery_cron_advisor`) and, while the session is in that mode "
            "(or goal-loop blocked), blocks the tick before it reaches the "
            "model — genuinely zero-token, not just cheaper. A real (non-cron) "
            "user prompt ends the mode; the mode also expires "
            "(24 hours after it was entered) so an extended silence restores "
            "full hourly coverage automatically. A focus mode "
            "(`hooks-daemon focus <task>`) never drops the failsafe tick: it "
            "arrives with the line `focus mode: the active task is <task>; "
            "other plans are out of scope`. Never terminal: other "
            "handlers keyed on the same canonical prompt still run.\n\n"
            "**Several crons in one session** (Plan 00388). Every cron prompt "
            "the daemon hands you starts with a sentinel line — "
            "`[tick:failsafe]`, `[tick:watchdog]` or `[tick:job:<id>]` — so "
            "paste it verbatim and never drop that line. A tick carrying one "
            "is never mistaken for the owner, so it leaves the mode and the "
            "cadence alone. A declared `persistent_crons` job's tick is also "
            "dropped while the mode is live (`R-DECLARED-CRON-SUPPRESSED`) "
            "unless the job sets `runs_while_awaiting_human: true`, and every "
            "declared job's tick is dropped while the session is focused; "
            "the watchdog's is always delivered. A cron prompt you composed "
            "yourself carries no sentinel and still reads as the owner.\n\n"
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
                title="No blocked mode: a delivered cron tick is allowed through unchanged",
                command='echo "test"',
                description=(
                    "Default state check. With no blocked session mode, "
                    "submitting the canonical failsafe-cron prompt must be "
                    "allowed through unchanged (ALLOW, no suppression)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Advisory-adjacent handler; this test asserts the SAFE default "
                    "(no suppression without a blocked mode)."
                ),
                test_type=TestType.CONTEXT,
                requires_event="UserPromptSubmit event (cannot be triggered by subagent)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
