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
from typing import Final

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
