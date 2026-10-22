"""Entering and ending a goal-loop block (Plan 00501 Tasks 6.3 and 6.4).

In ``act`` mode the goal-loop detector puts the session in GOAL_BLOCKED for
``blocked_hours``, signals the goal clear once (the ccy supervisor types
``/goal clear`` at its next idle), and queues one registry notice, so the line
reaches the agent at its next prompt rather than as Stop context (which Claude
Code would read as "continue" and so prolong the loop).

The block ends on its timer, at the next message the human types, on a
repository change, or on an explicit unblock. An unblock ends ONLY the
goal-loop entry: a declared awaiting-human entry ends only on a genuine prompt
from the human (Plan 00501 Phase 2), so an unblock that finds only that entry
is refused with :class:`DeclaredBlockRefusedError` and leaves it in place.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from claude_code_hooks_daemon.core.session_mode_registry import (
    ModeNotice,
    NoticeKind,
    SessionModeRegistry,
)
from claude_code_hooks_daemon.utils.session_modes import ModeLabel, goal_loop_blocked_entry

logger = logging.getLogger(__name__)


class DeclaredBlockRefusedError(ValueError):
    """An unblock asked to end a declared awaiting-human entry, which only the human ends."""


def enter_goal_loop(
    registry: SessionModeRegistry,
    session_id: str,
    *,
    ttl_seconds: float,
    evidence: str,
    clear_goal: Callable[[str], bool],
) -> bool:
    """Goal-block ``session_id`` for ``ttl_seconds``, signal the goal clear and queue the notice.

    A session already goal-blocked is entered again, which renews the expiry
    and signals the clear again.

    Args:
        registry: The session-modes registry.
        session_id: The looping session.
        ttl_seconds: How long the block lasts.
        evidence: The detector's assessment, for the transition log.
        clear_goal: Signals the goal clear for a session; False when it failed.

    Returns:
        Whether the goal clear was signalled.

    Raises:
        ValueError: ``session_id`` is blank or ``ttl_seconds`` is not positive.
        OSError: the registry write failed; nothing was signalled or queued.
    """
    entry = goal_loop_blocked_entry(session_id, entered_at=registry.now(), ttl_seconds=ttl_seconds)
    registry.enter(entry, evidence=evidence)
    cleared = clear_goal(session_id)
    if not cleared:
        logger.warning(
            "goal loop: session %s is goal-blocked but the goal clear could not be signalled",
            session_id,
        )
    registry.queue_notice(ModeNotice(NoticeKind.GOAL_LOOP_ENTERED, entry, goal_cleared=cleared))
    logger.info("goal loop: session %s entered goal-blocked", session_id)
    return cleared


class UnblockOutcome(StrEnum):
    """What an unblock did."""

    UNBLOCKED = "unblocked"
    NOT_BLOCKED = "not-blocked"


@dataclass(frozen=True, slots=True)
class UnblockChange:
    """The result of an unblock, and the one line describing it.

    Attributes:
        outcome: What happened.
        declared_remains: Whether a declared awaiting-human entry still applies.
    """

    outcome: UnblockOutcome
    declared_remains: bool = False

    def line(self) -> str:
        """The single line describing this change."""
        if self.outcome is UnblockOutcome.NOT_BLOCKED:
            return (
                "SESSION MODE: this session is not goal-blocked, so there was nothing to unblock."
            )
        if self.declared_remains:
            return (
                "SESSION MODE: the goal-blocked mode has ended; the declared awaiting-human "
                "mode still applies and ends only on a message the human types."
            )
        return (
            "SESSION MODE: the goal-blocked mode has ended; declared crons and goal "
            "injection apply to this session again."
        )


_REFUSAL: str = (
    "session {sid} is not goal-blocked: its blocked mode is the declared awaiting-human "
    "mode, which ends only on a genuine prompt from the human in this session "
    "(Plan 00501 Phase 2), so unblock leaves it in place"
)


def unblock_goal_loop(
    registry: SessionModeRegistry, session_id: str, *, evidence: str
) -> UnblockChange:
    """End ``session_id``'s goal-loop block; a declared awaiting-human entry is never ended.

    Args:
        registry: The session-modes registry.
        session_id: The session to unblock.
        evidence: What asked for the unblock, for the transition log.

    Raises:
        DeclaredBlockRefusedError: only a declared awaiting-human entry is live.
        OSError: the registry write failed.
    """
    labels = {entry.label for entry in registry.active(session_id)}
    declared = ModeLabel.AWAITING_HUMAN in labels
    if ModeLabel.GOAL_BLOCKED in labels:
        registry.exit(session_id, ModeLabel.GOAL_BLOCKED, evidence=evidence)
        logger.info("goal loop: session %s unblocked (%s)", session_id, evidence)
        return UnblockChange(UnblockOutcome.UNBLOCKED, declared_remains=declared)
    if declared:
        message = _REFUSAL.format(sid=session_id)
        logger.warning("goal loop: unblock refused: %s", message)
        raise DeclaredBlockRefusedError(message)
    return UnblockChange(UnblockOutcome.NOT_BLOCKED)
