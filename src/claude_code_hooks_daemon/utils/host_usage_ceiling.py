"""Resolve the subscription-usage ceiling for a hostname (Plan 00479 Task 3.2).

Pure: the caller supplies the ``hosts:`` config and the effective hostname
(``utils.cron_hosts.effective_hostname``). When several entries match, the
lowest ceiling wins per window, being the safer choice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from claude_code_hooks_daemon.config.models import HostConfig


@dataclass(frozen=True, slots=True)
class HostUsageCeiling:
    """The effective ceiling for a hostname.

    Attributes:
        five_hour: Used-percent limit for the 5-hour window, None for no ceiling.
        seven_day: Used-percent limit for the 7-day window, None for no ceiling.
        matched_labels: Labels of every matching entry, in config order,
            including entries that set no ceiling.
    """

    five_hour: float | None
    seven_day: float | None
    matched_labels: tuple[str, ...]


def _lowest(current: float | None, candidate: float | None) -> float | None:
    """The lower of two optional limits; None means no limit and never wins."""
    if candidate is None:
        return current
    return candidate if current is None else min(current, candidate)


def resolve_host_usage_ceiling(hosts: Mapping[str, HostConfig], hostname: str) -> HostUsageCeiling:
    """The effective usage ceiling per window for ``hostname``.

    Args:
        hosts: The ``hosts:`` config, label to entry.
        hostname: The effective session hostname.

    Returns:
        The lowest matching limit per window; no match, or no ceiling on any
        match, leaves the window without one.
    """
    labels: list[str] = []
    five_hour: float | None = None
    seven_day: float | None = None
    for label, host in hosts.items():
        if not host.matches(label, hostname):
            continue
        labels.append(label)
        if host.usage_ceiling is not None:
            five_hour = _lowest(five_hour, host.usage_ceiling.effective_five_hour)
            seven_day = _lowest(seven_day, host.usage_ceiling.effective_seven_day)
    return HostUsageCeiling(five_hour, seven_day, tuple(labels))
