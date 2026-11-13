"""Host-load scaling for the wall-clock budget of a subprocess.

A fixed timeout on a subprocess whose duration follows host load or tree size is
a hang guard that a loaded host turns into a hard failure: ``git worktree add``
took over 30 s at a load average near 70, and the cleanup that followed, on a 5 s
budget, could not undo it. A budget for such a call is therefore the idle-host
base multiplied by how oversubscribed the host is right now, bounded by a ceiling
the caller's own outer deadline can afford.

The base is always the floor, so scaling only ever lengthens a budget.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

#: The 1 and 5 minute load averages count; the 5 minute one stays because a
#: spike that just ended still leaves the host slow to schedule.
_LOAD_AVERAGES_USED: Final[int] = 2


@dataclass(frozen=True)
class _LoadReading:
    """One read of the host load: the averages, or the reason there are none."""

    averages: tuple[float, float, float] | None
    unavailable: str | None = None


def _read_load() -> _LoadReading:
    """Read the host's 1, 5 and 15 minute load averages; a failed read is a typed result."""
    try:
        return _LoadReading(averages=os.getloadavg())
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason=(
                "host load average is unreadable on this platform, so the "
                "budget is not scaled and stays at its idle-host base"
            ),
            level=logging.DEBUG,
        )
        return _LoadReading(averages=None, unavailable=str(exc))


def _load_averages() -> tuple[float, float, float] | None:
    """The host's load averages, or ``None`` when the host does not report them."""
    return _read_load().averages


def load_factor(
    *,
    load_averages: tuple[float, float, float] | None = None,
    cpu_count: int | None = None,
) -> float:
    """How many times slower than idle the host is likely to run a subprocess, at least 1.

    Args:
        load_averages: Read from the host when omitted; an unreadable load counts as idle.
        cpu_count: Logical CPUs; read from the host when omitted, unknown counts as one.
    """
    averages = load_averages if load_averages is not None else _load_averages()
    if averages is None:
        return 1.0
    cpus = cpu_count if cpu_count is not None else os.cpu_count()
    per_cpu = max(averages[:_LOAD_AVERAGES_USED]) / max(cpus or 1, 1)
    return max(per_cpu, 1.0)


def scaled_timeout(
    base_seconds: float,
    ceiling_seconds: float,
    *,
    load_averages: tuple[float, float, float] | None = None,
    cpu_count: int | None = None,
) -> float:
    """``base_seconds`` times the host load factor, bounded by ``ceiling_seconds``.

    Raises:
        ValueError: If ``base_seconds`` is not positive or exceeds the ceiling.
    """
    if base_seconds <= 0:
        raise ValueError(f"base_seconds must be positive, got {base_seconds}")
    if ceiling_seconds < base_seconds:
        raise ValueError(f"ceiling {ceiling_seconds} is below the base {base_seconds}")
    factor = load_factor(load_averages=load_averages, cpu_count=cpu_count)
    return min(base_seconds * factor, ceiling_seconds)


def describe_load(
    *,
    load_averages: tuple[float, float, float] | None = None,
    cpu_count: int | None = None,
) -> str:
    """A one-line statement of the host load, for a log line or an error message."""
    averages = load_averages if load_averages is not None else _load_averages()
    if averages is None:
        return "host load average unavailable"
    cpus = cpu_count if cpu_count is not None else os.cpu_count()
    one, five, fifteen = averages
    return f"load average {one:.1f} {five:.1f} {fifteen:.1f} on {cpus or 1} CPUs"


def branch_metadata_timeout() -> float:
    """The budget of one branch-metadata git call inside the WorktreeCreate event.

    The ``GIT_CONTEXT`` base scaled by host load, bounded by the ceiling the
    event budget (``Timeout.EVENT_HANDLER_BUDGET``) is sized for.
    """
    return scaled_timeout(Timeout.GIT_CONTEXT, Timeout.GIT_BRANCH_METADATA_MAX)
