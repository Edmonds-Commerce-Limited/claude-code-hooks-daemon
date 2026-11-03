"""Judge the branches a stopping session or sub-agent leaves behind (Plan 00558 Task 4.4).

DESIGN.md section 6. The branches judged are the ones the touch records
(:mod:`core.branch_records`) name for the stopping identity; the checks are a
dirty worktree, commits no remote holds, and a branch that is merged but not
deleted. A sub-agent is judged on its own branches. The coordinator is judged on
its own branches, and also owns what its sub-agents leave behind: their unpushed
and merged-but-present branches (not their dirty worktrees).

Every git call here runs inside one fixed budget
(``Timeout.GIT_STOP_GUARD_BUDGET``). When it runs out, the branches not yet
judged are reported through ``StopJudgement.incomplete`` and never as findings:
an unjudged branch is not a defect.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchInventory,
    BranchRecord,
    BranchState,
)
from claude_code_hooks_daemon.core.branch_records import touched_by_session
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import run_git

logger = logging.getLogger(__name__)

_DONE_STATES = frozenset(
    {BranchState.MERGED_DEFAULT, BranchState.MERGED_LINE, BranchState.PATCH_EQUIVALENT}
)
#: Branches that are never a session's work, whatever the touch record says.
_NEVER_JUDGED = frozenset({BranchState.EXEMPT, BranchState.PROTECTED})
#: Default and integration lines: judged only with ``include_default``.
_LINES = frozenset({BranchState.DEFAULT, BranchState.INTEGRATION_LINE})


class StopCheck(StrEnum):
    """The three checks of DESIGN.md section 6."""

    DIRTY = "dirty worktree"
    UNPUSHED = "commits no remote holds"
    MERGED = "merged but not deleted"


@dataclass(frozen=True)
class StopFinding:
    """One failed check on one branch, with the commands that finish it."""

    branch: str
    check: StopCheck
    tip: str
    commands: tuple[str, ...]
    #: True when the finding is reported but does not hold the stop.
    advisory: bool = False


@dataclass(frozen=True)
class StopJudgement:
    """What the guard found, the tip of every branch it judged, and whether it finished."""

    findings: tuple[StopFinding, ...]
    tips: dict[str, str]
    incomplete: bool = False


class _GitResult(Protocol):
    """The two fields read off a finished git command.

    Stated structurally because nothing here spawns a process: ``run_git``
    owns every git invocation, so importing ``subprocess`` only to name its
    return type would advertise a capability this module does not have.
    """

    returncode: int
    stdout: str


class _Budget:
    """A deadline shared by every git call of one judgement."""

    def __init__(self, seconds: float) -> None:
        self._deadline = time.monotonic() + seconds

    def git(self, cwd: Path, *args: str) -> _GitResult | None:
        """Run git, or None when the budget is spent."""
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            return None
        return run_git(cwd, *args, timeout=min(Timeout.GIT_CONTEXT, remaining))


def _scope(touches: dict[str, set[str]], agent_id: str | None) -> tuple[set[str], set[str]]:
    """``(own, owned)``: branches judged in full, and sub-agent branches the coordinator owns."""
    who = agent_id or ""
    own = {name for name, agents in touches.items() if who in agents}
    if agent_id:
        return own, set()
    return own, {name for name, agents in touches.items() if agents - {""}} - own


def _judgeable(record: BranchRecord | None, config: BranchesConfig) -> bool:
    if record is None or record.local_tip is None or record.state in _NEVER_JUDGED:
        return False
    return config.stop_guard.include_default or record.state not in _LINES


def _merged_commands(record: BranchRecord, remote: str) -> tuple[str, ...]:
    commands: list[str] = []
    if record.worktree is not None:
        commands.append(f"git worktree remove {record.worktree}")
    commands.append(f"git branch -d {record.name}")
    if record.remote_tip is not None:
        commands.append(f"git push {remote} --delete {record.name}")
    return tuple(commands)


def _is_dirty(record: BranchRecord, budget: _Budget) -> bool | None:
    """Whether the branch's worktree has changes; None when unknown or out of budget."""
    if record.worktree is None:
        return False
    result = budget.git(record.worktree, "status", "--porcelain")
    if result is None or result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _held_by_remote(repo: Path, tip: str, budget: _Budget) -> bool | None:
    result = budget.git(
        repo, "for-each-ref", "--contains", tip, "--format=%(refname)", "refs/remotes/"
    )
    if result is None or result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _in_local_default(repo: Path, tip: str, default: str, budget: _Budget) -> bool | None:
    result = budget.git(repo, "merge-base", "--is-ancestor", tip, f"refs/heads/{default}")
    if result is None or result.returncode not in (0, 1):
        return None
    return result.returncode == 0


def _unpushed(
    repo: Path, record: BranchRecord, inventory: BranchInventory, budget: _Budget
) -> bool | None:
    """Whether the tip is on no remote and not handed over to the local default branch."""
    tip = record.local_tip or ""
    held = _held_by_remote(repo, tip, budget)
    if held is None or held:
        return None if held is None else False
    if record.state in _LINES or inventory.default_branch is None:
        return True
    handed = _in_local_default(repo, tip, inventory.default_branch, budget)
    return None if handed is None else not handed


def judge_stop(
    repo: Path,
    inventory: BranchInventory,
    config: BranchesConfig,
    *,
    session_id: str,
    agent_id: str | None,
    handoff: bool = False,
    budget: float = Timeout.GIT_STOP_GUARD_BUDGET,
) -> StopJudgement:
    """Judge the branches this session (main thread) or this sub-agent touched.

    ``handoff`` is the hard-context-band path: the merged-but-not-deleted check
    is waived, because the work continues in a fresh agent.
    """
    try:
        touches = touched_by_session(repo, session_id)
    except RuntimeError as exc:
        log_and_continue(
            logger,
            exc,
            reason="branch_stop_guard: the touch records are unreadable, so no branch can "
            "be judged; the stop is allowed rather than held on a git failure",
        )
        return StopJudgement((), {}, incomplete=True)
    own, owned = _scope(touches, agent_id)
    clock = _Budget(budget)
    findings: list[StopFinding] = []
    tips: dict[str, str] = {}
    incomplete = False
    for name in sorted(own | owned):
        record = inventory.records.get(name)
        if record is None or not _judgeable(record, config):
            continue
        tip = record.local_tip or ""
        tips[name] = tip
        found, finished = _judge_branch(
            repo,
            record,
            inventory,
            config,
            clock,
            full=name in own,
            subagent=agent_id is not None,
            handoff=handoff,
        )
        findings.extend(found)
        incomplete = incomplete or not finished
    return StopJudgement(tuple(findings), tips, incomplete)


#: Reflog subjects that move a branch without adding work of its own: its
#: creation, a fast-forward onto commits that already exist, a reset, a rename.
#: Anything else (a commit, a real merge, a cherry-pick, an unlabelled
#: update-ref) counts as work, so an unknown entry still reports the branch.
_NO_WORK_REFLOG = re.compile(
    r"^(branch: Created from |branch: Reset to |Branch: renamed |reset: moving to "
    r"|(merge|pull)\b[^:]*: Fast-forward)"
)


def _never_worked(repo: Path, name: str, budget: _Budget) -> bool:
    """True when no reflog entry of the branch added work: nothing of its own was merged.

    A worktree branch made for a sub-agent sits at the default tip until its
    first commit, and a `merge --ff-only main` only moves it to another commit
    main already has; ancestry reads both as merged. An unreadable reflog
    answers False, so the branch is still reported.
    """
    result = budget.git(repo, "reflog", "show", "--format=%gs", f"refs/heads/{name}", "--")
    if result is None or result.returncode != 0:
        return False
    # Keep empty subjects: an unlabelled ref update is work, not noise.
    subjects = result.stdout.rstrip("\n").split("\n") if result.stdout else []
    return bool(subjects) and all(_NO_WORK_REFLOG.match(s) for s in subjects)


def _judge_branch(
    repo: Path,
    record: BranchRecord,
    inventory: BranchInventory,
    config: BranchesConfig,
    budget: _Budget,
    *,
    full: bool,
    subagent: bool,
    handoff: bool,
) -> tuple[list[StopFinding], bool]:
    """The findings on one branch, and whether every check could run."""
    tip = record.local_tip or ""
    findings: list[StopFinding] = []
    finished = True
    merged = record.state in _DONE_STATES
    if full:
        dirty = _is_dirty(record, budget)
        finished = finished and dirty is not None
        if dirty:
            findings.append(
                StopFinding(
                    record.name,
                    StopCheck.DIRTY,
                    tip,
                    (f"git -C {record.worktree} add -A", f"git -C {record.worktree} commit"),
                )
            )
    if merged:
        if not handoff and not _never_worked(repo, record.name, budget):
            findings.append(
                StopFinding(
                    record.name, StopCheck.MERGED, tip, _merged_commands(record, config.remote)
                )
            )
        return findings, finished
    mode = config.stop_guard.unpushed_subagent if subagent and full else "block"
    if mode == "off":
        return findings, finished
    unpushed = _unpushed(repo, record, inventory, budget)
    finished = finished and unpushed is not None
    if unpushed:
        findings.append(
            StopFinding(
                record.name,
                StopCheck.UNPUSHED,
                tip,
                (f"git push -u {config.remote} {record.name}",),
                advisory=mode == "advise",
            )
        )
    return findings, finished
