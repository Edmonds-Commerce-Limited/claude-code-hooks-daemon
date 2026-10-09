"""Shared logic of the usage pause (Plan 00479 Phase 4).

A session on a host with a usage ceiling PAUSES when a usage window reaches it:
every cron is replaced by ONE recurring resume cron (``RESUME_CRON_SCHEDULE``), the
session stops, and nothing wakes it but that cron. A hook cannot create or delete a
cron (``CronCreate``/``CronDelete`` are model tools), so the daemon DIRECTS the
model and then verifies what it did.

**The resume cron names no clock time**, so no host time zone can misplace it:
it fires every ten minutes, a tick before the pause's ``resume_at`` is dropped at
zero cost, and the first tick at or after it re-reads usage and lifts the pause.

Every part of that protocol reads the same few facts, so they live here once:

- which windows are over the ceiling and when the pause ends
  (:func:`find_breaches`, :func:`build_pause`, :func:`resume_at_for`);
- whether a resume tick is due (:func:`resume_is_due`) and whether a cron is the
  resume cron (:func:`is_resume_schedule`);
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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, PersistentCronConfig
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core.data_layer import latest_usage
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.cron_enforcement import (
    FAILSAFE_CRON_SCHEDULE_HINT,
    declared_tick_prompt,
)
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.cron_tick import TickKind, classify_tick, tick_sentinel
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
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

#: The resume cron's schedule: every ten minutes, the same expression in every time zone.
RESUME_CRON_SCHEDULE: Final[str] = "*/10 * * * *"

#: The only tools a paused session may use: just enough to replace its crons and to
#: wind up its subagents. ToolSearch is among them because the cron tools are deferred
#: (their schemas load only through it, ``constants/tools.py``). Neither dispatch tool
#: (``SUBAGENT_DISPATCH_TOOL_NAMES``) is: no new subagent starts while paused.
PAUSE_ALLOWED_TOOLS: Final[frozenset[str]] = frozenset(
    {
        ToolName.CRON_LIST,
        ToolName.CRON_DELETE,
        ToolName.CRON_CREATE,
        ToolName.TOOL_SEARCH,
        ToolName.SEND_MESSAGE,
        ToolName.TASK_STOP,
    }
)

#: The resume cron's prompt. Its first line is the daemon tick
#: sentinel, which is how the gate tells this tick from the owner.
USAGE_RESUME_PROMPT: Final[str] = (
    f"{tick_sentinel(TickKind.USAGE_RESUME)}\n"
    "USAGE PAUSE RESUME CHECK: the subscription usage window this session paused on "
    "should have reset. The daemon re-reads usage and tells you whether to resume "
    "or to stay paused."
)


@dataclass(frozen=True)
class UsageBreach:
    """One usage window at or above its ceiling."""

    window: str
    used_percentage: float
    ceiling: float
    resets_at: int


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


def resume_time_text(resume_at: float) -> str:
    """``resume_at`` as ``YYYY-MM-DD HH:MM UTC``, whatever the host's time zone."""
    return f"{datetime.fromtimestamp(resume_at, UTC):%Y-%m-%d %H:%M} UTC"


def is_resume_schedule(schedule: str) -> bool:
    """Whether ``schedule`` is :data:`RESUME_CRON_SCHEDULE` (whitespace aside)."""
    return schedule.split() == RESUME_CRON_SCHEDULE.split()


def resume_is_due(pause: UsagePause, *, now: float) -> bool:
    """Whether a resume tick at ``now`` may end (or re-check) the pause."""
    return now >= pause.resume_at


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
        log_and_continue(
            logger,
            exc,
            reason="without a project context there is nowhere to read or write a pause record (None), so no usage pause applies",
            level=logging.DEBUG,
        )
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
        log_and_continue(
            logger,
            exc,
            reason="an unreadable pause record is treated as no pause (None): this runs inside safety handlers on every call, and a record that cannot be read must not deny or stop the session",
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


_ALLOWED_TOOLS_TEXT: Final[str] = (
    "CronList, CronDelete, CronCreate, ToolSearch, SendMessage and TaskStop"
)

_WIND_UP_STEP: Final[str] = (
    "Subagents: do not start new subagents (starting one is refused). Let running "
    "subagents finish; you may SendMessage them to wrap up and report. Stop idle or "
    "finished teammates with TaskStop; do not stop one that is still working."
)


def _steps(pause: UsagePause, *, wind_up_subagents: bool = False) -> list[str]:
    """The numbered steps every pause directive ends with."""
    until = resume_time_text(pause.resume_at)
    steps = [
        "The cron tools are deferred: if their schemas are not loaded, load them "
        "with ToolSearch (query `select:CronList,CronDelete,CronCreate`) first.",
        "CronList - list every cron in this session.",
        "CronDelete EVERY cron listed: the failsafe recovery cron, every "
        "persistent_crons job, the watchdog, anything else. They are re-established "
        "when the pause lifts, so deleting them is correct.",
        f"CronCreate ONE cron: schedule `{RESUME_CRON_SCHEDULE}`, recurring: true, "
        "durable: false, with this exact prompt, first line included:\n"
        + "\n".join(f"       {line}" for line in USAGE_RESUME_PROMPT.splitlines())
        + "\n     It fires every ten minutes whatever the time zone; the daemon drops its "
        f"ticks until {until} at no cost, then re-reads usage and lifts the pause.",
    ]
    if wind_up_subagents:
        steps.append(_WIND_UP_STEP)
    steps.append(
        f"Stop with `STOPPING BECAUSE: usage paused until {until}`. "
        "The stop is accepted once exactly that one cron remains."
    )
    return [f"  {number}. {step}" for number, step in enumerate(steps)]


def _describe(pause: UsagePause) -> str:
    return (
        f"{pause.window} window at {_percent(pause.used_percentage)} "
        f"(ceiling {_percent(pause.ceiling)})"
    )


def render_pause_directive(pause: UsagePause) -> str:
    """The directive delivered when a session first crosses its ceiling."""
    lines = [
        f"USAGE CEILING REACHED - this session is PAUSED until "
        f"{resume_time_text(pause.resume_at)}.",
        "",
        f"Usage: {pause.reason}. This host stops taking on work at its ceiling so the "
        "account is not driven into its hard limit; the window resets, and a single "
        "resume cron brings the session back then.",
        "",
        "Do NOT act on the request that arrived with this message (a prompt, a cron "
        "tick or a supervisor message): it is refused for now. Every tool except "
        f"{_ALLOWED_TOOLS_TEXT} is denied until the pause ends. "
        "Do exactly this and nothing else:",
        "",
        *_steps(pause, wind_up_subagents=True),
    ]
    return "\n".join(lines)


def render_stop_directive(pause: UsagePause, *, found: int, problem: str | None = None) -> str:
    """The Stop-block reason while the session's crons are not yet exactly the resume cron.

    Args:
        pause: The live pause.
        found: How many crons ``session_crons`` holds.
        problem: Why a single resume cron was still refused (its schedule), if so.
    """
    noun = "cron" if found == 1 else "crons"
    lines = [
        f"USAGE PAUSE NOT COMPLETE - session_crons holds {found} {noun}, and a paused "
        "session may stop only when exactly ONE cron remains: the resume cron.",
        *([problem] if problem else []),
        "",
        f"Paused on: {_describe(pause)}, until {resume_time_text(pause.resume_at)}.",
        "",
        "Do exactly this and nothing else:",
        "",
        *_steps(pause),
    ]
    return "\n".join(lines)


def render_still_over_directive(pause: UsagePause) -> str:
    """The directive when the resume cron fired but usage is STILL over the ceiling."""
    until = resume_time_text(pause.resume_at)
    lines = [
        f"USAGE STILL OVER THE CEILING - {_describe(pause)}. The session stays PAUSED, "
        f"until {until}.",
        "",
        "Do NOT resume work. Do NOT create another cron: the recurring resume cron "
        f"(`{RESUME_CRON_SCHEDULE}`) is already in place, and the daemon drops its ticks "
        f"until {until} at no cost. Every tool except {_ALLOWED_TOOLS_TEXT} is denied. "
        f"Stop with `STOPPING BECAUSE: usage paused until {until}`; the stop is accepted "
        "while exactly that one cron remains.",
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
        "1. CronList (load it with ToolSearch if its schema is not loaded). The recurring "
        "resume cron (its prompt starts `[tick:usage-resume]`) still fires every ten "
        "minutes: CronDelete it now so it does not outlive the pause.",
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


def render_lift_not_recorded_note(*, expires_at: float) -> str:
    """Told instead of "lifted" when the record could not be removed.

    The tool and stop gates still read the record, so claiming a lift would send
    the model into tools that are about to be denied.
    """
    until = resume_time_text(expires_at)
    return (
        "USAGE PAUSE: usage is back under the ceiling, but the pause record could NOT be "
        f"removed, so the pause is NOT lifted yet: tools other than {_ALLOWED_TOOLS_TEXT} "
        f"stay denied until it expires ({until}) or a human runs "
        "`! bin/hooks-daemon usage-pause clear`. Do not start new work."
    )


# --- Entry: shared by the prompt, tool and stop gates ---------------------------------


def load_project_config() -> Config:
    """The project's daemon config; defaults (so no ceiling) when it cannot be loaded."""
    try:
        return load_config_cached(ProjectContext.project_root() / ".claude" / "hooks-daemon.yaml")
    except (RuntimeError, ValidationError, OSError, ValueError) as exc:
        logger.debug("usage_pause_gate: cannot load config, so no ceiling: %s", exc)
        return default_config()


def default_usage_loader(now: float) -> UsageSnapshot | None:
    """The daemon's latest usage snapshot (in memory; the file only before any Status event)."""
    return latest_usage(now=now)


@dataclass
class PauseEnvironment:
    """The seams a gate reads the world through; tests substitute fakes."""

    clock: Callable[[], float] = time.time
    config_loader: Callable[[], Config] = load_project_config
    usage_loader: Callable[[float], UsageSnapshot | None] = default_usage_loader


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
        log_and_continue(
            logger,
            exc,
            reason="an unreadable usage snapshot is no data, so no breach is found ([]) and the session is not paused on a reading nobody could take",
        )
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
        log_and_continue(
            logger,
            exc,
            reason="a pause record that cannot be written means no pause is entered (None): every other gate reads that record, so a directive without one could not be enforced",
        )
        return None
    if read_usage_pause(directory, session_id, now=now) != pause:
        logger.warning(
            "usage_pause_gate: the pause record could not be read back as written, not pausing"
        )
        try:
            clear_usage_pause(directory, session_id)
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unreadable record that cannot be removed is still not enforced as a pause (None is returned below), so the session is not held by it",
            )
        return None
    logger.warning("usage_pause_gate: pausing session %s: %s", session_id, pause.reason)
    return pause


def try_start_pause(hook_input: Mapping[str, Any], env: PauseEnvironment) -> UsagePause | None:
    """Enter the pause if this session's host ceiling is reached; total, fails open.

    Synthetic traffic (a probe, a harness, a test) is never paused: it is not a
    session spending the account's usage, and a pause would replace the verdict
    of the handler it exists to exercise with the pause directive.
    """
    session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
    if not session_id:
        return None
    if is_synthetic_event(hook_input):
        logger.debug("usage_pause_gate: synthetic traffic is never paused (%s)", session_id)
        return None
    try:
        return start_pause(session_id, current_breaches(hook_input, env), env)
    except Exception as exc:
        # Deliberately broad: this runs inside a SAFETY handler on every tool call, and
        # the chain turns any exception from one into a DENY of the call.
        log_and_continue(
            logger,
            exc,
            reason="an evaluation that raises means no pause is entered (None): this runs inside a SAFETY handler on every tool call, and the chain would turn any exception from one into a DENY of the call",
        )
        return None


def clear_pause(session_id: str) -> bool:
    """Remove the session's pause record; False when a record could not be removed."""
    directory = untracked_dir()
    if directory is None:
        return True
    try:
        clear_usage_pause(directory, session_id)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="a pause record that cannot be removed is reported to the caller as False (not cleared), so the owner is told the clear did not happen",
        )
        return False
    return True
