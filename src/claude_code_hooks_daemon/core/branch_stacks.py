"""Stacked branches count once against the open cap (Plan 00594 Task 4.6, DESIGN.md 7.1).

A stack is a chain of open work units where each unit's tip is a strict ancestor
of the next one's. A dependent pull request is not independent work, and landing
the bottom first is already the practice, so a stack counts 1 against
``branches.wip.cap`` up to ``branches.wip.stack_max_depth`` links and 1 more for
each link past that: a too-deep stack is pressed, never hidden.

A fork (one unit with two nearest descendants) ends the chain: each arm is its own
stream, and the shared base goes with the first arm by name.

Grouping reads tips only (one ``git rev-list``, no forge call), because reported
stacks are pushed as separate pull requests and may exist only as remote-tracking
refs. The callers classify first: only units already in the OPEN pool are passed
in, so a parked, merged, park-carried or foreign branch never joins a stack.

Fail closed: when the ancestry cannot be read, nothing is grouped and every unit
counts on its own. That over-counts, which is the safe direction for a cap.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.load_scaling import branch_metadata_timeout

logger = logging.getLogger(__name__)

#: Tip sha -> the strict ancestors of that tip among the tips asked about.
TipAncestry = Mapping[str, frozenset[str]]

#: The words every surface uses for a stack's next step.
LAND_BOTTOM_FIRST = "land the bottom first"


@dataclass(frozen=True)
class WorkUnit:
    """One open piece of work: its display name and every tip that joins it."""

    name: str
    tips: frozenset[str]


@dataclass(frozen=True)
class WorkStack:
    """One stream of open work, its links bottom first; a lone unit is a stream of one."""

    links: tuple[str, ...]

    @property
    def depth(self) -> int:
        """How many units the stream holds."""
        return len(self.links)

    @property
    def bottom(self) -> str:
        """The unit to land first."""
        return self.links[0]

    @property
    def top(self) -> str:
        """The group key (DESIGN.md 7.1): the chain's top."""
        return self.links[-1]


def stack_charge(depth: int, max_depth: int) -> int:
    """What one stream of ``depth`` units counts against the open cap.

    Raises:
        ValueError: ``depth`` or ``max_depth`` is below 1.
    """
    if depth < 1 or max_depth < 1:
        raise ValueError(f"stack depth and max depth must be at least 1: {depth}, {max_depth}")
    return 1 + max(0, depth - max_depth)


def open_work_charge(stacks: Iterable[WorkStack], max_depth: int) -> int:
    """The open-work count: the ONE function the sweep, preflight, guard and ladder read."""
    return sum(stack_charge(stack.depth, max_depth) for stack in stacks)


def read_tip_ancestry(
    repo: Path, tips: frozenset[str], exclude_refs: Sequence[str]
) -> TipAncestry | None:
    """Which of ``tips`` is a strict ancestor of which, in one ``git rev-list``.

    The walk stops at ``exclude_refs`` (the default branch), so it covers only
    unmerged commits. With no exclusion the walk would cover the whole history, so
    the answer is None (unknown) instead; a git failure is unknown too.
    """
    if not exclude_refs or not tips:
        return None
    result = run_git(
        repo,
        "rev-list",
        "--topo-order",
        "--parents",
        *sorted(tips),
        "--not",
        *exclude_refs,
        timeout=branch_metadata_timeout(),
    )
    if result.returncode != 0:
        logger.info("branch_stacks: ancestry walk failed: %s", result.stderr.strip())
        return None
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    below: dict[str, frozenset[str]] = {}
    # --topo-order lists children before parents, so reversed, parents come first.
    for row in reversed(rows):
        commit, parents = row[0], row[1:]
        found: frozenset[str] = frozenset()
        for parent in parents:
            if parent not in below:
                continue
            inherited = below[parent] | ({parent} if parent in tips else frozenset())
            found = inherited if not found else found | inherited
        below[commit] = found
    return {tip: below.get(tip, frozenset()) for tip in tips}


def _units_below(units: Sequence[WorkUnit], ancestry: TipAncestry) -> dict[str, frozenset[str]]:
    """Unit name -> the other units with a tip strictly below one of its tips.

    A pair that each claims to be below the other (two-tip units that cross) is
    related in neither direction: it is not a chain.
    """
    owner = {tip: unit.name for unit in units for tip in unit.tips}
    below: dict[str, set[str]] = {}
    for unit in units:
        found = {
            owner[ancestor]
            for tip in unit.tips
            for ancestor in ancestry.get(tip, frozenset())
            if ancestor in owner
        }
        found.discard(unit.name)
        below[unit.name] = found
    return {
        name: frozenset(other for other in found if name not in below[other])
        for name, found in below.items()
    }


def group_stacks(units: Sequence[WorkUnit], ancestry: TipAncestry | None) -> tuple[WorkStack, ...]:
    """Every unit in exactly one stream, streams sorted by their bottom link.

    ``ancestry`` None (unknown) groups nothing: each unit is its own stream.
    """
    names = sorted(unit.name for unit in units)
    if ancestry is None or len(names) < 2:
        return tuple(WorkStack((name,)) for name in names)
    below = _units_below(units, ancestry)
    nearest_below = {
        name: {a for a in found if not any(a in below[c] for c in found if c != a)}
        for name, found in below.items()
    }
    nearest_above: dict[str, list[str]] = {name: [] for name in names}
    for name in names:
        for lower in nearest_below[name]:
            nearest_above[lower].append(name)
    successor: dict[str, str] = {}
    claimed: set[str] = set()
    for name in names:
        for upper in sorted(nearest_above[name]):
            if upper not in claimed:
                successor[name] = upper
                claimed.add(upper)
                break
    visited: set[str] = set()
    stacks: list[WorkStack] = []
    # Unclaimed units start a stream; anything left (a cycle) starts its own after.
    for start in [n for n in names if n not in claimed] + names:
        if start in visited:
            continue
        links: list[str] = []
        current: str | None = start
        while current is not None and current not in visited:
            visited.add(current)
            links.append(current)
            current = successor.get(current)
        stacks.append(WorkStack(tuple(links)))
    return tuple(sorted(stacks, key=lambda stack: stack.bottom))


def stack_line(stack: WorkStack, max_depth: int) -> str:
    """The one line a stack of two or more links is printed as."""
    charge = stack_charge(stack.depth, max_depth)
    counted = "counts 1" if charge == 1 else f"counts {charge}, past stack_max_depth {max_depth}"
    return (
        f"stack of {stack.depth}, bottom {stack.bottom} ({' <- '.join(stack.links)}; "
        f"{counted}): {LAND_BOTTOM_FIRST}"
    )
