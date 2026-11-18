"""The branch pool warning ladder (Plan 00619).

Each pool (open work, parked, merged) hard-stops branch creation at its block
point. This module warns well before that, by the share of the block point in
use: warn at 60 percent, strong at 80, very strong at 90 (configurable per pool,
thresholds rounded UP), block at 100. It changes nothing a guard denies or allows:
it only reads the pools and words the pressure.

The block point is where creation is actually refused, so the open pool's is
``wip.cap + wip.creation_grace`` and the parked and merged pools' is their cap.

Every surface (session start, the stop report, the every-prompt and every-tool-call
advisories) renders the same :class:`PoolPressure` through :func:`pressure_lines`.
Warn and strong show once per session per pool and level (:class:`LadderThrottle`);
very strong and block are never rate-limited.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import BranchesConfig, BranchLadderConfig
from claude_code_hooks_daemon.constants.branch_guard import POOL_PARK_CLAUSE
from claude_code_hooks_daemon.core.branch_cleanup import sweep_clean_command
from claude_code_hooks_daemon.core.branch_creation import (
    CLEANABLE_GROUPS,
    WorkGroup,
    work_pools,
    work_rank,
)
from claude_code_hooks_daemon.core.branch_inventory import Pool
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

#: How long the every-call surfaces reuse one reading of the pools (seconds).
PRESSURE_CACHE_SECONDS: Final[float] = 10.0
_SECONDS_PER_DAY: Final[float] = 86400.0
_ICON: Final[str] = "🌿"

Labels = Mapping[str, Mapping[str, str | None]]


class LadderLevel(IntEnum):
    """How full a pool is, in order: nothing to say up to the block itself."""

    NONE = 0
    WARN = 1
    STRONG = 2
    VERY_STRONG = 3
    BLOCK = 4


#: Levels that are never rate-limited: shown on every call until usage drops below.
_ALWAYS_SHOWN: Final[frozenset[LadderLevel]] = frozenset({LadderLevel.VERY_STRONG, LadderLevel.BLOCK})


def _threshold_count(base: int, percent: int) -> int:
    """The count at which ``percent`` of ``base`` is reached, rounded UP (integer maths)."""
    return -(-base * percent // 100)


def ladder_level(count: int, base: int, thresholds: BranchLadderConfig) -> LadderLevel:
    """The level of a pool holding ``count`` against a block point of ``base``.

    Thresholds that collapse onto the block point (a small ``base``) leave the
    highest level the count reaches: the pool is simply blocked at ``base``.
    """
    if count >= base:
        return LadderLevel.BLOCK
    for level, percent in (
        (LadderLevel.VERY_STRONG, thresholds.very_strong),
        (LadderLevel.STRONG, thresholds.strong),
        (LadderLevel.WARN, thresholds.warn),
    ):
        if count >= _threshold_count(base, percent):
            return level
    return LadderLevel.NONE


def pool_base(config: BranchesConfig, pool: Pool) -> int:
    """The count at which creation is refused: the 100 percent of the ladder."""
    if pool == Pool.OPEN:
        return config.effective_wip_cap() + config.wip.creation_grace
    return config.effective_pool_cap(pool)


class LadderThrottle:
    """Which warn and strong notices a session has already been shown."""

    def __init__(self) -> None:
        self._shown: set[tuple[str | None, Pool, LadderLevel]] = set()

    def should_show(self, session_id: str | None, pool: Pool, level: LadderLevel) -> bool:
        """True when the notice is due: always for very strong and block, once otherwise."""
        if level == LadderLevel.NONE:
            return False
        if level in _ALWAYS_SHOWN:
            return True
        key = (session_id, pool, level)
        if key in self._shown:
            return False
        self._shown.add(key)
        return True


@dataclass(frozen=True)
class PoolPressure:
    """One pool at or above the warn level."""

    pool: Pool
    count: int
    base: int
    level: LadderLevel
    work: tuple[WorkGroup, ...]


def _pool_section_mode_and_ladder(
    config: BranchesConfig, pool: Pool
) -> tuple[str, BranchLadderConfig]:
    if pool == Pool.OPEN:
        return config.wip.mode, config.wip.ladder
    section = config.parked if pool == Pool.PARKED else config.merged
    return section.mode, section.ladder


def pool_pressures(repo: Path, config: BranchesConfig, labels: Labels) -> list[PoolPressure]:
    """Every pool at or above its warn level; empty when git cannot be read.

    A pool whose ``mode`` is ``off`` is not counted, as in the creation guard.
    """
    try:
        pools = work_pools(repo, config, labels=labels)
    except (RuntimeError, OSError) as exc:
        log_and_continue(
            logger,
            exc,
            reason="the ladder is advisory: a repository that cannot be read gets no warning, "
            "and the creation guard reports its own failure",
            level=logging.DEBUG,
        )
        return []
    found: list[PoolPressure] = []
    for pool, work in pools.items():
        mode, thresholds = _pool_section_mode_and_ladder(config, pool)
        if mode == "off":
            continue
        base = pool_base(config, pool)
        level = ladder_level(len(work), base, thresholds)
        if level != LadderLevel.NONE:
            found.append(PoolPressure(pool, len(work), base, level, tuple(work)))
    return found


# --- wording --------------------------------------------------------------------------


_HEADLINES: Final[dict[LadderLevel, str]] = {
    LadderLevel.WARN: "WARNING",
    LadderLevel.STRONG: "STRONG WARNING",
    LadderLevel.VERY_STRONG: "VERY STRONG WARNING (shown on every tool call and prompt until "
    "the pool drops below this level)",
    LadderLevel.BLOCK: "AT THE LIMIT (a new branch is refused)",
}


def _first_to_close(pressure: PoolPressure) -> WorkGroup:
    """The branch to finish or remove first.

    From the strong level up, an unfinished branch comes first (oldest first):
    merged ones are cleared by a sweep and need no decision. At warn the cheapest
    to close comes first, as the deny list orders them.
    """
    work = pressure.work
    if pressure.level >= LadderLevel.STRONG:
        unfinished = [w for w in work if w.label.get("group") not in CLEANABLE_GROUPS]
        pool = unfinished or list(work)
        return min(pool, key=lambda w: (w.committed, w.name))
    return min(work, key=lambda w: (work_rank(w), w.committed, w.name))


def _command(pressure: PoolPressure, work: WorkGroup) -> str:
    park = daemon_cli_command_for_docs("branch-park")
    if pressure.pool == Pool.MERGED:
        return sweep_clean_command(remote=any(w.on_remote for w in pressure.work))
    if pressure.pool == Pool.PARKED:
        return f"{park} {work.name} --clear, then merge it"
    return str(work.label.get("action") or f"{park} {work.name} --reason ...")


def pressure_lines(pressure: PoolPressure, *, now: float) -> list[str]:
    """The few lines for one pool: its count against the block point, one branch, one command."""
    percent = pressure.count * 100 // pressure.base
    lines = [
        f"{_ICON}  BRANCH POOL {_HEADLINES[pressure.level]}: the {pressure.pool.value} pool "
        f"holds {pressure.count} of {pressure.base} ({percent}% of the point where creating "
        "a branch is refused)."
    ]
    if pressure.work:
        first = _first_to_close(pressure)
        age = max(0, int((now - first.committed) // _SECONDS_PER_DAY))
        lines.append(
            f"  Finish or remove first: {first.name} ({age}d old) -> {_command(pressure, first)}"
        )
    if pressure.level >= LadderLevel.STRONG:
        lines.append(
            "  A branch leaves the pool by being merged or, only when it holds no value, "
            "through the no-value verdict route of Plan 00620 once it ships "
            f"(your own assertion never counts); {POOL_PARK_CLAUSE}."
        )
    preflight = daemon_cli_command_for_docs("branch-preflight")
    lines.append(f"  Every branch and its fix: `{preflight}`.")
    return lines


# --- the surfaces' shared entry point ---------------------------------------------------


class PressureCache:
    """One recent reading of the pools per repository, so every-call surfaces stay cheap."""

    def __init__(self, ttl: float = PRESSURE_CACHE_SECONDS) -> None:
        self._ttl = ttl
        self._entries: dict[tuple[str, int], tuple[float, list[PoolPressure]]] = {}

    def get(
        self,
        repo: Path,
        config: BranchesConfig,
        labels: Labels,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> list[PoolPressure]:
        """The pressures of ``repo``, read afresh once the last reading is ``ttl`` old."""
        key = (str(repo), id(config))
        stamp = clock()
        cached = self._entries.get(key)
        if cached is not None and stamp - cached[0] < self._ttl:
            return cached[1]
        pressures = pool_pressures(repo, config, labels)
        self._entries[key] = (stamp, pressures)
        return pressures


#: What this daemon process has already told each session (warn and strong only).
SESSION_THROTTLE: Final[LadderThrottle] = LadderThrottle()
#: The reading the every-call advisories share.
PRESSURE_CACHE: Final[PressureCache] = PressureCache()


def ladder_notice(
    repo: Path,
    config: BranchesConfig,
    labels: Labels,
    *,
    session_id: str | None,
    throttle: LadderThrottle | None,
    cache: PressureCache | None = None,
    now: float | None = None,
) -> list[str]:
    """The ladder lines due now. ``throttle`` None shows every level (session start, stop)."""
    pressures = (
        cache.get(repo, config, labels) if cache else pool_pressures(repo, config, labels)
    )
    moment = time.time() if now is None else now
    lines: list[str] = []
    for pressure in pressures:
        if throttle is None or throttle.should_show(session_id, pressure.pool, pressure.level):
            lines.extend(pressure_lines(pressure, now=moment))
    return lines
