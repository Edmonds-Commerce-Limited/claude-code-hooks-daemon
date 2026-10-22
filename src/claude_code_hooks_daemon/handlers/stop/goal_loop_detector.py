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
* ``would-enter`` when it has reached it.

It never blocks and never enters a mode; ``act`` is not a valid ``mode`` yet.

**Never breaks a Stop.** An unreadable transcript, an invalid checkpoint, a
failed repository fingerprint and a failed log append are each a named WARNING,
and the Stop is allowed.

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
from claude_code_hooks_daemon.core.goal_loop import (
    Checkpoint,
    CheckpointInvalidError,
    CycleRing,
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
from claude_code_hooks_daemon.core.handler_bases import StopHandlerBase
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.core.session_mode_log import ModeTransition, TransitionAction
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
    _STOP_EXPLANATION_PREFIX,
    _declares_human_blocked,
)
from claude_code_hooks_daemon.utils.session_modes import ModeLabel

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
        extraction = extract_events(
            lines, stop_prefix=_STOP_EXPLANATION_PREFIX, declares_blocked=_declares_human_blocked
        )
        fed = state.ring.feed(extraction.events)
        for reset in fed.resets:
            self._log_reset(session_id, reset)
        if fed.new_cycles == 0:
            return allow
        try:
            fingerprint = self._fingerprint_repo()
        except FingerprintError as error:
            logger.warning("goal-loop detector: fingerprint failed: %s", error)
            return allow
        repo_reset = state.ring.note_fingerprint(fingerprint, new_cycles=fed.new_cycles)
        if repo_reset is not None:
            self._log_reset(session_id, repo_reset)
        assessment = assess(state.ring, config)
        action = _VERDICT_ACTION.get(assessment.verdict)
        if action is not None:
            self._log(
                ModeTransition(
                    at=self._clock(),
                    session_id=session_id,
                    label=ModeLabel.GOAL_BLOCKED,
                    action=action,
                    evidence=assessment.evidence(config, state.ring.fingerprint),
                )
            )
        return allow

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
            logger.warning(
                "goal-loop detector: transition not logged (%s %s): %s",
                transition.action,
                transition.session_id,
                error,
            )

    @staticmethod
    def _default_fingerprint() -> str:
        return repo_fingerprint(ProjectContext.project_root())

    @staticmethod
    def _default_append(transition: ModeTransition) -> None:
        log = get_data_layer().session_modes.transition_log
        if log is not None:
            log.append([transition])

    def get_claude_md(self) -> str | None:
        """No resident guidance: the detector only observes and never blocks."""
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
