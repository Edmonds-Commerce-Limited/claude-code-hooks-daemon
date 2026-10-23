"""GoalLoopDetectorHandler - observe a session looping on an unmet goal.

Plan 00501 Tasks 6.1 and 6.2. A goal loop is a session that keeps stopping with
``STOPPING BECAUSE:`` while Claude Code's goal evaluator keeps answering "not
met", with no human prompt in between. The pure logic lives in
:mod:`claude_code_hooks_daemon.core.goal_loop`; this handler owns the
per-session state (a transcript checkpoint and a cycle ring) and the logging.

**Observe only.** On every main-thread Stop it reads the transcript lines
appended since its checkpoint, feeds them to the ring, and appends to the
session-mode transition log:

* ``loop-reset`` when a human prompt, a goal met or cleared, or a repository
  change empties a non-empty ring (the cause is the transition's ``detail``);
* ``near-miss`` when the ring is one cycle short of its threshold;
* ``would-enter`` when it has reached it (``observe``, the default).

**Act mode (``mode: act``, opt-in; Task 6.3).** At the threshold it enters
GOAL_BLOCKED for ``blocked_hours`` through ``core.goal_loop_block``, signals the
goal clear once, and queues ONE registry notice that reaches the agent at its
next prompt. The line is never Stop-result context: Claude Code reads that as
"continue", which would prolong the loop being stopped. Either way the ring's
count restarts, so a loop is logged or entered once, not on every further Stop.

**Exits (Task 6.4)**, each logged with its cause: the timer (registry EXPIRE),
the next message the human types (``failsafe_cron_blockage_suppressor``), a
repository change (here, ``cause=repo-change``), and ``hooks-daemon
session-mode unblock`` (``cause=explicit-clear``). The repo-change watch is in
memory only, so a daemon restart loses it for an entry already live; the other
three exits still apply.

**Without the ccy supervisor** nothing types ``/goal clear``. The backstop is
Claude Code's own cap of 8 consecutive stop-hook continuations (each tool call
resets it; ``CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`` raises it), after which the goal
pauses until the next message, a tick included. A loop that makes tool calls
between stops never reaches that cap.

**Goal-clear attribution (Task 8.2).** The same new lines are searched for a
typed clearing ``/goal``; each is attributed once
(:mod:`claude_code_hooks_daemon.core.goal_clear_attribution`) from the ccy
supervisor's ``.goal-clear-injected`` record and logged as a ``goal-clear``
transition whose ``detail`` names the supervisor or the human. A clear the log
already attributes (a restart re-reads the transcript tail) is skipped. When the
record was unreadable the clear is assumed the supervisor's and one line asking
the human to clear again is queued with ``SessionModeRegistry.queue_line``, to be
stated at the next prompt rather than as Stop context.

**Never breaks a Stop.** An unreadable transcript, an invalid checkpoint, a
failed repository fingerprint, a failed log append, a failed attribution, and a
registry failure (``OSError``, or ``RuntimeError`` from ``get_data_layer()``) on
entry or on the repo-change exit are each a named WARNING, and the Stop is allowed. It never
blocks and never returns ``continue: false``.

**Ordering.** Priority 5 runs it ahead of the terminal ``auto_continue_stop``
(10), so it sees every stop; it is non-terminal so every handler behind it runs.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext, get_data_layer
from claude_code_hooks_daemon.core.goal_clear_attribution import (
    Attribution,
    GoalClearAttributionError,
    attribute_clear,
    attributed_keys,
    find_typed_clears,
)
from claude_code_hooks_daemon.core.goal_loop import (
    Checkpoint,
    CheckpointInvalidError,
    CycleRing,
    DetectorMode,
    FingerprintError,
    GoalLoopConfig,
    RingReset,
    Verdict,
    assess,
    extract_events,
    option_problems,
    read_new_lines,
    repo_fingerprint,
)
from claude_code_hooks_daemon.core.goal_loop_block import enter_goal_loop
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.manual_goals import GoalsOutcome, enter_manual_goals
from claude_code_hooks_daemon.core.session_mode_log import (
    MAX_TRANSITIONS,
    ModeTransition,
    TransitionAction,
    TransitionLogError,
)
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
    _STOP_EXPLANATION_PREFIX,
    _declares_human_blocked,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_modes import ModeLabel, ModeSource
from claude_code_hooks_daemon.utils.session_signal_paths import SIGNAL_SUBDIR

logger = logging.getLogger(__name__)

#: Sessions whose checkpoint and ring are kept; the least recently seen is dropped.
MAX_TRACKED_SESSIONS: Final[int] = 64

#: The most a single Stop reads: a session's first sight, or a backlog, is read
#: from its last ``TAIL_BYTES`` only.
TAIL_BYTES: Final[int] = 2 * 1024 * 1024

_VERDICT_ACTION: Final[dict[Verdict, TransitionAction]] = {
    Verdict.NEAR_MISS: TransitionAction.NEAR_MISS,
    Verdict.WOULD_ENTER: TransitionAction.WOULD_ENTER,
}


@dataclass(slots=True)
class _SessionState:
    """What the detector remembers about one session between Stops."""

    ring: CycleRing
    checkpoint: Checkpoint | None = None
    #: The repository fingerprint when act mode entered GOAL_BLOCKED; None when not watching.
    blocked_fingerprint: str | None = None


class GoalLoopDetectorHandler(StopHandlerBase):
    """Log a session's goal-loop cycles to the transition log; always allow."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GOAL_LOOP_DETECTOR,
            priority=Priority.GOAL_LOOP_DETECTOR,
            terminal=False,
            # Goals are set and evaluated on the coordinator's own session.
            scope=HandlerScope.MAIN,
            tags=[HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )
        defaults = GoalLoopConfig()
        # Options (``apply_handler_options`` sets ``_<key>``); validated by validate_options.
        self._mode: str = str(defaults.mode)
        self._cycle_threshold: int = defaults.cycle_threshold
        self._declared_cycle_threshold: int = defaults.declared_cycle_threshold
        self._window_minutes: int = defaults.window_minutes
        self._blocked_hours: float = defaults.blocked_hours
        # Seams: tests substitute these so they need no git and no data layer.
        self._fingerprint_repo: Callable[[], str] = self._default_fingerprint
        self._append_transition: Callable[[ModeTransition], None] = self._default_append
        self._clock: Callable[[], float] = time.time
        self._registry: Callable[[], SessionModeRegistry] = self._default_registry
        self._clear_goal: Callable[[str], bool] = self._default_clear_goal
        self._recent_transitions: Callable[[str], list[ModeTransition]] = (
            self._default_recent_transitions
        )
        self._clear_record_dir: Callable[[], Path] = self._default_clear_record_dir
        self._sessions: OrderedDict[str, _SessionState] = OrderedDict()

    validate_options = staticmethod(option_problems)

    def get_default_enabled(self) -> bool:
        """On by default: it only reads the transcript and writes the transition log."""
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every main-thread Stop; ``handle`` decides whether there is anything to read."""
        return True

    def _config(self) -> GoalLoopConfig:
        return GoalLoopConfig.from_options(
            {
                "mode": self._mode,
                "cycle_threshold": self._cycle_threshold,
                "declared_cycle_threshold": self._declared_cycle_threshold,
                "window_minutes": self._window_minutes,
                "blocked_hours": self._blocked_hours,
            }
        )

    def _state(self, session_id: str, config: GoalLoopConfig) -> _SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            state = _SessionState(ring=CycleRing(window_seconds=config.window_seconds))
            self._sessions[session_id] = state
            while len(self._sessions) > MAX_TRACKED_SESSIONS:
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(session_id)
        return state

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Read the new transcript lines, feed the ring, log what it shows; allow."""
        allow = BlockingResult(decision=Decision.ALLOW)
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        transcript = str(hook_input.get(HookInputField.TRANSCRIPT_PATH) or "")
        if not session_id or not transcript:
            logger.info(
                "goal-loop detector: no transcript_path or session_id on this Stop; nothing read"
            )
            return allow
        config = self._config()
        state = self._state(session_id, config)
        try:
            lines, state.checkpoint = read_new_lines(
                Path(transcript), state.checkpoint, tail_bytes=TAIL_BYTES
            )
        except CheckpointInvalidError as error:
            logger.warning(
                "goal-loop detector: checkpoint invalid, re-anchored at EOF (%s): %s",
                transcript,
                error,
            )
            state.checkpoint = error.anchor
            return allow
        except OSError as error:
            logger.warning("goal-loop detector: transcript unreadable %s: %s", transcript, error)
            return allow
        self._attribute_clears(session_id, lines)
        extraction = extract_events(
            lines, stop_prefix=_STOP_EXPLANATION_PREFIX, declares_blocked=_declares_human_blocked
        )
        fed = state.ring.feed(extraction.events)
        for reset in fed.resets:
            self._log_reset(session_id, reset)
        if fed.new_cycles == 0 and state.blocked_fingerprint is None:
            return allow
        try:
            fingerprint = self._fingerprint_repo()
        except FingerprintError as error:
            logger.warning("goal-loop detector: fingerprint failed: %s", error)
            return allow
        if state.blocked_fingerprint is not None:
            self._exit_on_repo_change(session_id, state, fingerprint)
        if fed.new_cycles == 0:
            return allow
        repo_reset = state.ring.note_fingerprint(fingerprint, new_cycles=fed.new_cycles)
        if repo_reset is not None:
            self._log_reset(session_id, repo_reset)
        assessment = assess(state.ring, config)
        evidence = assessment.evidence(config, state.ring.fingerprint)
        if assessment.verdict is Verdict.WOULD_ENTER and config.mode is DetectorMode.ACT:
            self._enter(session_id, state, config, evidence, fingerprint)
        else:
            action = _VERDICT_ACTION.get(assessment.verdict)
            if action is not None:
                self._log(
                    ModeTransition(
                        at=self._clock(),
                        session_id=session_id,
                        label=ModeLabel.GOAL_BLOCKED,
                        action=action,
                        evidence=evidence,
                    )
                )
        if assessment.verdict is Verdict.WOULD_ENTER:
            # Logged (or entered) once per loop, not on every further Stop of it.
            state.ring.restart_count()
        return allow

    def _enter(
        self,
        session_id: str,
        state: _SessionState,
        config: GoalLoopConfig,
        evidence: str,
        fingerprint: str,
    ) -> None:
        """Act mode: goal-block the session; a failure is a WARNING and the Stop proceeds."""
        try:
            enter_goal_loop(
                self._registry(),
                session_id,
                ttl_seconds=config.blocked_seconds,
                evidence=evidence,
                clear_goal=self._clear_goal,
            )
        except (OSError, RuntimeError) as error:
            log_and_continue(
                logger,
                error,
                reason=(
                    f"goal-loop detector: goal-blocked mode not entered for {session_id}; "
                    "a Stop is never broken, and the would-be entry is in this warning"
                ),
            )
        else:
            state.blocked_fingerprint = fingerprint

    def _exit_on_repo_change(self, session_id: str, state: _SessionState, fingerprint: str) -> None:
        """End this detector's block when the repository changed; forget it once it has ended."""
        old = state.blocked_fingerprint
        try:
            registry = self._registry()
            if ModeLabel.GOAL_BLOCKED not in {e.label for e in registry.active(session_id)}:
                logger.info(
                    "goal-loop detector: %s is no longer goal-blocked (ended by timer, human "
                    "or unblock); repo-change watch dropped",
                    session_id,
                )
                state.blocked_fingerprint = None
                return
            if fingerprint == old:
                return
            registry.exit(
                session_id,
                ModeLabel.GOAL_BLOCKED,
                evidence=f"cause=repo-change fingerprint={old}->{fingerprint}",
            )
            state.blocked_fingerprint = None
        except (OSError, RuntimeError) as error:
            log_and_continue(
                logger,
                error,
                reason=(
                    f"goal-loop detector: the repo-change exit was not made for {session_id}; "
                    "the block still ends on its timer, a human prompt or an unblock"
                ),
            )

    def _attribute_clears(self, session_id: str, lines: list[str]) -> None:
        """Log who typed each clearing ``/goal`` in ``lines``, once per clear; never break a Stop."""
        try:
            clears = find_typed_clears(lines)
            if not clears:
                return
            seen = attributed_keys(self._recent_transitions(session_id))
            directory = self._clear_record_dir()
            for clear in clears:
                if clear.key in seen:
                    continue
                verdict = attribute_clear(clear, session_id=session_id, directory=directory)
                self._log(verdict.transition(session_id))
                line = verdict.line()
                if line is not None:
                    self._registry().queue_line(session_id, line)
                if verdict.attribution is Attribution.HUMAN:
                    self._enter_manual_goals(session_id, verdict.evidence)
        except (OSError, RuntimeError, GoalClearAttributionError, TransitionLogError) as error:
            log_and_continue(
                logger,
                error,
                reason=(
                    f"goal-loop detector: goal-clear attribution not made for {session_id}; "
                    "an unattributed clear leaves automated goals as they were, so the Stop "
                    "proceeds"
                ),
            )

    def _enter_manual_goals(self, session_id: str, evidence: str) -> None:
        """A human cleared the goal: enter manual goals, stating it once on entry.

        Raises:
            OSError: the registry write failed (the caller logs it).
        """
        registry = self._registry()
        change = enter_manual_goals(
            registry,
            session_id,
            source=ModeSource.HUMAN,
            evidence=f"a human typed a goal clear ({evidence})",
        )
        if change.outcome is GoalsOutcome.ENTERED:
            registry.queue_line(session_id, change.line())

    def _log_reset(self, session_id: str, reset: RingReset) -> None:
        self._log(
            ModeTransition(
                at=reset.at,
                session_id=session_id,
                label=ModeLabel.GOAL_BLOCKED,
                action=TransitionAction.LOOP_RESET,
                evidence=f"cause={reset.cause} dropped={reset.dropped}",
                detail=str(reset.cause),
            )
        )

    def _log(self, transition: ModeTransition) -> None:
        """Append one transition; a failure is a WARNING, never a broken Stop."""
        try:
            self._append_transition(transition)
        except (OSError, RuntimeError) as error:
            log_and_continue(
                logger,
                error,
                reason=(
                    f"goal-loop detector: transition not logged ({transition.action} "
                    f"{transition.session_id}); the detector only observes, so the Stop proceeds"
                ),
            )

    @staticmethod
    def _default_registry() -> SessionModeRegistry:
        return get_data_layer().session_modes

    @staticmethod
    def _default_clear_goal(session_id: str) -> bool:
        # Deferred: daemon.session_mode_ipc imports daemon.server, which loads the handlers.
        from claude_code_hooks_daemon.daemon.session_mode_ipc import clear_goal_signal

        return clear_goal_signal(session_id)

    @staticmethod
    def _default_fingerprint() -> str:
        return repo_fingerprint(ProjectContext.project_root())

    @staticmethod
    def _default_append(transition: ModeTransition) -> None:
        log = get_data_layer().session_modes.transition_log
        if log is not None:
            log.append([transition])

    @staticmethod
    def _default_recent_transitions(session_id: str) -> list[ModeTransition]:
        log = get_data_layer().session_modes.transition_log
        if log is None:
            return []
        return log.recent(MAX_TRANSITIONS, session_id=session_id)

    @staticmethod
    def _default_clear_record_dir() -> Path:
        return ProjectContext.daemon_untracked_dir() / SIGNAL_SUBDIR

    def get_claude_md(self) -> str | None:
        """No resident guidance: it never blocks a tool, and act mode is opt-in.

        Deliberate: guidance here would end its guidance-coverage exemption and
        change the generated CLAUDE.md block for every project, while act mode's
        one-time line already reaches the affected session as a registry notice.
        """
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: an ordinary stop is always allowed (the detector only observes)."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="goal loop detector - an ordinary stop is allowed",
                command="echo 'ordinary stop'",
                description=(
                    "The detector only observes: whatever the transcript shows, the Stop "
                    "is allowed and at most a transition-log line is written."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Observe-only handler; it never blocks.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="Stop",
                requires_main_thread=False,
                hook_input={"hook_event_name": "Stop", "stop_hook_active": False},
            ),
        ]
