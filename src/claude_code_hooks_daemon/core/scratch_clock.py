"""The scratch TTL clock (Plan 00627 Task 1.4, DESIGN.md section 4).

An entry's activity is the newest of three inputs: the walker's newest mtime
(an mtime in the future already replaced by that inode's ctime), the entry
root's ctime, and the birth time recorded for it, when there is one. ``cp -a``
and ``tar -x`` restore old mtimes, so the ctime and the birth stop a fresh copy
looking expired. ``touch`` keeps an mtime fresh for ever, so past
``max_lifetime_hours`` from birth the entry is due whatever its mtime.

Phase 1 records no birth anywhere, so the lifetime backstop has no input yet;
the result says so rather than pretending it was checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from claude_code_hooks_daemon.core.scratch_walk import EntryStats

_NANOSECONDS = 1_000_000_000
_SECONDS_PER_HOUR = 3600

#: Reported when an entry has no recorded birth time.
NO_BIRTH_NOTE = "no birth time recorded: the maximum-lifetime backstop was not evaluated"


@dataclass(frozen=True)
class EntryAge:
    """How long an entry has been idle, and whether its TTL has run out."""

    #: Seconds since the newest activity, never negative.
    age_seconds: float
    #: True when the age reached the TTL, or the maximum lifetime ran out.
    due: bool
    #: None when there is no birth time to measure the lifetime from.
    lifetime_exceeded: bool | None
    notes: tuple[str, ...] = ()


def entry_age(
    stats: EntryStats,
    *,
    now: float,
    ttl_hours: int,
    max_lifetime_hours: int,
    birth: float | None = None,
) -> EntryAge:
    """The age of the entry ``stats`` describes, at wall-clock ``now`` (seconds)."""
    activity = max(stats.newest_mtime_ns, stats.root_ctime_ns) / _NANOSECONDS
    if birth is not None:
        activity = max(activity, birth)
    age_seconds = max(0.0, now - activity)
    due = age_seconds >= ttl_hours * _SECONDS_PER_HOUR
    if birth is None:
        return EntryAge(age_seconds, due, None, (NO_BIRTH_NOTE,))
    exceeded = now - birth >= max_lifetime_hours * _SECONDS_PER_HOUR
    return EntryAge(age_seconds, due or exceeded, exceeded)


__all__ = ["NO_BIRTH_NOTE", "EntryAge", "entry_age"]
