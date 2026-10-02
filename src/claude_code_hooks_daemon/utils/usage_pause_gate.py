"""Shared logic of the usage pause (Plan 00479 Phase 4).

A session on a host with a usage ceiling PAUSES when a usage window reaches it:
every cron is replaced by ONE one-shot resume cron at the window's reset, the
session stops, and nothing wakes it until that cron fires. A hook cannot create
or delete a cron (``CronCreate``/``CronDelete`` are model tools), so the daemon
DIRECTS the model and then verifies what it did.

Every part of that protocol reads the same few facts, so they live here once:

- which windows are over the ceiling and when the pause ends
  (:func:`find_breaches`, :func:`build_pause`, :func:`resume_at_for`);
- the exact one-shot cron expression for that instant
  (:func:`resume_schedule`);
- whether a session is paused (:func:`is_usage_paused`) -- the ONE predicate
  every continuation-forcing or cron-re-arming handler stands down on;
- the directive text each stage delivers.

**One predicate, the usage record, not ``cron_pause``.** ``utils.cron_pause``
is a CLI-set, 24-hour, per-declared-job exemption read inside the cron
enforcers. A usage pause is the opposite shape: written by the daemon, one per
SESSION rather than per job, ending at a window reset rather than after a fixed
TTL, and read by the supervisor as well (``utils.usage_pause``). Making the
gates read ``cron_pause`` would force a synthetic job id per declared job and a
TTL that is wrong by construction, and would leave the supervisor needing a
second record anyway. The pause record already exists (Task 4.5), so it is the
single source of truth and ``cron_pause`` is untouched.

**Fail open.** No project context, no record, an unreadable record, a different
session: not paused. The record's own validity rule (``UsagePause.is_live``)
bounds a stale record to ``resume_at`` plus a grace.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import Config, PersistentCronConfig
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.utils.cron_enforcement import declared_tick_prompt
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.cron_tick import TickKind, classify_tick, tick_sentinel
from claude_code_hooks_daemon.utils.host_usage_ceiling import (
    HostUsageCeiling,
    resolve_host_usage_ceiling,
)
from claude_code_hooks_daemon.utils.usage_pause import (
    WINDOW_FIVE_HOUR,
    WINDOW_SEVEN_DAY,
    UsagePause,
    read_usage_pause,
)

logger = logging.getLogger(__name__)

#: Added to the latest reset so the resume cron fires after the window has
#: actually rolled over, not on the boundary where the snapshot may still read
#: the old window.
RESUME_MARGIN_SECONDS: Final[float] = 120.0

#: The only tools a paused session may use: just enough to replace its crons.
PAUSE_ALLOWED_TOOLS: Final[frozenset[str]] = frozenset(
    {ToolName.CRON_LIST, ToolName.CRON_DELETE, ToolName.CRON_CREATE}
)

_SECONDS_PER_MINUTE: Final[int] = 60

#: The one-shot resume cron's prompt. Its first line is the daemon tick
#: sentinel, which is how the gate tells this tick from the owner.
USAGE_RESUME_PROMPT: Final[str] = (
    f"{tick_sentinel(TickKind.USAGE_RESUME)}\n"
    "USAGE PAUSE RESUME CHECK: the subscription usage window this session paused on "
    "should have reset. The daemon re-reads usage and tells you whether to resume "
    "or to schedule another resume cron."
)

_FAILSAFE_SCHEDULE_HINT: Final[str] = "47 * * * *"


@dataclass(frozen=True)
class UsageBreach:
    """One usage window at or above its ceiling."""

    window: str
    used_percentage: float
    ceiling: float
    resets_at: int


@dataclass(frozen=True)
class ResumeSchedule:
    """The resume instant, as the cron to create and as text for a human.

    ``cron`` is the 5-field one-shot expression in LOCAL time (the zone
    ``CronCreate`` interprets expressions in); ``local_text`` and ``utc_text``
    name the same instant so the model can check what ``CronCreate`` reports.
    """

    cron: str
    local_text: str
    utc_text: str
    hhmm: str


def find_breaches(snapshot: UsageSnapshot | None, ceiling: HostUsageCeiling) -> list[UsageBreach]:
    """The live windows at or above their ceiling.

    A window with no ceiling, an absent window or no snapshot never breaches
    (Task 4.7: missing data never pauses a session).
    """
    if snapshot is None:
        return []
    candidates: tuple[tuple[str, UsageWindow | None, float | None], ...] = (
        (WINDOW_FIVE_HOUR, snapshot.five_hour, ceiling.five_hour),
        (WINDOW_SEVEN_DAY, snapshot.seven_day, ceiling.seven_day),
    )
    return [
        UsageBreach(name, window.used_percentage, limit, window.resets_at)
        for name, window, limit in candidates
        if window is not None and limit is not None and window.used_percentage >= limit
    ]


def session_ceiling(config: Config, hook_input: Mapping[str, Any]) -> HostUsageCeiling:
    """The usage ceiling for the session's effective hostname (Plan 00470 Task 6.1)."""
    return resolve_host_usage_ceiling(config.hosts, effective_hostname(hook_input))


def _latest_breach(breaches: Sequence[UsageBreach]) -> UsageBreach:
    if not breaches:
        raise ValueError("a usage pause needs at least one breached window")
    return max(breaches, key=lambda breach: breach.resets_at)


def resume_at_for(breaches: Sequence[UsageBreach]) -> float:
    """When to resume: the latest ``resets_at`` among the breached windows plus the margin.

    Raises:
        ValueError: ``breaches`` is empty.
    """
    return _latest_breach(breaches).resets_at + RESUME_MARGIN_SECONDS


def _percent(value: float) -> str:
    """A percentage rounded DOWN, as the status line shows it, so 79.9 never reads as 80."""
    return f"{math.floor(value)}%"


def build_pause(session_id: str, breaches: Sequence[UsageBreach], *, now: float) -> UsagePause:
    """The pause record for ``breaches``.

    The record's window is the one that sets the resume time; the reason names
    every breached window.

    Raises:
        ValueError: ``breaches`` is empty.
    """
    deciding = _latest_breach(breaches)
    reason = "; ".join(
        f"{b.window} window at {_percent(b.used_percentage)} (ceiling {_percent(b.ceiling)})"
        for b in breaches
    )
    return UsagePause(
        session_id=session_id,
        paused_at=now,
        resume_at=resume_at_for(breaches),
        window=deciding.window,
        used_percentage=deciding.used_percentage,
        ceiling=deciding.ceiling,
        reason=reason,
    )


def resume_schedule(resume_at: float, *, tz: tzinfo | None = None) -> ResumeSchedule:
    """The one-shot cron for ``resume_at``, rounded UP to a whole minute.

    Args:
        resume_at: Epoch seconds.
        tz: Zone the cron is expressed in; None is the machine's local zone,
            which is what ``CronCreate`` reads.
    """
    minute = math.ceil(resume_at / _SECONDS_PER_MINUTE) * _SECONDS_PER_MINUTE
    utc = datetime.fromtimestamp(minute, UTC)
    local = utc.astimezone(tz)  # tz None: the machine's local zone
    zone_name = local.tzname() or "local"
    return ResumeSchedule(
        cron=f"{local.minute} {local.hour} {local.day} {local.month} *",
        local_text=f"{local:%Y-%m-%d %H:%M} {zone_name}",
        utc_text=f"{utc:%Y-%m-%d %H:%M} UTC",
        hhmm=f"{local:%H:%M}",
    )


def is_resume_tick(hook_input: Mapping[str, Any]) -> bool:
    """Whether this prompt is the usage pause's own resume cron firing."""
    tick = classify_tick(hook_input.get(HookInputField.PROMPT))
    return tick is not None and tick.kind is TickKind.USAGE_RESUME


def tool_allowed_while_paused(tool_name: object) -> bool:
    """Whether a paused session may use ``tool_name``."""
    return isinstance(tool_name, str) and tool_name in PAUSE_ALLOWED_TOOLS


def untracked_dir() -> Path | None:
    """The daemon's untracked directory, or None when there is no project context."""
    try:
        return ProjectContext.daemon_untracked_dir()
    except RuntimeError as exc:
        logger.debug("usage_pause_gate: no project context, so no usage pause: %s", exc)
        return None


def active_usage_pause(session_id: str, *, now: float | None = None) -> UsagePause | None:
    """The live usage pause for ``session_id``, or None. Fails open."""
    if not session_id:
        return None
    directory = untracked_dir()
    if directory is None:
        return None
    return read_usage_pause(directory, session_id, now=time.time() if now is None else now)


def is_usage_paused(session_id: str, *, now: float | None = None) -> bool:
    """Whether ``session_id`` is paused on its usage ceiling.

    THE predicate: every handler that forces continuation or re-arms a cron
    stands down on this one answer.
    """
    return active_usage_pause(session_id, now=now) is not None


def hook_is_usage_paused(hook_input: Mapping[str, Any], *, now: float | None = None) -> bool:
    """:func:`is_usage_paused` for the session a hook payload belongs to."""
    return is_usage_paused(str(hook_input.get(HookInputField.SESSION_ID) or ""), now=now)


def _steps(schedule: ResumeSchedule) -> list[str]:
    """The cron steps every pause directive ends with."""
    return [
        "  1. CronList - list every cron in this session.",
        "  2. CronDelete EVERY cron listed: the failsafe recovery cron, every "
        "persistent_crons job, the watchdog, anything else. They are re-established "
        "when the pause lifts, so deleting them is correct.",
        f"  3. CronCreate ONE cron: schedule `{schedule.cron}` (local time; "
        f"{schedule.local_text}, which is {schedule.utc_text}), recurring: false, "
        "durable: false, with this exact prompt, first line included:",
        *(f"       {line}" for line in USAGE_RESUME_PROMPT.splitlines()),
        f"     Check that CronCreate reports a next run of {schedule.local_text}.",
        f"  4. Stop with `STOPPING BECAUSE: usage paused until {schedule.hhmm}`. The "
        "stop is accepted once exactly that one cron remains.",
    ]


def _describe(pause: UsagePause) -> str:
    return (
        f"{pause.window} window at {_percent(pause.used_percentage)} "
        f"(ceiling {_percent(pause.ceiling)})"
    )


def render_pause_directive(pause: UsagePause, *, tz: tzinfo | None = None) -> str:
    """The directive delivered when a session first crosses its ceiling."""
    schedule = resume_schedule(pause.resume_at, tz=tz)
    lines = [
        f"USAGE CEILING REACHED - this session is PAUSED until {schedule.local_text} "
        f"({schedule.utc_text}).",
        "",
        f"Usage: {pause.reason}. This host stops taking on work at its ceiling so the "
        "account is not driven into its hard limit; the window resets, and a single "
        "resume cron brings the session back then.",
        "",
        "Do NOT act on the request that arrived with this message (a prompt, a cron "
        "tick or a supervisor message): it is refused for now. Every tool except "
        "CronList, CronDelete and CronCreate is denied until the pause ends. Do "
        "exactly this and nothing else:",
        "",
        *_steps(schedule),
    ]
    return "\n".join(lines)


def render_stop_directive(pause: UsagePause, *, found: int, tz: tzinfo | None = None) -> str:
    """The Stop-block reason while the session's crons are not yet exactly the resume cron."""
    schedule = resume_schedule(pause.resume_at, tz=tz)
    noun = "cron" if found == 1 else "crons"
    lines = [
        f"USAGE PAUSE NOT COMPLETE - session_crons holds {found} {noun}, and a paused "
        "session may stop only when exactly ONE cron remains: the resume cron.",
        "",
        f"Paused on: {_describe(pause)}, until {schedule.local_text} ({schedule.utc_text}).",
        "",
        "Do exactly this and nothing else:",
        "",
        *_steps(schedule),
    ]
    return "\n".join(lines)


def render_still_over_directive(pause: UsagePause, *, tz: tzinfo | None = None) -> str:
    """The directive when the resume cron fired but usage is STILL over the ceiling."""
    schedule = resume_schedule(pause.resume_at, tz=tz)
    lines = [
        f"USAGE STILL OVER THE CEILING - {_describe(pause)}. The session stays PAUSED, "
        f"until {schedule.local_text} ({schedule.utc_text}).",
        "",
        "Do NOT resume work. Every tool except CronList, CronDelete and CronCreate is "
        "denied. Do exactly this and nothing else:",
        "",
        *_steps(schedule),
    ]
    return "\n".join(lines)


def render_resume_lifted_directive(
    *,
    jobs: Sequence[PersistentCronConfig] = (),
    failsafe_prompt: str | None = None,
) -> str:
    """The directive when usage is back under the ceiling: re-establish crons, continue.

    Args:
        jobs: The ``persistent_crons`` jobs declared for this host.
        failsafe_prompt: The canonical failsafe cron prompt when this session
            should have a failsafe cron that no declared job already supplies.
    """
    lines = [
        "USAGE PAUSE LIFTED - usage is back under the ceiling and the session may " "work again.",
        "",
        "1. CronList. The one-shot resume cron has fired; CronDelete it if it is " "still listed.",
        "2. Re-establish this session's crons, creating only those not already "
        "listed (a duplicate fires twice):",
    ]
    if failsafe_prompt is not None:
        lines += [
            f"   - failsafe recovery cron: CronCreate recurring: true, durable: false, "
            f"on an off-:00 minute (e.g. `{_FAILSAFE_SCHEDULE_HINT}`), prompt verbatim, "
            "first line included:",
            *(f"       {line}" for line in failsafe_prompt.splitlines()),
        ]
    for job in jobs:
        lines += [
            f"   - declared job `{job.id}`: CronCreate recurring: true, schedule "
            f"`{job.schedule}`, prompt verbatim, first line included:",
            *(f"       {line}" for line in declared_tick_prompt(job).splitlines()),
        ]
    if failsafe_prompt is None and not jobs:
        lines.append("   - none are declared for this host, so there is nothing to create.")
    lines += [
        "3. Then continue the active work where it stopped; the pause is over.",
    ]
    return "\n".join(lines)
