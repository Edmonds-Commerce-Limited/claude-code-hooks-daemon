"""The timed stand-in for an ``[awaiting-human]`` stop (Plan 00470 Task 5.2).

A session that declares it is blocked only on the human halts everything until
the human answers. So the main-thread stop that declares it must also leave a
ONE-OFF cron about three hours out. If the marker is still live when it fires,
the session dispatches a Fable sub-agent that chooses among the options the
agent laid out, records the choice as the stand-in's ruling, and carries on.

``auto_continue_stop`` is the only place that knows the stop declared
``[awaiting-human]`` (``cron_stop_enforcer`` runs before it, so the marker does
not exist yet at that point), so it asks :func:`stand_in_verdict` for the block,
exactly as ``cron_stop_enforcer`` blocks on a missing declared cron: the verdict
is read from the payload's ``session_crons``, an absent field is "no
information" and allows, and a re-entering stop is never blocked twice.

The cron is recognised by ``[tick:stand-in]`` (``cron_tick.TickKind.STAND_IN``).
Because that is not a declared job's tick, the suppressor lets it through while
the marker is live, which is the one moment it is meant to fire.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Final

from claude_code_hooks_daemon.core.result_types import BlockingResult
from claude_code_hooks_daemon.utils.cron_enforcement import SessionCron, parse_session_crons
from claude_code_hooks_daemon.utils.cron_tick import (
    TickKind,
    classify_tick,
    tick_sentinel,
    with_tick_sentinel,
)
from claude_code_hooks_daemon.utils.stop_hook_helpers import is_stop_hook_active

logger = logging.getLogger(__name__)

DEFAULT_STAND_IN_DELAY_HOURS: Final[float] = 3.0
#: The awaiting-human marker expires after 24 hours by default; a stand-in that
#: would fire at or after that would find no live marker and do nothing.
MAX_STAND_IN_DELAY_HOURS: Final[float] = 24.0
STAND_IN_SENTINEL: Final[str] = tick_sentinel(TickKind.STAND_IN)
_SECONDS_PER_HOUR: Final[int] = 3600

_PROMPT_BODY: Final[str] = (
    "**AWAITING-HUMAN STAND-IN (automated one-off, NOT the owner).**\n"
    "If a real owner message has arrived since your `[awaiting-human]` stop, this tick "
    "is a no-op.\n"
    "Otherwise dispatch ONE sub-agent with `model: fable` (id `claude-fable-5-1`) to "
    "read the pending question and the options you laid out in your last stop message "
    "and choose one; then carry on with it.\n"
    "Rules:\n"
    "- It may choose ONLY among engineering options. Reserved for a human, stay "
    "blocked: releases, force deletes, remote branch deletes, QA suppressions, history "
    "rewrites, upgrade approvals, anything a guard says to ask the user. If the "
    "question is one of those, record that the stand-in declined and stay blocked.\n"
    "- Record the choice or decline with `mkplan.bash --journal` as the stand-in's "
    "ruling, never as the owner's. A later real owner message can overturn it."
)


def stand_in_prompt() -> str:
    """The prompt the stand-in cron carries, led by its ``[tick:stand-in]`` sentinel."""
    return with_tick_sentinel(_PROMPT_BODY, STAND_IN_SENTINEL)


def validate_delay_hours(value: object) -> float:
    """``value`` as the stand-in delay in hours.

    Raises:
        ValueError: not a real number above 0 and below ``MAX_STAND_IN_DELAY_HOURS``.
            A bool or a numeric string is refused: it is a config typo, and this
            runs at config load where a failure is reported rather than silent.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not 0 < value < MAX_STAND_IN_DELAY_HOURS
    ):
        raise ValueError(
            f"stand_in_delay_hours must be a number above 0 and below "
            f"{MAX_STAND_IN_DELAY_HOURS:g} (the marker's expiry), got {value!r}"
        )
    return float(value)


def one_off_schedule(now: float, delay_hours: float) -> str:
    """A 5-field cron expression that fires once, ``delay_hours`` after ``now`` (local time)."""
    due = time.localtime(now + delay_hours * _SECONDS_PER_HOUR)
    return f"{due.tm_min} {due.tm_hour} {due.tm_mday} {due.tm_mon} *"


def has_stand_in_cron(session_crons: list[SessionCron]) -> bool:
    """Whether any live session cron is a stand-in (matched by sentinel, never by id)."""
    for cron in session_crons:
        tick = classify_tick(cron.prompt)
        if tick is not None and tick.kind is TickKind.STAND_IN:
            return True
    return False


def _render_reason(schedule: str, delay_hours: float) -> str:
    prompt_lines = "\n".join(f"      {line}" for line in stand_in_prompt().splitlines())
    return (
        "AWAITING-HUMAN STAND-IN MISSING -- this stop declared [awaiting-human], so the "
        f"session must also schedule a one-off stand-in about {delay_hours:g} hours out; "
        "otherwise one open question halts all work until the owner returns.\n\n"
        "Run CronCreate (recurring: false) with the schedule and prompt exactly as given:\n\n"
        f"    schedule (one-off, local time): {schedule}\n"
        "    prompt:\n"
        f"{prompt_lines}\n\n"
        "Once it is created, stop again. The stand-in only acts if the marker is still "
        "live when it fires, and it may choose only among engineering options."
    )


def stand_in_verdict(
    hook_input: dict[str, Any], *, delay_hours: float, now: float | None = None
) -> BlockingResult | None:
    """The Stop block for an ``[awaiting-human]`` stop with no stand-in, else ``None``.

    ``None`` means "do not block": a stand-in is already scheduled, ``session_crons``
    was not delivered (no information is never a gap), or this stop re-enters after
    an earlier block, so a session that cannot create the cron is never trapped.
    """
    session_crons = parse_session_crons(hook_input)
    if session_crons is None or has_stand_in_cron(session_crons):
        return None
    if is_stop_hook_active(hook_input):
        logger.warning("awaiting-human stand-in cron still missing on stop re-entry, allowing")
        return None
    when = time.time() if now is None else now
    return BlockingResult.deny(_render_reason(one_off_schedule(when, delay_hours), delay_hours))
