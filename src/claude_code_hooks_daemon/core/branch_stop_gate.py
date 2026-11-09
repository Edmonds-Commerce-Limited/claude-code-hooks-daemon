"""The Stop and SubagentStop branch decision (Plan 00558 Task 4.4, DESIGN.md sections 4 and 6).

:func:`decide_stop` turns the judgement of :mod:`core.branch_stop_guard` into
what a stop handler returns: a deny reason (at most ``MAX_STOP_BLOCKS`` times
per stopping identity, after which the guard gives way and records the branches
as abandoned) and context lines. The main thread also gets a once-an-hour line
naming branches idle at the noisy dormancy stage or later. Both handlers share
this function so the rules cannot drift apart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.core.agent_ownership import canonical_path, running_holds
from claude_code_hooks_daemon.core.branch_cleanup import linked_worktrees, sweep_clean_line
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchInventory,
    BranchInventoryError,
    DormancyStage,
    build_inventory,
)
from claude_code_hooks_daemon.core.branch_stop_guard import StopCheck, StopFinding, judge_stop
from claude_code_hooks_daemon.core.branch_sweep import dormant_action
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path, write_state

logger = logging.getLogger(__name__)

#: Stops denied per stopping identity before the guard gives way.
MAX_STOP_BLOCKS: Final[int] = 3
#: Spend-ledger state kind holding the block count and the noisy-line clock.
STATE_KIND: Final[str] = "branch-stop-guard"
#: The noisy line appears at most this often per session.
NOISY_INTERVAL_SECONDS: Final[float] = 3600.0
#: A running release owns the repository state; the guard stands aside.
RELEASE_STATE_FILENAME: Final[str] = "release-state.json"

_MAIN_KEY: Final[str] = "main"
_NOISY_STAGES: Final[frozenset[DormancyStage]] = frozenset(
    {DormancyStage.NOISY, DormancyStage.BLOCK}
)
_MAX_NOISY_NAMES: Final[int] = 10


@dataclass(frozen=True)
class StopDecision:
    """``reason`` is the deny text, or None to allow; ``context`` is non-blocking output."""

    reason: str | None
    context: tuple[str, ...]


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _describe(finding: StopFinding) -> list[str]:
    lines = [f"  - {finding.branch}: {finding.check.value} (tip {finding.tip[:12]})"]
    lines.extend(f"      {command}" for command in finding.commands)
    return lines


def _deny_reason(
    findings: list[StopFinding], tips: dict[str, str], *, block: int, handoff: bool
) -> str:
    lines = ["BRANCHES LEFT BEHIND: this stop leaves branch work unfinished."]
    for finding in findings:
        lines.extend(_describe(finding))
    merged = [finding for finding in findings if finding.check == StopCheck.MERGED]
    if merged:
        lines.append(sweep_clean_line(remote=any(finding.on_remote for finding in merged)))
    if handoff:
        lines.append("Handoff: record these in the handoff note (branch @ tip):")
        lines.extend(f"  {name} @ {tip}" for name, tip in sorted(tips.items()))
    lines.append(
        f"Block {block} of {MAX_STOP_BLOCKS}; after that the stop is allowed and the "
        "branches are recorded as abandoned."
    )
    lines.append(BRANCH_LIMIT_PRINCIPLE)
    return "\n".join(lines)


def _noisy_line(inventory: BranchInventory) -> str | None:
    names = sorted(
        name for name, record in inventory.records.items() if record.dormancy_stage in _NOISY_STAGES
    )
    if not names:
        return None
    shown = names[:_MAX_NOISY_NAMES]
    more = len(names) - _MAX_NOISY_NAMES
    lines = [
        "Idle branches at the noisy dormancy stage or later: unfinished work. This session "
        "should take this work on now, before starting anything new.",
        BRANCH_LIMIT_PRINCIPLE,
    ]
    lines.extend(f"  {name}: {dormant_action(name)}" for name in shown)
    if more > 0:
        lines.append(f"  (and {more} more; see `branch-sweep`)")
    return "\n".join(lines)


def _noisy_context(
    inventory: BranchInventory, state: dict[str, Any], *, now: float
) -> tuple[str, ...]:
    last = state.get("noisy_last")
    if isinstance(last, (int, float)) and now - last < NOISY_INTERVAL_SECONDS:
        return ()
    line = _noisy_line(inventory)
    if line is None:
        return ()
    state["noisy_last"] = now
    return (line,)


def _running_queue_branches(repo: Path, untracked: Path) -> frozenset[str]:
    """Branches a ``running`` work-queue record holds, by the sweep's own holds.

    :func:`agent_ownership.running_holds` is the one reader of the queue: a branch is
    held when a record names it, or when it is checked out in a worktree a record
    names, in whatever spelling (relative, trailing separator, symlink). Empty when
    the queue is unreadable, so every finding stands.
    """
    holds = running_holds(untracked, repo)
    if not holds.worktrees:
        return holds.branches
    try:
        worktrees = linked_worktrees(repo)
    except RuntimeError as exc:
        log_and_continue(
            logger,
            exc,
            reason="branch_stop_guard: the worktrees cannot be listed, so only branches a "
            "running work-queue record names are handed over",
        )
        return holds.branches
    by_worktree = {
        name for name, path in worktrees.items() if canonical_path(path, repo) in holds.worktrees
    }
    return holds.branches | by_worktree


def decide_stop(
    repo: Path,
    branches: BranchesConfig,
    untracked: Path,
    *,
    session_id: str,
    agent_id: str | None,
    handoff: bool,
    now: float,
) -> StopDecision:
    """Judge a stop; every failure to judge allows the stop rather than holding it."""
    allow = StopDecision(None, ())
    if branches.stop_guard.mode == "off" or (untracked / RELEASE_STATE_FILENAME).exists():
        return allow
    try:
        inventory = build_inventory(repo, branches)
    except BranchInventoryError as exc:
        log_and_continue(
            logger,
            exc,
            reason="branch_stop_guard: the branches cannot be listed, so none can be judged; "
            "the stop is allowed rather than held on a git failure",
        )
        return allow
    judgement = judge_stop(
        repo,
        inventory,
        branches,
        session_id=session_id,
        agent_id=agent_id,
        handoff=handoff,
    )
    state_file = state_path(untracked, session_id, STATE_KIND, agent_id or _MAIN_KEY)
    state = read_state(state_file)
    # N581: the coordinator cannot finish a branch a live work-queue agent owns, so it
    # is handed over, not left behind. A sub-agent's own stop is still judged in full.
    handed = _running_queue_branches(repo, untracked) if agent_id is None else frozenset()
    findings = [f for f in judgement.findings if f.branch not in handed]
    blocking = [f for f in findings if not f.advisory]
    advisory = [f for f in findings if f.advisory]
    context: list[str] = [
        f"Branch left behind (advisory): {f.branch}: {f.check.value}" for f in advisory
    ]
    over = sorted({f.branch for f in judgement.findings if f.branch in handed})
    if over:
        context.append(
            "Branches handed over to running work-queue agents (not abandoned): " + ", ".join(over)
        )
    reason: str | None = None
    if blocking and branches.stop_guard.mode == "warn":
        context.extend(f"Branch left behind: {f.branch}: {f.check.value}" for f in blocking)
    elif blocking:
        blocks = _int(state.get("blocks"))
        if blocks < MAX_STOP_BLOCKS:
            state["blocks"] = blocks + 1
            reason = _deny_reason(blocking, judgement.tips, block=blocks + 1, handoff=handoff)
        else:
            names = sorted({f.branch for f in blocking})
            state["abandoned"] = names
            logger.warning("branch_stop_guard: abandoned at stop: %s", ", ".join(names))
            context.append(
                f"Branches abandoned at stop after {MAX_STOP_BLOCKS} blocks: " + ", ".join(names)
            )
    if reason is None and agent_id is None:
        context.extend(_noisy_context(inventory, state, now=now))
    if state:
        write_state(state_file, state)
    return StopDecision(reason, tuple(context))
