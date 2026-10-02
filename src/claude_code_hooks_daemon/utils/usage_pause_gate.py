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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, PersistentCronConfig
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core.data_layer import latest_usage
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.utils.config_cache import load_config_cached
from claude_code_hooks_daemon.utils.cron_enforcement import (
    FAILSAFE_CRON_SCHEDULE_HINT,
    declared_tick_prompt,
)
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
    clear_usage_pause,
    read_usage_pause,
    usage_override_active,
    write_usage_pause,
)

logger = logging.getLogger(__name__)

#: Added to the latest reset so the resume cron fires after the window has
#: actually rolled over, not on the boundary where the snapshot may still read
#: the old window.
RESUME_MARGIN_SECONDS: Final[float] = 120.0

#: How long after the resume time the single remaining cron may fire and still be
#: accepted by the Stop gate. Anything later is a cron that will not wake the session.
MAX_FIRE_AFTER_RESUME_SECONDS: Final[float] = 86400.0

#: The only tools a paused session may use: just enough to replace its crons.
#: ToolSearch is among them because the cron tools are deferred (their schemas
#: load only through it, ``constants/tools.py``).
PAUSE_ALLOWED_TOOLS: Final[frozenset[str]] = frozenset(
    {ToolName.CRON_LIST, ToolName.CRON_DELETE, ToolName.CRON_CREATE, ToolName.TOOL_SEARCH}
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

_PINNED_CRON_FIELDS: Final[int] = 5
_SECONDS_PER_DAY: Final[float] = 86400.0


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

    ``cron`` is the 5-field one-shot expression in the zone ``zone_text`` names
    (UTC unless a caller passes another: the vendored Claude Code docs do not say
    which zone ``CronCreate`` reads); ``local_text`` and ``utc_text`` name the same
    instant so the model can check what ``CronCreate`` reports.
    """

    cron: str
    local_text: str
    utc_text: str
    hhmm: str
    zone_text: str


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
        # Never in the past: a reset seconds away resumes a margin from now, so the
        # pinned cron minute is still ahead when the model creates it.
        resume_at=max(resume_at_for(breaches), now + RESUME_MARGIN_SECONDS),
        window=deciding.window,
        used_percentage=deciding.used_percentage,
        ceiling=deciding.ceiling,
        reason=reason,
    )


def refresh_resume(pause: UsagePause, *, now: float) -> UsagePause:
    """``pause`` with a resume time at least a margin from ``now``; ``pause`` itself if already so.

    A pause whose resume time has come or gone (the model was slow, or a resume
    tick found usage still over) would have its cron pinned to a minute that has
    passed, which next matches a year later.
    """
    floor = now + RESUME_MARGIN_SECONDS
    if pause.resume_at >= floor:
        return pause
    return replace(pause, resume_at=floor)


def resume_schedule(resume_at: float, *, tz: tzinfo = UTC) -> ResumeSchedule:
    """The one-shot cron for ``resume_at``, rounded UP to a whole minute.

    Args:
        resume_at: Epoch seconds.
        tz: Zone the cron is expressed in. UTC by default: nothing the project
            vendors says which zone ``CronCreate`` reads, so no machine zone is
            assumed.
    """
    minute = math.ceil(resume_at / _SECONDS_PER_MINUTE) * _SECONDS_PER_MINUTE
    utc = datetime.fromtimestamp(minute, UTC)
    local = utc.astimezone(tz)
    zone_name = local.tzname() or "local"
    offset = f"{local:%z}"  # +HHMM
    return ResumeSchedule(
        cron=f"{local.minute} {local.hour} {local.day} {local.month} *",
        local_text=f"{local:%Y-%m-%d %H:%M} {zone_name}",
        utc_text=f"{utc:%Y-%m-%d %H:%M} UTC",
        hhmm=f"{local:%H:%M}",
        zone_text=f"{zone_name}, UTC{offset[:3]}:{offset[3:]}",
    )


def _pinned_fire_time(cron: str, *, now: float, tz: tzinfo) -> float | None:
    """The next instant after ``now`` a pinned ``m h dom mon *`` cron fires, or None.

    Only the one-shot shape :func:`resume_schedule` builds is understood: four
    integers and a ``*`` for the weekday. Anything else, and any impossible date,
    is None, which the caller treats as "cannot be verified".
    """
    fields = cron.split()
    if len(fields) != _PINNED_CRON_FIELDS or fields[4] != "*":
        return None
    try:
        minute, hour, day, month = (int(field) for field in fields[:4])
    except ValueError:
        return None
    current = datetime.fromtimestamp(now, UTC).astimezone(tz)
    for year in (current.year, current.year + 1):
        try:
            wall = datetime(year, month, day, hour, minute)
        except ValueError:
            return None
        candidate = wall.replace(tzinfo=tz).timestamp()
        if candidate > now:
            return candidate
    return None


def schedule_fires_in_window(cron: str, *, now: float, resume_at: float, tz: tzinfo = UTC) -> bool:
    """Whether ``cron`` next fires in ``(now, resume_at + MAX_FIRE_AFTER_RESUME_SECONDS]``.

    The Stop gate's check that the one remaining cron will actually wake the
    session: a pinned minute that has passed next matches a year later, and a
    time-zone mismatch lands it hours away.
    """
    fire = _pinned_fire_time(cron, now=now, tz=tz)
    return fire is not None and now < fire <= resume_at + MAX_FIRE_AFTER_RESUME_SECONDS


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
    """The live usage pause for ``session_id``, or None.

    TOTAL: any ``OSError``/``ValueError``/``RuntimeError`` reading the record is "not
    paused", with a warning. A pause only ever restricts, so a broken record must
    never deny a tool, trap a Stop or silence a safety handler (the chain turns an
    exception from a SAFETY handler into a DENY).
    """
    if not session_id:
        return None
    try:
        directory = untracked_dir()
        if directory is None:
            return None
        return read_usage_pause(directory, session_id, now=time.time() if now is None else now)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning(
            "usage_pause_gate: cannot read the pause record, treating as no pause: %s", exc
        )
        return None


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
        "  0. The cron tools are deferred: if their schemas are not loaded, load them "
        "with ToolSearch (query `select:CronList,CronDelete,CronCreate`) first.",
        "  1. CronList - list every cron in this session.",
        "  2. CronDelete EVERY cron listed: the failsafe recovery cron, every "
        "persistent_crons job, the watchdog, anything else. They are re-established "
        "when the pause lifts, so deleting them is correct.",
        f"  3. CronCreate ONE cron: schedule `{schedule.cron}`, recurring: false, "
        "durable: false, with this exact prompt, first line included:",
        *(f"       {line}" for line in USAGE_RESUME_PROMPT.splitlines()),
        f"     That expression is in {schedule.zone_text} and means {schedule.local_text}. "
        "The Claude Code documentation does not say which time zone CronCreate reads an "
        "expression in, so use it exactly as written; do not convert it and do not run any "
        "other tool to check the clock (every tool but the cron tools is denied). The "
        "cron is pinned to one calendar minute: the stop is refused if it will not fire "
        "within a day after the resume time.",
        f"  4. Stop with `STOPPING BECAUSE: usage paused until {schedule.hhmm}`. The "
        "stop is accepted once exactly that one cron remains.",
    ]


def _describe(pause: UsagePause) -> str:
    return (
        f"{pause.window} window at {_percent(pause.used_percentage)} "
        f"(ceiling {_percent(pause.ceiling)})"
    )


def render_pause_directive(pause: UsagePause, *, tz: tzinfo = UTC) -> str:
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
        "CronList, CronDelete, CronCreate and ToolSearch is denied until the pause ends. "
        "Do exactly this and nothing else:",
        "",
        *_steps(schedule),
    ]
    return "\n".join(lines)


def render_stop_directive(
    pause: UsagePause, *, found: int, tz: tzinfo = UTC, problem: str | None = None
) -> str:
    """The Stop-block reason while the session's crons are not yet exactly the resume cron.

    Args:
        pause: The live pause.
        found: How many crons ``session_crons`` holds.
        tz: Zone the cron is expressed in.
        problem: Why a single resume cron was still refused (its schedule), if so.
    """
    schedule = resume_schedule(pause.resume_at, tz=tz)
    noun = "cron" if found == 1 else "crons"
    lines = [
        f"USAGE PAUSE NOT COMPLETE - session_crons holds {found} {noun}, and a paused "
        "session may stop only when exactly ONE cron remains: the resume cron.",
        *([problem] if problem else []),
        "",
        f"Paused on: {_describe(pause)}, until {schedule.local_text} ({schedule.utc_text}).",
        "",
        "Do exactly this and nothing else:",
        "",
        *_steps(schedule),
    ]
    return "\n".join(lines)


def render_still_over_directive(pause: UsagePause, *, tz: tzinfo = UTC) -> str:
    """The directive when the resume cron fired but usage is STILL over the ceiling."""
    schedule = resume_schedule(pause.resume_at, tz=tz)
    lines = [
        f"USAGE STILL OVER THE CEILING - {_describe(pause)}. The session stays PAUSED, "
        f"until {schedule.local_text} ({schedule.utc_text}).",
        "",
        "Do NOT resume work. Every tool except CronList, CronDelete, CronCreate and "
        "ToolSearch is denied. Do exactly this and nothing else:",
        "",
        *_steps(schedule),
    ]
    return "\n".join(lines)


def render_resume_lifted_directive(
    *,
    jobs: Sequence[PersistentCronConfig] = (),
    failsafe_prompt: str | None = None,
    verified_under_ceiling: bool = True,
) -> str:
    """The directive when the pause ends: re-establish crons, continue.

    Args:
        jobs: The ``persistent_crons`` jobs declared for this host.
        failsafe_prompt: The canonical failsafe cron prompt when this session
            should have a failsafe cron that no declared job already supplies.
        verified_under_ceiling: Whether a fresh usage read showed every window under
            the ceiling. False when the pause ended for another reason (the owner's
            override, a pause that could not be kept): the text then says usage was
            NOT confirmed, since claiming it is back under would be a statement
            nothing checked.
    """
    headline = (
        "USAGE PAUSE LIFTED - usage is back under the ceiling and the session may work again."
        if verified_under_ceiling
        else "USAGE PAUSE ENDED - usage was NOT confirmed back under the ceiling (the owner "
        "overrode the pause, or it could not be renewed). Work again, but expect to be "
        "paused again if usage is still over it."
    )
    lines = [
        headline,
        "",
        "1. CronList (load it with ToolSearch if its schema is not loaded). The one-shot "
        "resume cron has fired; CronDelete it if it is still listed.",
        "2. Re-establish this session's crons, creating only those not already "
        "listed (a duplicate fires twice):",
    ]
    if failsafe_prompt is not None:
        lines += [
            f"   - failsafe recovery cron: CronCreate recurring: true, durable: false, "
            f"on an off-:00 minute (e.g. `{FAILSAFE_CRON_SCHEDULE_HINT}`), prompt verbatim, "
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


def render_lift_not_recorded_note(*, expires_at: float, tz: tzinfo = UTC) -> str:
    """Told instead of "lifted" when the record could not be removed.

    The tool and stop gates still read the record, so claiming a lift would send
    the model into tools that are about to be denied.
    """
    until = resume_schedule(expires_at, tz=tz).local_text
    return (
        "USAGE PAUSE: usage is back under the ceiling, but the pause record could NOT be "
        "removed, so the pause is NOT lifted yet: tools other than CronList, CronDelete, "
        f"CronCreate and ToolSearch stay denied until it expires ({until}) or a human runs "
        "`! bin/hooks-daemon usage-pause clear`. Do not start new work."
    )


# --- Entry: shared by the prompt, tool and stop gates ---------------------------------


def load_project_config() -> Config:
    """The project's daemon config; defaults (so no ceiling) when it cannot be loaded."""
    try:
        return load_config_cached(ProjectContext.project_root() / ".claude" / "hooks-daemon.yaml")
    except (RuntimeError, ValidationError, OSError, ValueError) as exc:
        logger.debug("usage_pause_gate: cannot load config, so no ceiling: %s", exc)
        return Config()


def default_usage_loader(now: float) -> UsageSnapshot | None:
    """The daemon's latest usage snapshot (in memory; the file only before any Status event)."""
    return latest_usage(now=now)


@dataclass
class PauseEnvironment:
    """The seams a gate reads the world through; tests substitute fakes.

    ``tz`` is the zone the resume cron's expression is written in: UTC, because the
    vendored Claude Code docs do not say which zone ``CronCreate`` reads.
    """

    clock: Callable[[], float] = time.time
    config_loader: Callable[[], Config] = load_project_config
    usage_loader: Callable[[float], UsageSnapshot | None] = default_usage_loader
    tz: tzinfo = UTC


def current_breaches(hook_input: Mapping[str, Any], env: PauseEnvironment) -> list[UsageBreach]:
    """The windows over this session's host ceiling right now, logging why when none.

    Every "no" is a debug line naming the reason (Task 4.7): no ceiling for the host,
    no snapshot, or below the ceiling. An ``OSError`` reading the snapshot is "no data".
    """
    now = env.clock()
    hostname = effective_hostname(hook_input)
    ceiling = session_ceiling(env.config_loader(), hook_input)
    if ceiling.five_hour is None and ceiling.seven_day is None:
        logger.debug("usage_pause_gate: no usage ceiling for host %r, not pausing", hostname)
        return []
    try:
        snapshot = env.usage_loader(now)
    except OSError as exc:
        logger.warning("usage_pause_gate: cannot read the usage snapshot, not pausing: %s", exc)
        return []
    if snapshot is None:
        logger.debug("usage_pause_gate: no usage snapshot (no rate_limits seen), not pausing")
        return []
    breaches = find_breaches(snapshot, ceiling)
    if not breaches:
        logger.debug("usage_pause_gate: usage below the ceiling for host %r", hostname)
    return breaches


def start_pause(
    session_id: str, breaches: Sequence[UsageBreach], env: PauseEnvironment
) -> UsagePause | None:
    """Record a pause for ``breaches``; None (no pause) when it must not or cannot be.

    Not entered for an empty session id, the owner's override
    (``usage-pause clear``), no project context, or a record that cannot be written
    AND read back identically: every other gate reads this record, so a directive
    without one could not be enforced, and a record this process can write but not
    read would be re-entered on every call (a deny/stop loop).
    """
    if not session_id or not breaches:
        return None
    now = env.clock()
    directory = untracked_dir()
    if directory is None:
        return None
    if usage_override_active(directory, session_id, now=now):
        logger.info("usage_pause_gate: the owner's override is active, not pausing")
        return None
    pause = build_pause(session_id, breaches, now=now)
    try:
        write_usage_pause(directory, pause)
    except (OSError, ValueError) as exc:
        logger.warning("usage_pause_gate: pause record not written, not pausing: %s", exc)
        return None
    if read_usage_pause(directory, session_id, now=now) != pause:
        logger.warning(
            "usage_pause_gate: the pause record could not be read back as written, not pausing"
        )
        try:
            clear_usage_pause(directory, session_id)
        except OSError as exc:
            logger.warning("usage_pause_gate: could not remove the unreadable record: %s", exc)
        return None
    logger.warning("usage_pause_gate: pausing session %s: %s", session_id, pause.reason)
    return pause


def renew_pause(pause: UsagePause, env: PauseEnvironment) -> UsagePause:
    """``pause`` with a resume time still ahead, persisted; unchanged if it already is.

    A record that cannot be rewritten keeps its old resume time (a warning says so):
    the gates then judge against the record that is actually on disk.
    """
    fresh = refresh_resume(pause, now=env.clock())
    if fresh is pause:
        return pause
    directory = untracked_dir()
    if directory is None:
        return pause
    try:
        write_usage_pause(directory, fresh)
    except (OSError, ValueError) as exc:
        logger.warning("usage_pause_gate: could not move the resume time forward: %s", exc)
        return pause
    return fresh


def try_start_pause(hook_input: Mapping[str, Any], env: PauseEnvironment) -> UsagePause | None:
    """Enter the pause if this session's host ceiling is reached; total, fails open."""
    session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
    if not session_id:
        return None
    try:
        return start_pause(session_id, current_breaches(hook_input, env), env)
    except Exception as exc:
        # Deliberately broad: this runs inside a SAFETY handler on every tool call, and
        # the chain turns any exception from one into a DENY of the call.
        logger.warning("usage_pause_gate: cannot evaluate the ceiling, not pausing: %s", exc)
        return None


def clear_pause(session_id: str) -> bool:
    """Remove the session's pause record; False when a record could not be removed."""
    directory = untracked_dir()
    if directory is None:
        return True
    try:
        clear_usage_pause(directory, session_id)
    except OSError as exc:
        logger.warning("usage_pause_gate: could not clear the pause record: %s", exc)
        return False
    return True
