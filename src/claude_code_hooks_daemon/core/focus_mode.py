"""Focus mode: the prompt command, entering and leaving it, and its wording (Plan 00501 Phase 3).

A human points one session at one task by typing ``hooks-daemon focus <task>``
(speech-to-text spellings ``hooks daemon`` and ``hooks demon`` included) and
ends it with ``hooks-daemon focus off`` (or ``done``, ``end``, ``disable``).
The same two operations back the ``session-mode`` CLI and its IPC actions, so
every route enters and leaves focus here.

Entering focus clears an existing goal once (ruling 06): the goal-clear signal
is written and the ccy supervisor types ``/goal clear`` at its next idle.
Changing the task of a focus already on does not clear again.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.utils.session_modes import (
    FOCUS_TTL_SECONDS,
    Lifetime,
    ModeLabel,
    ModeSource,
    SessionMode,
    SessionModeEntry,
    is_genuine_human_prompt,
)

logger = logging.getLogger(__name__)

#: Words that end focus when they are the whole argument.
FOCUS_OFF_ALIASES: Final[frozenset[str]] = frozenset({"off", "done", "end", "disable"})

_SECONDS_PER_HOUR: Final[int] = 3600

#: ``hooks-daemon focus ...`` at the very start of the prompt, any case, with the
#: speech-to-text spellings ``hooks daemon`` and ``hooks demon``.
_COMMAND_RE: Final[re.Pattern[str]] = re.compile(
    r"\Ahooks[\s-]+d(?:ae|e)mon\s+focus(?:\s+(?P<rest>.*))?\Z",
    re.IGNORECASE | re.DOTALL,
)

#: Punctuation a dictated ``off`` may carry.
_TRAILING_PUNCTUATION: Final[str] = ".!"


@dataclass(frozen=True, slots=True)
class FocusCommand:
    """A parsed focus command: a task to focus on, or the request to end focus."""

    task: str
    is_off: bool


def parse_focus_command(prompt: object) -> FocusCommand | None:
    """The focus command a genuine human prompt opens with, or None.

    Machine traffic (ticks, supervisor lines, notifications) is never a command,
    so nothing but the human can turn focus on or off from a prompt.
    """
    if not isinstance(prompt, str) or not is_genuine_human_prompt(prompt):
        return None
    match = _COMMAND_RE.match(prompt.strip())
    if match is None:
        return None
    rest = (match.group("rest") or "").strip()
    if rest.rstrip(_TRAILING_PUNCTUATION).lower() in FOCUS_OFF_ALIASES:
        return FocusCommand(task="", is_off=True)
    return FocusCommand(task=rest, is_off=False)


class FocusOutcome(StrEnum):
    """What a focus operation did."""

    ENTERED = "entered"
    CHANGED = "changed"
    EXITED = "exited"
    NOT_FOCUSED = "not-focused"
    NEEDS_TASK = "needs-task"


@dataclass(frozen=True, slots=True)
class FocusChange:
    """The result of a focus operation, and the one line stated to the agent.

    Attributes:
        outcome: What happened.
        task: The focus task concerned (the old one on exit), or empty.
        goal_cleared: On entry, whether the goal clear was signalled; else None.
    """

    outcome: FocusOutcome
    task: str = ""
    goal_cleared: bool | None = None

    def line(self) -> str:
        """The single context line describing this change."""
        if self.outcome is FocusOutcome.NEEDS_TASK:
            return "FOCUS MODE NOT SET: focus needs a task; type `hooks-daemon focus <task>`."
        if self.outcome is FocusOutcome.NOT_FOCUSED:
            return "FOCUS MODE: focus was not on in this session, so there was nothing to end."
        if self.outcome is FocusOutcome.EXITED:
            return (
                f"FOCUS MODE OFF: the focus on '{self.task}' has ended; declared crons, goal "
                "injection and goal-ledger challenges apply to this session again."
            )
        hours = FOCUS_TTL_SECONDS // _SECONDS_PER_HOUR
        scope = (
            f"the active task is '{self.task}'; other plans are out of scope. Declared cron "
            "ticks, goal injection and goal-ledger challenges are off for this session; the "
            "failsafe tick still arrives, naming this task."
        )
        ending = (
            f" Focus lasts {hours} h, renewed by each prompt the human types; "
            "`hooks-daemon focus off` ends it."
        )
        if self.outcome is FocusOutcome.CHANGED:
            return f"FOCUS MODE TASK CHANGED: {scope}{ending}"
        if self.goal_cleared:
            goal = (
                " Any existing goal is being cleared: the ccy supervisor types `/goal clear` "
                "at its next idle; without the supervisor, a human must type `/goal clear`."
            )
        else:
            goal = (
                " The daemon could not signal the goal clear (see its log), so any existing "
                "goal is still set: a human must type `/goal clear`."
            )
        return f"FOCUS MODE ON: {scope}{goal}{ending}"


def enter_focus(
    registry: SessionModeRegistry,
    session_id: str,
    task: str,
    *,
    clear_goal: Callable[[str], bool],
) -> FocusChange:
    """Focus ``session_id`` on ``task``, clearing an existing goal on first entry.

    Args:
        registry: The session-modes registry.
        session_id: The session to focus.
        task: The task; a blank one is refused and no mode is entered.
        clear_goal: Signals the goal clear for a session; False when it failed.

    Raises:
        OSError: the registry write failed.
    """
    stripped = task.strip()
    if not stripped:
        return FocusChange(FocusOutcome.NEEDS_TASK)
    already = registry.policy(session_id).focus_task is not None
    now = registry.now()
    registry.enter(
        SessionModeEntry(
            mode=SessionMode.FOCUS,
            session_id=session_id,
            entered_at=now,
            expires_at=now + FOCUS_TTL_SECONDS,
            source=ModeSource.HUMAN,
            detail=stripped,
            lifetime=Lifetime.SESSION,
        )
    )
    if already:
        logger.info("focus mode: session %s changed its task", session_id)
        return FocusChange(FocusOutcome.CHANGED, task=stripped)
    cleared = clear_goal(session_id)
    if not cleared:
        logger.warning(
            "focus mode: session %s entered focus but the goal clear could not be signalled",
            session_id,
        )
    logger.info("focus mode: session %s entered focus", session_id)
    return FocusChange(FocusOutcome.ENTERED, task=stripped, goal_cleared=cleared)


def exit_focus(registry: SessionModeRegistry, session_id: str) -> FocusChange:
    """End ``session_id``'s focus.

    Raises:
        OSError: the registry write failed.
    """
    removed = registry.exit(session_id, ModeLabel.FOCUS)
    if removed is None:
        return FocusChange(FocusOutcome.NOT_FOCUSED)
    logger.info("focus mode: session %s left focus", session_id)
    return FocusChange(FocusOutcome.EXITED, task=removed.detail)


def failsafe_focus_line(task: str) -> str:
    """The line delivered with a failsafe tick while focused (ruling 04)."""
    return f"focus mode: the active task is {task}; other plans are out of scope"


def focus_reminder(task: str) -> str:
    """The one-line reminder that replaces the goal-ledger stop challenge while focused."""
    return (
        f"FOCUS MODE: the active task is '{task}'; other plans are out of scope. Continue "
        "that task, or stop with STOPPING BECAUSE: naming why it cannot proceed."
    )
