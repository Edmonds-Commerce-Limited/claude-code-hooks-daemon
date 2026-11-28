"""The Stop and SubagentStop branch decision (Plan 00558 Task 4.4, DESIGN.md sections 4 and 6).

:func:`decide_stop` turns the judgement of :mod:`core.branch_stop_guard` into
what a stop handler returns: a deny reason (at most ``MAX_STOP_BLOCKS`` times
per stopping identity, after which the guard gives way and records the branches
(as left unpushed when unpushed commits are a branch's only finding, otherwise as
abandoned); stops refused only on own harness-directory branches have a second
budget of the same size) and context lines. The main thread also gets a once-an-hour line
naming branches idle at the noisy dormancy stage or later. Both handlers share
this function so the rules cannot drift apart.
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.core.agent_ownership import ownership_refusal, running_holds
from claude_code_hooks_daemon.core.branch_cleanup import linked_worktree_records, sweep_clean_line
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchInventory,
    BranchInventoryError,
    DormancyStage,
    build_inventory,
)
from claude_code_hooks_daemon.core.branch_ladder import ladder_notice
from claude_code_hooks_daemon.core.branch_stop_guard import StopCheck, StopFinding, judge_stop
from claude_code_hooks_daemon.core.branch_sweep import dormant_action
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.session_load import (
    LiveAgent,
    finished_agents,
    finished_task_ids,
    live_agents,
)
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path, write_state
from claude_code_hooks_daemon.utils.transcript_tail import subagents_dir

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
#: State keys: the main block counter, and the one for stops refused only on newly
#: judged own harness-directory branches (each capped at ``MAX_STOP_BLOCKS``).
_BLOCKS_KEY: Final[str] = "blocks"
_HARNESS_BLOCKS_KEY: Final[str] = "blocks_harness"
_NOISY_STAGES: Final[frozenset[DormancyStage]] = frozenset(
    {DormancyStage.NOISY, DormancyStage.BLOCK}
)
_MAX_NOISY_NAMES: Final[int] = 10
#: Branches whose only finding is "no remote holds the commits": nothing is lost.
_UNPUSHED_KEY: Final[str] = "unpushed"
_UNPUSHED_RECORD: Final[str] = "left unpushed"
_UNPUSHED_TRUTH: Final[str] = (
    "The work is intact locally; what is missing is a push, or a branch-park with a reason."
)
#: State key: the branches the last stop let through as in flight with a live agent.
_IN_FLIGHT_KEY: Final[str] = "in_flight"
#: The main thread's id on a touch record.
_MAIN_TOUCH: Final[str] = ""
_LEAVE_IT_TO_THE_AGENT: Final[str] = (
    "wait for that agent to finish, stop it (TaskStop), or have it commit its own work"
)


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
    if all(finding.check == StopCheck.UNPUSHED for finding in findings):
        lines.append(
            f"Block {block} of {MAX_STOP_BLOCKS}; after that the stop is allowed and the "
            f"branches are recorded as {_UNPUSHED_RECORD}. {_UNPUSHED_TRUTH}"
        )
    else:
        lines.append(
            f"Block {block} of {MAX_STOP_BLOCKS}; after that the stop is allowed and the "
            f"branches are recorded as abandoned (or as {_UNPUSHED_RECORD} where unpushed "
            "commits are a branch's only finding)."
        )
    lines.append(BRANCH_LIMIT_PRINCIPLE)
    return "\n".join(lines)


def _record_given_way(state: dict[str, Any], blocking: list[StopFinding]) -> list[str]:
    """Record the branches a stop is let through on, and the context lines saying so.

    A branch whose only finding is unpushed commits is recorded under ``unpushed``
    with what is true (the work is intact locally; a push or a park is missing); any
    other branch is recorded under ``abandoned``.
    """
    unpushed_only = {f.branch for f in blocking} - {
        f.branch for f in blocking if f.check != StopCheck.UNPUSHED
    }
    abandoned = sorted({f.branch for f in blocking} - unpushed_only)
    lines: list[str] = []
    if unpushed_only:
        names = sorted(unpushed_only)
        state[_UNPUSHED_KEY] = names
        logger.warning("branch_stop_guard: left unpushed at stop: %s", ", ".join(names))
        lines.append(
            f"Branches {_UNPUSHED_RECORD} at stop after {MAX_STOP_BLOCKS} blocks: "
            + ", ".join(names)
            + f". {_UNPUSHED_TRUTH}"
        )
    if abandoned:
        state["abandoned"] = abandoned
        logger.warning("branch_stop_guard: abandoned at stop: %s", ", ".join(abandoned))
        lines.append(
            f"Branches abandoned at stop after {MAX_STOP_BLOCKS} blocks: " + ", ".join(abandoned)
        )
    return lines


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


@dataclass(frozen=True)
class HandOver:
    """Who a coordinator stop hands over, read from ONE worktree listing and queue read.

    ``handed`` is what this stop hands over. ``newly_judged`` maps each branch the
    stopping thread touched itself whose only hold is the harness ``.claude/worktrees/``
    directory to that worktree: handed over before Plan 00618 B-2, judged now. Its
    refusals draw on a separate counter so the main one matches the pre-B-2 gate.
    """

    handed: frozenset[str]
    newly_judged: dict[str, Path]


def _hand_over(repo: Path, untracked: Path, *, own: frozenset[str]) -> HandOver:
    """Branches a live agent owns, by :func:`agent_ownership.ownership_refusal`.

    The coordinator cannot finish these. A branch is owned when a ``running``
    work-queue record names it (or the worktree it is checked out in, in whatever
    spelling), or when its linked worktree is locked by git or sits under the harness's
    ``.claude/worktrees/`` directory, where a plain background sub-agent works with no
    work-queue record. The harness-directory signal is not honoured for a branch in
    ``own`` (the stopping thread touched it itself): that branch is handed over only on
    the holds ``worktree-reap`` honours, a queue record or a git lock (Plan 00618 B-2),
    and is reported in ``newly_judged``. When the worktrees cannot be listed only the
    queue's branch names apply and nothing is newly judged; an unreadable queue
    contributes nothing, so every finding stands.
    """
    holds = running_holds(untracked, repo)
    try:
        records = linked_worktree_records(repo)
    except RuntimeError as exc:
        log_and_continue(
            logger,
            exc,
            reason="branch_stop_guard: the worktrees cannot be listed, so only branches a "
            "running work-queue record names are handed over",
        )
        return HandOver(holds.branches, {})
    owned: set[str] = set()
    newly_judged: dict[str, Path] = {}
    for name, record in records.items():
        if ownership_refusal(name, record.path, locked=record.locked, holds=holds) is None:
            continue
        held = ownership_refusal(
            name, record.path, locked=record.locked, holds=holds, harness_directory=False
        )
        if name not in own or held is not None:
            owned.add(name)
        else:
            newly_judged[name] = record.path
    return HandOver(holds.branches | owned, newly_judged)


def _hold_remedies(finding: StopFinding, worktree: Path) -> StopFinding:
    """``finding`` with remedies that never commit inside a live agent's worktree."""
    queue_add = daemon_cli_command_for_docs(
        "work-queue",
        "add",
        "<agent-name>",
        "--worktree",
        str(worktree),
        "--branch",
        finding.branch,
        "--brief",
        "...",
    )
    return replace(
        finding,
        commands=(
            f"if an agent is still working in it, hand it over: git worktree lock {worktree}",
            f"or give that agent a running work-queue record: {queue_add}",
            "if no agent works in it, it is this session's own work: finish it from inside "
            "that worktree like any other branch",
        ),
    )


def live_session_agents(
    untracked: Path,
    *,
    session_id: str,
    agent_id: str | None,
    transcript_path: str,
    background_tasks: object,
    now: float,
) -> tuple[LiveAgent, ...]:
    """The session's sub-agents verifiably still working, the stopping agent excluded (N758).

    Read from daemon state only: an ``agent-<id>.jsonl`` transcript in the session's
    sub-agent directory that moved within ``Timeout.STOP_GUARD_AGENT_SILENCE``, whose
    turn has not ended, which could be read (``strict``), and which neither the
    recorded ``background_tasks`` nor this payload's reports as no longer running.
    No transcript path means no reading, so the stop is judged as it always was.
    """
    directory = subagents_dir(transcript_path, session_id)
    if directory is None:
        return ()
    finished = finished_agents(untracked, session_id) | (
        finished_task_ids(background_tasks) or frozenset()
    )
    live = live_agents(
        directory,
        liveness_seconds=Timeout.STOP_GUARD_AGENT_SILENCE,
        now=now,
        finished=finished,
        strict=True,
    )
    return tuple(agent for agent in live if agent.agent_id != agent_id)


def _label(agent: LiveAgent) -> str:
    return f"{agent.name} ({agent.agent_id})" if agent.name else agent.agent_id


def _labels(agents: tuple[LiveAgent, ...]) -> str:
    return ", ".join(_label(agent) for agent in agents)


def _in_flight(
    blocking: list[StopFinding],
    touched_by: dict[str, frozenset[str]],
    live: tuple[LiveAgent, ...],
) -> dict[str, tuple[LiveAgent, ...]]:
    """Each blocking branch a live sub-agent of the session touched, with those agents."""
    flying: dict[str, tuple[LiveAgent, ...]] = {}
    for name in sorted({finding.branch for finding in blocking}):
        authors = touched_by.get(name, frozenset()) - {_MAIN_TOUCH}
        agents = tuple(agent for agent in live if agent.agent_id in authors)
        if agents:
            flying[name] = agents
    return flying


def _in_flight_line(branch: str, agents: tuple[LiveAgent, ...]) -> str:
    return (
        f"Branch in flight (not abandoned): {branch}: a live agent of this session is "
        f"working on it: {_labels(agents)}. Do not stage or commit its files from here; "
        f"{_LEAVE_IT_TO_THE_AGENT}."
    )


def _shared_tree_remedies(finding: StopFinding, live: tuple[LiveAgent, ...]) -> StopFinding:
    """A dirty finding's remedies when another agent of the session is live: never ``add -A``.

    A blanket add would sweep that agent's half-done files into this commit.
    """
    if not live or finding.check != StopCheck.DIRTY or finding.worktree is None:
        return finding
    tree = shlex.quote(str(finding.worktree))
    return replace(
        finding,
        commands=(
            f"a live agent of this session ({_labels(live)}) may hold some of these files: "
            f"stage only your own, by name: git -C {tree} add -- <path>...",
            f"git -C {tree} commit",
            f"or {_LEAVE_IT_TO_THE_AGENT}",
        ),
    )


def _record_in_flight(state: dict[str, Any], flying: dict[str, tuple[LiveAgent, ...]]) -> bool:
    """Record the in-flight branches, or clear an older record; True when ``state`` changed."""
    if flying:
        names = sorted(flying)
        logger.info("branch_stop_guard: in flight with a live agent at stop: %s", ", ".join(names))
        state[_IN_FLIGHT_KEY] = names
        return True
    return state.pop(_IN_FLIGHT_KEY, None) is not None


def decide_stop(
    repo: Path,
    branches: BranchesConfig,
    untracked: Path,
    *,
    session_id: str,
    agent_id: str | None,
    handoff: bool,
    now: float,
    transcript_path: str = "",
    background_tasks: object = None,
) -> StopDecision:
    """Judge a stop; every failure to judge allows the stop rather than holding it.

    ``transcript_path`` and ``background_tasks`` come from the stop payload and feed
    :func:`live_session_agents`: a branch a live sub-agent of the session touched is
    in flight (reported, never held or recorded as abandoned), and while any such
    agent is live no remedy stages a whole worktree.
    """
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
    # N581: the coordinator cannot finish a branch a live agent owns (a running queue
    # record, or a locked or harness-directory worktree), so it is handed over, not left
    # behind. A branch it touched itself needs a queue record or a lock (Plan 00618 B-2).
    # A sub-agent's own stop is still judged in full.
    over_to = (
        _hand_over(repo, untracked, own=judgement.own)
        if agent_id is None
        else HandOver(frozenset(), {})
    )
    handed = over_to.handed
    newly = over_to.newly_judged
    findings = [
        _hold_remedies(f, newly[f.branch]) if f.branch in newly else f
        for f in judgement.findings
        if f.branch not in handed
    ]
    blocking = [f for f in findings if not f.advisory]
    advisory = [f for f in findings if f.advisory]
    # N758: read only when something would hold the stop, so a clean stop pays nothing.
    live = (
        live_session_agents(
            untracked,
            session_id=session_id,
            agent_id=agent_id,
            transcript_path=transcript_path,
            background_tasks=background_tasks,
            now=now,
        )
        if blocking
        else ()
    )
    flying = _in_flight(blocking, judgement.touched_by, live)
    # A newly judged harness branch already names only hold remedies; keep them.
    blocking = [
        f if f.branch in newly else _shared_tree_remedies(f, live)
        for f in blocking
        if f.branch not in flying
    ]
    context: list[str] = [
        f"Branch left behind (advisory): {f.branch}: {f.check.value}" for f in advisory
    ]
    over = sorted({f.branch for f in judgement.findings if f.branch in handed})
    if over:
        context.append("Branches handed over to running agents (not abandoned): " + ", ".join(over))
    context.extend(_in_flight_line(name, agents) for name, agents in flying.items())
    state_changed = _record_in_flight(state, flying)
    reason: str | None = None
    if blocking and branches.stop_guard.mode == "warn":
        context.extend(f"Branch left behind: {f.branch}: {f.check.value}" for f in blocking)
    elif blocking:
        # Plan 00618 B-2: a stop refused ONLY on newly judged branches counts on its own
        # capped counter; any other refusal is one the pre-B-2 gate made too, and counts
        # on the main counter, which therefore matches that gate stop for stop.
        key = _HARNESS_BLOCKS_KEY if all(f.branch in newly for f in blocking) else _BLOCKS_KEY
        blocks = _int(state.get(key))
        if blocks < MAX_STOP_BLOCKS:
            state[key] = blocks + 1
            reason = _deny_reason(blocking, judgement.tips, block=blocks + 1, handoff=handoff)
        else:
            context.extend(_record_given_way(state, blocking))
    if reason is None and agent_id is None:
        context.extend(_noisy_context(inventory, state, now=now))
    if state or state_changed:
        write_state(state_file, state)
    if agent_id is None:
        # Plan 00619: the warning ladder, from the first warning up to the block. Context
        # only and read AFTER the decision and its counter are settled and persisted: it
        # holds nothing, and it cannot raise (a failed read is no lines), so the stop
        # decision above is exactly the one it was before the ladder existed.
        context.extend(ladder_notice(repo, branches, session_id=None, throttle=None, now=now))
    return StopDecision(reason, tuple(context))
