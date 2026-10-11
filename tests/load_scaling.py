"""Host-load multiplier for the wall-clock bounds of subprocess-driven tests.

A fixed timeout on a subprocess is a guard against a hang, and a loaded host
turns it into a false failure: the same work that takes 30 s on an idle machine
took 25 minutes at a load average of 55 on 8 CPUs (ledger 00474 N344). A bound
that exists only to catch a hang should therefore be a base budget multiplied
by how oversubscribed the host is right now.

The base is the idle-host budget and is always the floor, so the multiplier
only ever lengthens a bound. It never weakens what a test asserts: a test whose
timeout IS the assertion polls for its condition up to the scaled deadline
instead.
"""

from __future__ import annotations

import os
import sys
from typing import Final

#: How much slower in-process Python runs while a tracer (coverage, a debugger)
#: is installed. Measured on the judgement tests of the full-QA blocker: 0.3 s
#: idle, 1.2 s under local coverage, 1.7-2.2 s on the CI runner, which runs the
#: suite with ``--cov``. A host-load average cannot see this cost.
TRACING_FACTOR: Final[float] = 8.0

#: Ceiling on the multiplier, so a runaway load average cannot turn a hang
#: guard into a bound nobody would wait for.
MAX_LOAD_FACTOR: Final[float] = 16.0

#: The load averages that count: the 1 and 5 minute ones. The 5 minute one is
#: kept because a spike that has just ended still leaves the host slow to
#: schedule; the 15 minute one describes a different era of the host.
_LOAD_AVERAGES_USED: Final[int] = 2


def load_factor(
    *,
    load_averages: tuple[float, float, float] | None = None,
    cpu_count: int | None = None,
) -> float:
    """How many times slower than idle the host is likely to run a test, at least 1.

    Args:
        load_averages: The 1, 5 and 15 minute load averages; read from the host
            when omitted. A host that cannot report them counts as idle.
        cpu_count: Logical CPUs; read from the host when omitted. An unknown
            count is treated as one CPU.

    Returns:
        The larger of the 1 and 5 minute load averages per CPU, clamped to
        ``[1.0, MAX_LOAD_FACTOR]``.
    """
    if load_averages is None:
        try:
            load_averages = os.getloadavg()
        except OSError:
            return 1.0
    cpus = cpu_count if cpu_count is not None else os.cpu_count()
    per_cpu = max(load_averages[:_LOAD_AVERAGES_USED]) / max(cpus or 1, 1)
    return min(max(per_cpu, 1.0), MAX_LOAD_FACTOR)


def scaled_seconds(
    base_seconds: float,
    *,
    load_averages: tuple[float, float, float] | None = None,
    cpu_count: int | None = None,
) -> float:
    """``base_seconds`` (the idle-host budget) multiplied by ``load_factor``.

    Raises:
        ValueError: If ``base_seconds`` is not positive.
    """
    if base_seconds <= 0:
        raise ValueError(f"base_seconds must be positive, got {base_seconds}")
    return base_seconds * load_factor(load_averages=load_averages, cpu_count=cpu_count)


def tracing_factor(*, tracer_installed: bool | None = None) -> float:
    """``TRACING_FACTOR`` while a trace function is installed, else 1.

    Args:
        tracer_installed: Whether a tracer is running; read from the
            interpreter when omitted.
    """
    if tracer_installed is None:
        tracer_installed = sys.gettrace() is not None
    return TRACING_FACTOR if tracer_installed else 1.0


def scaled_cpu_seconds(
    base_seconds: float,
    *,
    load_averages: tuple[float, float, float] | None = None,
    cpu_count: int | None = None,
    tracer_installed: bool | None = None,
) -> float:
    """``scaled_seconds`` for in-process CPU work, also scaled for tracing.

    For a bound that asserts how long Python itself takes (a judgement that must
    stay linear), not how long a subprocess may hang: coverage multiplies the
    former several times over and leaves the host load untouched.

    Raises:
        ValueError: If ``base_seconds`` is not positive.
    """
    return scaled_seconds(
        base_seconds, load_averages=load_averages, cpu_count=cpu_count
    ) * tracing_factor(tracer_installed=tracer_installed)
