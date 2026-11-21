"""Scratch cap evaluation: warn, then block, before the link index overflows.

Plan 00627 DESIGN.md section 8. Pure: the counts come from the cached
inventory, the figures from ``scratch.caps``. An incomplete inventory's counts
are lower bounds, so it can raise a level and never lower one: with
``incomplete`` the result is at least ``previous``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from claude_code_hooks_daemon.config.models import ScratchCapsConfig, ScratchThresholdConfig


class CapLevel(enum.IntEnum):
    """How far a count has reached; ordered so ``max`` is the worst."""

    OK = 0
    WARN = 1
    BLOCK = 2


@dataclass(frozen=True)
class CapCounts:
    """The inventory's totals over every scratch root, the archive store and the stores."""

    directories: int
    bytes: int
    entries: int


@dataclass(frozen=True)
class CapCheck:
    """One key's count against its warn and block figures."""

    key: str
    count: int
    warn: int
    block: int
    level: CapLevel


@dataclass(frozen=True)
class CapReport:
    """Every evaluated key, the worst level, and whether a block is enforced."""

    checks: tuple[CapCheck, ...]
    level: CapLevel
    incomplete: bool
    enforce: bool

    def at_or_above(self, level: CapLevel) -> tuple[CapCheck, ...]:
        """The checks whose own level is ``level`` or worse."""
        return tuple(check for check in self.checks if check.level >= level)


def _check(key: str, count: int, warn: int, block: int) -> CapCheck:
    if count >= block:
        level = CapLevel.BLOCK
    elif count >= warn:
        level = CapLevel.WARN
    else:
        level = CapLevel.OK
    return CapCheck(key=key, count=count, warn=warn, block=block, level=level)


def _threshold(key: str, count: int, figures: ScratchThresholdConfig) -> CapCheck:
    return _check(key, count, figures.warn, figures.block)


def evaluate_caps(
    counts: CapCounts,
    caps: ScratchCapsConfig,
    *,
    incomplete: bool,
    previous: CapLevel | None = None,
    index_directories: int | None = None,
    index_cap: int | None = None,
) -> CapReport:
    """Evaluate ``counts`` against ``caps``.

    ``project_directories`` is evaluated only when the link index supplies its
    listed count and its cap. ``mode: off`` evaluates nothing; ``advise`` keeps
    the level for the report but never enforces a block.
    """
    if caps.mode == "off":
        return CapReport(checks=(), level=CapLevel.OK, incomplete=incomplete, enforce=False)
    checks = [
        _threshold("directories", counts.directories, caps.directories),
        _threshold("bytes", counts.bytes, caps.bytes),
        _threshold("entries", counts.entries, caps.entries),
    ]
    if index_directories is not None and index_cap is not None:
        share = caps.project_directories
        checks.append(
            _check(
                "project_directories",
                index_directories,
                index_cap * share.warn_percent // 100,
                index_cap * share.block_percent // 100,
            )
        )
    level = max(check.level for check in checks)
    if incomplete and previous is not None:
        level = max(level, previous)
    return CapReport(
        checks=tuple(checks),
        level=CapLevel(level),
        incomplete=incomplete,
        enforce=caps.mode == "block",
    )
