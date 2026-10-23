"""The ``manual-goals`` session mode: entering, leaving and reading it (Plan 00501 Task 8.3).

While a session is in ``manual-goals`` the daemon writes no automated goal
intent for it; ``continue``, cron ticks and every guard are unaffected, and a
``/goal <condition>`` the human types still works without ending the mode.

The mode is entered when a human clears a goal (the Stop path's attribution) or
types ``hooks-daemon goals off``, and ends only at an explicit switch-back
(``hooks-daemon goals on``, the CLI, ``/mode goals auto``) or with the session: its stored expiry
is a liveness bound every prompt renews (see
``utils.session_modes.MANUAL_GOALS_RETENTION_SECONDS``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from claude_code_hooks_daemon.constants.modes import SessionModeIPC
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.utils.session_modes import (
    ModeLabel,
    ModeSource,
    is_genuine_human_prompt,
    manual_goals_entry,
)

logger = logging.getLogger(__name__)

#: ``hooks-daemon goals <word>`` as the WHOLE prompt, any case, with the
#: speech-to-text spellings ``hooks daemon`` and ``hooks demon``.
_COMMAND_RE: Final[re.Pattern[str]] = re.compile(
    r"\Ahooks[\s-]+d(?:ae|e)mon\s+goals\s+(?P<word>\S+)\Z",
    re.IGNORECASE,
)

#: Punctuation a dictated word may carry.
_TRAILING_PUNCTUATION: Final[str] = ".!"


@dataclass(frozen=True, slots=True)
class GoalsCommand:
    """A parsed goals command: ``manual`` True enters manual goals, False switches back."""

    manual: bool


def parse_goals_command(prompt: object) -> GoalsCommand | None:
    """The goals command a genuine human prompt consists of, or None.

    ``on``/``auto`` switches automated goals back on; ``off``/``manual`` enters
    manual goals. Machine traffic is never a command, and any other word (or
    trailing text) is not one either, so ordinary prose cannot flip the mode.
    """
    if not isinstance(prompt, str) or not is_genuine_human_prompt(prompt):
        return None
    match = _COMMAND_RE.match(prompt.strip())
    if match is None:
        return None
    word = match.group("word").rstrip(_TRAILING_PUNCTUATION).lower()
    if word in SessionModeIPC.GOALS_MANUAL_WORDS:
        return GoalsCommand(manual=True)
    if word in SessionModeIPC.GOALS_AUTO_WORDS:
        return GoalsCommand(manual=False)
    return None


class GoalsOutcome(StrEnum):
    """What a manual-goals operation did."""

    ENTERED = "entered"
    ALREADY_MANUAL = "already-manual"
    EXITED = "exited"
    NOT_MANUAL = "not-manual"


_LINES: dict[GoalsOutcome, str] = {
    GoalsOutcome.ENTERED: (
        "MANUAL GOALS ON: the human owns this session's goal, so automated goal injection "
        "is off for this session and no plan-driven clear removes a goal (the goal-loop "
        "detector can still clear a goal to break a loop). `continue`, cron ticks and guards "
        "are unaffected; a typed "
        "`/goal <condition>` still works and does not end this mode. "
        "`hooks-daemon goals on` (or `/mode goals auto`) turns automated goals back on."
    ),
    GoalsOutcome.ALREADY_MANUAL: (
        "MANUAL GOALS: this session is already in manual goals; automated goal injection "
        "stays off."
    ),
    GoalsOutcome.EXITED: (
        "MANUAL GOALS OFF: automated goal injection applies to this session again; the next "
        "plan event that sets a goal sets it."
    ),
    GoalsOutcome.NOT_MANUAL: (
        "MANUAL GOALS: this session was not in manual goals, so there was nothing to end."
    ),
}


@dataclass(frozen=True, slots=True)
class GoalsChange:
    """The result of a manual-goals operation."""

    outcome: GoalsOutcome

    def line(self) -> str:
        """The single context line describing this change."""
        return _LINES[self.outcome]


def goal_intent_suppressed(registry: SessionModeRegistry, session_id: str) -> bool:
    """Whether ``session_id`` is in manual goals, so no automated goal intent is written.

    Raises:
        OSError: committing an expiry found on the read failed.
    """
    return registry.policy(session_id).goal_intent_suppressed


def enter_manual_goals(
    registry: SessionModeRegistry,
    session_id: str,
    *,
    source: ModeSource,
    evidence: str,
) -> GoalsChange:
    """Put ``session_id`` in manual goals; a session already in it is left as it is.

    Args:
        registry: The session-modes registry.
        session_id: The session.
        source: Who asked for it.
        evidence: What triggered it, for the transition log.

    Raises:
        ValueError: ``session_id`` is blank.
        OSError: the registry write failed.
    """
    if goal_intent_suppressed(registry, session_id):
        return GoalsChange(GoalsOutcome.ALREADY_MANUAL)
    registry.enter(
        manual_goals_entry(session_id, entered_at=registry.now(), source=source),
        evidence=evidence,
    )
    logger.info("manual goals: session %s entered manual goals (%s)", session_id, evidence)
    return GoalsChange(GoalsOutcome.ENTERED)


def exit_manual_goals(
    registry: SessionModeRegistry, session_id: str, *, evidence: str
) -> GoalsChange:
    """End ``session_id``'s manual goals; ``evidence`` (what asked) goes to the transition log.

    Raises:
        OSError: the registry write failed.
    """
    removed = registry.exit(session_id, ModeLabel.MANUAL_GOALS, evidence=evidence)
    if removed is None:
        return GoalsChange(GoalsOutcome.NOT_MANUAL)
    logger.info("manual goals: session %s left manual goals (%s)", session_id, evidence)
    return GoalsChange(GoalsOutcome.EXITED)
