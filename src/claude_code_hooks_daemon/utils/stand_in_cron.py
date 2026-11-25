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
from typing import Any, Final, cast

from claude_code_hooks_daemon.config.models import Config, handler_options
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.core.result_types import BlockingResult
from claude_code_hooks_daemon.utils.autonomy import autonomy_verdict, session_policy
from claude_code_hooks_daemon.utils.cron_enforcement import SessionCron, parse_session_crons
from claude_code_hooks_daemon.utils.cron_tick import (
    TickKind,
    classify_tick,
    tick_sentinel,
    with_tick_sentinel,
)
from claude_code_hooks_daemon.utils.session_modes import ModeLabel
from claude_code_hooks_daemon.utils.stop_hook_helpers import is_stop_hook_active

logger = logging.getLogger(__name__)

DEFAULT_STAND_IN_DELAY_HOURS: Final[float] = 3.0
#: The awaiting-human marker expires after 24 hours by default; a stand-in that
#: would fire at or after that would find no live marker and do nothing.
MAX_STAND_IN_DELAY_HOURS: Final[float] = 24.0
#: A backed-off delay stays below this, so the stand-in still fires inside the marker's day.
BACKOFF_CEILING_HOURS: Final[float] = 23.0
STAND_IN_SENTINEL: Final[str] = tick_sentinel(TickKind.STAND_IN)
#: ``auto_continue_stop``'s option holding the stand-in delay in hours.
STAND_IN_DELAY_OPTION: Final[str] = "stand_in_delay_hours"
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
    "ruling, never as the owner's. A later real owner message can overturn it.\n"
    "- A repeat decline with the question unchanged since the last journalled one "
    "gets NO new journal entry; a ruling that changes anything is always journalled."
)


def stand_in_prompt() -> str:
    """The prompt the stand-in cron carries, led by its ``[tick:stand-in]`` sentinel."""
    return with_tick_sentinel(_PROMPT_BODY, STAND_IN_SENTINEL)


def delay_hours_problem(value: object) -> str | None:
    """Why ``value`` is not a usable stand-in delay in hours, or ``None`` when it is.

    A bool or a numeric string is refused: it is a config typo, and this runs at
    config load where a failure is reported rather than silent.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not 0 < value < MAX_STAND_IN_DELAY_HOURS
    ):
        return (
            f"stand_in_delay_hours must be a number above 0 and below "
            f"{MAX_STAND_IN_DELAY_HOURS:g} (the marker's expiry), got {value!r}"
        )
    return None


def validate_delay_hours(value: object) -> float:
    """``value`` as the stand-in delay in hours.

    Raises:
        ValueError: with :func:`delay_hours_problem`'s message when ``value`` is
            not a real number above 0 and below ``MAX_STAND_IN_DELAY_HOURS``.
    """
    problem = delay_hours_problem(value)
    if problem is not None:
        raise ValueError(problem)
    return float(cast("float", value))


def backed_off_delay_hours(
    delay_hours: float, *, previous_entered_at: float | None, now: float
) -> float:
    """The delay for a stand-in, longer when this stop repeats one nobody answered.

    ``previous_entered_at`` is when the still-live awaiting-human entry of the
    session was made (``None`` when the session is not awaiting a human). Each
    stop replaces that entry, so ``now - previous_entered_at`` is the gap since
    the last stop that no human message ended; waiting twice that gap doubles the
    cadence each round (3h, 6h, 12h) up to ``BACKOFF_CEILING_HOURS``. A human
    message ends the entry, so the next stop starts again at ``delay_hours``.
    """
    if previous_entered_at is None or previous_entered_at >= now:
        return delay_hours
    gap_hours = (now - previous_entered_at) / _SECONDS_PER_HOUR
    return min(max(delay_hours, round(2 * gap_hours, 1)), max(delay_hours, BACKOFF_CEILING_HOURS))


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


def configured_delay_hours(config: Config) -> float:
    """``auto_continue_stop``'s ``stand_in_delay_hours`` from ``config``; the default when invalid.

    An invalid value is reported at session start by the handler's
    ``validate_options``, so here it simply falls back like the handler does.
    """
    options = handler_options(config.handlers.stop.get(HandlerID.AUTO_CONTINUE_STOP.config_key))
    value = options.get(STAND_IN_DELAY_OPTION, DEFAULT_STAND_IN_DELAY_HOURS)
    if delay_hours_problem(value) is not None:
        return DEFAULT_STAND_IN_DELAY_HOURS
    return float(value)


def previous_awaiting_human_entered_at(hook_input: dict[str, Any]) -> float | None:
    """When the session's still-live awaiting-human entry was made, or ``None``.

    A caller that goes on to write THIS stop's entry must read this first: the
    write replaces the entry, so afterwards the registry holds only this stop.
    """
    try:
        entries = session_policy(hook_input).entries
    except (RuntimeError, OSError) as exc:
        # Best-effort like the marker write itself: no registry means no backoff, never a failed stop.
        logger.debug("stand-in backoff: cannot read the session's modes: %s", exc)
        return None
    for entry in entries:
        if entry.label is ModeLabel.AWAITING_HUMAN:
            return entry.entered_at
    return None


def stand_in_requirement(
    hook_input: dict[str, Any],
    *,
    config: Config,
    delay_hours: float,
    previous_entered_at: float | None,
    now: float | None = None,
) -> BlockingResult | None:
    """The stand-in deny an ``[awaiting-human]`` stop owes, or ``None`` when none is owed.

    ``previous_entered_at`` is :func:`previous_awaiting_human_entered_at` as read
    BEFORE this stop wrote its own entry; it lengthens the delay for a repeat stop.

    The ONE gate both ``auto_continue_stop`` and ``owner_wait_stop_guard`` use, so the
    guard's earlier deny can carry the requirement the chain would otherwise hide
    (Plan 00636 F1). Silent where autonomy is off for this environment or session
    is focused (Plan 00498), and unless ``persistent_crons.enabled``; a BLOCKED mode
    does not silence it, because this stop enters awaiting-human (Plan 00501).
    """
    autonomy = autonomy_verdict(hook_input)
    if not autonomy.environment_allowed or autonomy.session.focus_task is not None:
        return None
    if not config.persistent_crons.enabled:
        return None
    when = time.time() if now is None else now
    delay = backed_off_delay_hours(delay_hours, previous_entered_at=previous_entered_at, now=when)
    return stand_in_verdict(hook_input, delay_hours=delay, now=when)
