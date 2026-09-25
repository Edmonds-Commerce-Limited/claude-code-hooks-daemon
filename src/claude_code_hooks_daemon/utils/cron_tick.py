"""The sentinel every daemon-supplied cron prompt carries (Plan 00388, option 2').

``UserPromptSubmit`` carries no automated-versus-human flag, so the daemon can
only tell one of its crons' ticks from the owner by text it wrote into the
tick's prompt. Every cron prompt the daemon hands an agent to paste into
``CronCreate`` therefore starts with one sentinel line:

=====================  =====================================================
``[tick:failsafe]``    the failsafe recovery cron (``recovery_cron_advisor``)
``[tick:watchdog]``    the background-process watchdog
``[tick:job:<id>]``    a job declared under ``persistent_crons``
=====================  =====================================================

**Recognition is positive evidence only.** A prompt with no well-formed
sentinel is the human. That keeps the failure direction where Plan 00388
requires it: a tick the daemon fails to recognise clears the
``[awaiting-human]`` marker and costs a turn, which is today's behaviour; a
human misread as a tick would withdraw the safety net, which is worse.

The residual gap is a cron whose prompt the daemon never supplied -- one an
agent composed itself, a ``/loop`` or a ``ScheduleWakeup``. Those still read as
the human.

The sentinel is one bracketed token with no spaces, so an agent that re-flows
the prompt (measured: ``cron_enforcement`` constraint 4) cannot split it, and
matching is a substring search rather than a first-line test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

TICK_SENTINEL_PREFIX: Final[str] = "[tick:"
_SENTINEL_SUFFIX: Final[str] = "]"
_JOB_SEPARATOR: Final[str] = ":"


class TickKind(StrEnum):
    """Which daemon-supplied cron a tick came from."""

    FAILSAFE = "failsafe"
    WATCHDOG = "watchdog"
    DECLARED = "job"


@dataclass(frozen=True)
class DaemonTick:
    """A recognised tick: its kind, plus the job id for a declared cron."""

    kind: TickKind
    job_id: str | None = None


#: A job id is anything up to the closing bracket that is not whitespace --
#: a declared id containing either therefore produces a sentinel that does not
#: parse, and its ticks read as the human (the safe direction).
_SENTINEL_RE: Final[re.Pattern[str]] = re.compile(
    re.escape(TICK_SENTINEL_PREFIX)
    + rf"(?:(?P<fixed>{TickKind.FAILSAFE}|{TickKind.WATCHDOG})"
    + rf"|{TickKind.DECLARED}{_JOB_SEPARATOR}(?P<job>[^\]\s]+))"
    + re.escape(_SENTINEL_SUFFIX)
)


def tick_sentinel(kind: TickKind, job_id: str | None = None) -> str:
    """The sentinel token for ``kind``.

    Raises:
        ValueError: a declared job without an id, or a fixed kind given one.
    """
    if kind is TickKind.DECLARED:
        if not job_id:
            raise ValueError("a declared-cron sentinel needs its job id")
        return f"{TICK_SENTINEL_PREFIX}{kind}{_JOB_SEPARATOR}{job_id}{_SENTINEL_SUFFIX}"
    if job_id is not None:
        raise ValueError(f"a {kind} sentinel takes no job id")
    return f"{TICK_SENTINEL_PREFIX}{kind}{_SENTINEL_SUFFIX}"


def classify_tick(prompt: object) -> DaemonTick | None:
    """The daemon cron this prompt came from, or ``None`` for the human.

    The failsafe sentinel wins over any other in the same prompt: a project
    may declare the failsafe cron under ``persistent_crons``, and its ticks
    must keep the failsafe's own cadence rules rather than a declared job's.
    """
    if not isinstance(prompt, str):
        return None
    ticks: list[DaemonTick] = []
    for match in _SENTINEL_RE.finditer(prompt):
        fixed = match.group("fixed")
        if fixed is not None:
            ticks.append(DaemonTick(TickKind(fixed)))
        else:
            ticks.append(DaemonTick(TickKind.DECLARED, match.group("job")))
    failsafe = DaemonTick(TickKind.FAILSAFE)
    if failsafe in ticks:
        return failsafe
    return ticks[0] if ticks else None


def is_daemon_tick(prompt: object) -> bool:
    """Whether ``prompt`` carries any well-formed daemon tick sentinel."""
    return classify_tick(prompt) is not None


def with_tick_sentinel(prompt: str, sentinel: str) -> str:
    """``prompt`` with ``sentinel`` as its first line, unless it has one.

    A prompt already carrying a sentinel keeps it alone: one cron has one
    identity, and a declared failsafe job must stay the failsafe.
    """
    if is_daemon_tick(prompt):
        return prompt
    return f"{sentinel}\n{prompt}"


def strip_tick_sentinels(prompt: str) -> str:
    """``prompt`` with every sentinel token removed and the words kept.

    Used where two copies of one prompt are compared, so a cron created before
    the sentinel existed still matches its declaration.
    """
    return _SENTINEL_RE.sub("", prompt)
