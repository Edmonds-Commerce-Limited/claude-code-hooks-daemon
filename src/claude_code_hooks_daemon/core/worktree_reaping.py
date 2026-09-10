"""Decide whether an agent worktree is safe to remove.

Agent worktrees under ``.claude/worktrees/`` outlive the session that created
them and nothing removes them, so they accumulate: this repo reached 21, of
which every one was stale (Plan 00349, Task 1.1). The cost is disk and
legibility — a *live* agent worktree becomes hard to spot among the dead ones,
which matters because the isolation advice for concurrent agents depends on
seeing them.

**Unknown means not reapable, and that rule costs something on purpose.** Of
the 21, six were provably safe: their one apparently-unlanded commit had landed
on ``main`` under a different SHA after a rebase, and their one staged file was
a superseded draft of a *gitignored* file. But establishing that took reading a
commit subject, checking a plan folder's location, and comparing byte counts —
judgements this predicate cannot make. From here, a rebased-and-landed commit
and genuinely unlanded work look identical. So it refuses, and the caller
surfaces those for a human rather than reaping them.

The alternative — teaching it that ignored files or already-landed patches do
not count — would have cleared those six correctly and then been wrong the
first time an agent staged something that mattered. A reaper that is
occasionally too cautious wastes disk; one that is occasionally too eager
destroys work that exists nowhere else.

**Plan 00372: a worktree with no history of its own is not evidence that it
is finished.** A worktree created moments earlier for an actively-working
agent has no uncommitted paths, no commits ahead and no unlanded patches — it
looks EXACTLY like one of the 15 stale-and-clean worktrees above, because
nothing about git's own state distinguishes "just started" from "finished
long ago". Two independent signals close that gap, neither derived from git's
tracked state: a live process whose working directory is inside the worktree
(``/proc/*/cwd`` — never a ``pgrep -f`` pattern, which this project already
forbids for matching the searching process's own argv), and a minimum age
below which a history-free worktree is refused regardless of what else is
true about it.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from claude_code_hooks_daemon.core.worktree_paths import WORKTREE_DIR_PATTERNS
from claude_code_hooks_daemon.utils.git_repo import run_git, strip_branch_ref


class GitResult(Protocol):
    """The three fields this module reads off a finished git command.

    Stated structurally rather than as ``subprocess.CompletedProcess`` because
    that is the true dependency: nothing here spawns a process — ``run_git``
    owns every git invocation in the daemon (Plan 00246) — and importing
    ``subprocess`` merely to name a return type would advertise a capability
    this module does not have, to readers and to the security scanner alike.
    """

    returncode: int
    stdout: str
    stderr: str


#: Stands in for a count git could not supply. NEGATIVE on purpose: every
#: refusal rule below tests `!= 0`, so a collection failure can never be read
#: as "nothing to lose" no matter which rule sees it first.
UNKNOWN_COUNT = -1

#: `git status --porcelain` prefixes each path with two status characters and a
#: space (`A  path`, `?? path`).
_STATUS_PREFIX_WIDTH = 3

#: The two `git worktree list --porcelain` lines this module reads. Each record
#: opens with `worktree <path>` and, unless the worktree is detached, carries a
#: `branch refs/heads/<name>` line naming what it has checked out.
_WORKTREE_LINE_PREFIX = "worktree "
_BRANCH_LINE_PREFIX = "branch refs/heads/"

RunGit = Callable[..., GitResult]

#: pid -> resolved cwd, for every process this user can introspect.
ProcessCwds = Mapping[int, Path]
ProcessCwdsFn = Callable[[], ProcessCwds]
#: Seconds since a worktree was created, or None when that could not be
#: determined (a collection failure, never read as "old enough").
WorktreeAgeFn = Callable[[Path], "float | None"]

#: Below this, a history-free worktree is exactly as consistent with "just
#: created, about to be worked in" as with "finished seconds after being
#: created" — every check above sees identical state for both, so age is what
#: tells them apart. Generous on purpose: the cost of waiting longer to reap a
#: genuinely finished worktree is disk; the cost of guessing wrong the other
#: way is unrecoverable work (Plan 00372).
MINIMUM_AGE_SECONDS = 15 * 60

#: Read once per collection run, not once per worktree — see
#: `default_process_cwds`.
_PROC_ROOT = Path("/proc")


def default_process_cwds() -> ProcessCwds:
    """pid -> resolved cwd, read from `/proc/<pid>/cwd`.

    Named without a leading underscore, unlike this module's other private
    helpers: `cmd_worktree_reap` needs to reference the SAME default a caller
    would get by omitting `process_cwds_fn` entirely, to resolve its own
    Optional CLI-testability parameter — exactly how `run_git` already serves
    that role for `run_fn`.

    The only route to "who is sitting in this directory right now" that does
    not depend on the command a process was launched with — unlike a
    `pgrep -f` pattern match, a symlink read cannot be fooled by argv text and
    cannot match the reader's own search string (this project already forbids
    exactly that self-match failure mode for process probes). Silently skips
    a pid this process cannot introspect — permission, or the process exited
    between listing and reading — rather than failing the whole scan; a
    process this call cannot see cannot be reported as live either way.

    Returns an empty mapping when `/proc` itself is unavailable (a non-Linux
    host) rather than raising: the age gate stays a real, independent check
    on a platform without `/proc`, so losing this one signal does not turn
    into losing both.
    """
    if not _PROC_ROOT.is_dir():
        return {}
    caller_pid = os.getpid()
    cwds: dict[int, Path] = {}
    for entry in _PROC_ROOT.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == caller_pid:
            # Never let the reaper's own process count as evidence that a
            # worktree it happens to be running from inside is "live".
            continue
        try:
            cwds[pid] = (entry / "cwd").resolve(strict=True)
        except OSError:
            continue
    return cwds


def _live_pids_under(path: Path, process_cwds: ProcessCwds) -> tuple[int, ...]:
    """pids from `process_cwds` whose cwd is `path` itself or inside it."""
    resolved = path.resolve()
    return tuple(
        sorted(
            pid for pid, cwd in process_cwds.items() if cwd == resolved or resolved in cwd.parents
        )
    )


def default_worktree_age(path: Path) -> float | None:
    """Seconds since `path` was created by `git worktree add`, or None.

    A linked worktree's `.git` is a plain pointer FILE git writes once at
    creation time and does not touch again for ordinary `status`/`add`/
    `commit` operations inside the worktree — verified live (Plan 00372: the
    file's mtime was byte-identical before and after a commit made seconds
    later) rather than assumed. That makes its mtime a cheap, accurate proxy
    for "how old is this worktree", with no extra git subprocess.

    Named without a leading underscore for the same reason as
    `default_process_cwds`: `cmd_worktree_reap` needs to reference this exact
    default to resolve its own Optional CLI-testability parameter.
    """
    try:
        created_at = (path / ".git").stat().st_mtime
    except OSError:
        return None
    return max(0.0, time.time() - created_at)


@dataclass(frozen=True)
class WorktreeState:
    """What a collector observed about one worktree.

    Deliberately plain data, so the decision is testable without a git
    repository and the git-running half can be exercised separately.

    Attributes:
        name: The worktree's directory name, used in the refusal message.
        path: Where git says the worktree is. Carried rather than rebuilt from
            `name`: BOTH `.claude/worktrees/` and `untracked/worktrees/` are
            sanctioned roots (`core.worktree_paths.WORKTREE_DIR_PATTERNS`), so
            a caller reconstructing the path has to pick one and is wrong about
            the other half of them.
        branch: The branch the worktree has checked out, bare, or None when it
            is detached. Also carried rather than assumed equal to `name`: git
            names the directory and the branch separately and nothing keeps
            them in step, so acting on `name` can address an unrelated branch.
        uncommitted_paths: Paths `git status --porcelain` reports — staged,
            unstaged or untracked, all treated alike.
        commits_ahead_of_base: `git rev-list --count <base>..HEAD`.
        unlanded_patches: `git cherry <base> HEAD` lines marked `+`. Recorded
            because it is the far more accurate signal of real divergence, but
            it is NOT trusted to clear a worktree on its own — see the module
            docstring.
        live_process_pids: pids of processes whose cwd is this worktree's path
            or somewhere inside it, sorted. Empty means none were found — NOT
            "unknown", since `/proc` being unavailable already collapses to an
            empty mapping upstream (Plan 00372).
        age_seconds: Seconds since the worktree was created, or `None` when
            that could not be determined — never read as "old enough" (Plan
            00372, same UNKNOWN-is-not-safe rule as the counts above).
    """

    name: str
    path: Path
    branch: str | None
    uncommitted_paths: tuple[str, ...]
    commits_ahead_of_base: int
    unlanded_patches: int
    live_process_pids: tuple[int, ...]
    age_seconds: float | None


def reap_refusal_reason(state: WorktreeState) -> str | None:
    """Why this worktree must be kept, or ``None`` when it is safe to remove.

    Every applicable problem is reported, not just the first: a caller that
    fixed one and re-ran to discover the next would spend a cycle per problem.
    """
    problems: list[str] = []

    if state.uncommitted_paths:
        listed = ", ".join(state.uncommitted_paths)
        problems.append(f"{len(state.uncommitted_paths)} uncommitted path(s): {listed}")

    # A negative count cannot come from git; it means the collector failed and
    # substituted a sentinel. Reading that as "zero commits ahead" would turn a
    # collection failure into a deletion.
    if state.commits_ahead_of_base != 0:
        problems.append(f"{state.commits_ahead_of_base} commit(s) not on the base branch")

    if state.unlanded_patches != 0:
        problems.append(f"{state.unlanded_patches} patch(es) git cherry cannot find on the base")

    if state.live_process_pids:
        pids = ", ".join(str(pid) for pid in state.live_process_pids)
        noun = "pid" if len(state.live_process_pids) == 1 else "pids"
        problems.append(f"a live process has its working directory inside it ({noun} {pids})")

    # None means the collector could not determine an age — treated the same
    # as "too young", not as "old enough", for the same reason a negative
    # count above is never read as "nothing to lose".
    if state.age_seconds is None:
        problems.append("its creation time could not be determined")
    elif state.age_seconds < MINIMUM_AGE_SECONDS:
        problems.append(
            f"created {int(state.age_seconds)}s ago, under the {MINIMUM_AGE_SECONDS}s "
            "minimum age a worktree with no history of its own needs before it "
            "can be told apart from one that just started"
        )

    if not problems:
        return None

    return (
        f"{state.name} is not safe to reap: "
        + "; ".join(problems)
        + ". Inspect it and remove it by hand if the work is accounted for — "
        "a rebased commit that already landed looks exactly like one that did "
        "not, so this check cannot tell them apart."
    )


def is_reapable(state: WorktreeState) -> bool:
    return reap_refusal_reason(state) is None


@dataclass(frozen=True)
class _WorktreeEntry:
    """One `git worktree list --porcelain` record, as far as this module reads it."""

    path: Path
    branch: str | None


def _worktree_entries(listing: str, repo_root: Path) -> list[_WorktreeEntry]:
    """The agent worktrees in `git worktree list --porcelain` output.

    The main checkout appears in that listing too and must never become a reap
    candidate, so records are kept only when their path sits under one of the
    sanctioned worktree directories — the same tuple the path-classifying
    helpers use.

    The path and the branch are both taken from the listing rather than derived
    from the directory name afterwards. Git already answered both questions
    here; re-deriving either is a guess, and each has a wrong answer available
    (the other sanctioned root, and a same-named branch that is not this
    worktree's).
    """
    entries: list[_WorktreeEntry] = []
    # Every line after a `worktree` line belongs to THAT record, so a branch
    # line must be ignored entirely while the record it describes is one this
    # collector skipped — otherwise the main checkout's `refs/heads/main` would
    # attach itself to whichever agent worktree happened to precede it.
    collecting = False
    for line in listing.splitlines():
        if line.startswith(_WORKTREE_LINE_PREFIX):
            candidate = line[len(_WORKTREE_LINE_PREFIX) :].strip()
            relative = candidate[len(str(repo_root)) :].lstrip("/")
            collecting = any(relative.startswith(pattern) for pattern in WORKTREE_DIR_PATTERNS)
            if collecting:
                entries.append(_WorktreeEntry(path=Path(candidate), branch=None))
        elif collecting and line.startswith(_BRANCH_LINE_PREFIX):
            branch = line[len(_BRANCH_LINE_PREFIX) :].strip()
            entries[-1] = replace(entries[-1], branch=branch)
    return entries


def _count(result: GitResult) -> int:
    """A git count, or :data:`UNKNOWN_COUNT` when git could not supply one.

    Covers both failure shapes: a non-zero exit, and a zero exit whose output
    is not an integer. Neither is treated as absence of divergence — that would
    turn a collection failure into a deletion.
    """
    if result.returncode != 0:
        return UNKNOWN_COUNT
    try:
        return int(result.stdout.strip())
    except ValueError:
        return UNKNOWN_COUNT


def _unlanded(result: GitResult) -> int:
    """`git cherry` lines marked `+`, or :data:`UNKNOWN_COUNT` on failure.

    `-` means git found an equivalent patch already on the base.
    """
    if result.returncode != 0:
        return UNKNOWN_COUNT
    return sum(1 for line in result.stdout.splitlines() if line.startswith("+"))


def collect_worktree_states(
    repo_root: Path,
    base_branch: str,
    *,
    run_fn: RunGit = run_git,
    process_cwds_fn: ProcessCwdsFn = default_process_cwds,
    age_fn: WorktreeAgeFn = default_worktree_age,
) -> tuple[WorktreeState, ...]:
    """Read each agent worktree's state from git, `/proc` and the filesystem.

    Read-only: this asks questions and removes nothing. Pair it with
    :func:`is_reapable` to decide, and leave acting to an explicit caller.

    Returns an empty tuple when the listing itself cannot be read — with no
    listing there are no candidates, which is the safe answer rather than a
    guess.
    """
    listing = run_fn(repo_root, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return ()

    # One /proc scan serves every worktree in this run, not one per worktree.
    process_cwds = process_cwds_fn()

    states = []
    for entry in _worktree_entries(listing.stdout, repo_root):
        path = entry.path
        status = run_fn(path, "status", "--porcelain")
        uncommitted = (
            tuple(line[_STATUS_PREFIX_WIDTH:] for line in status.stdout.splitlines() if line)
            if status.returncode == 0
            # An unreadable status is not an empty one. A sentinel path keeps
            # the refusal explicit and names why in the message.
            else ("<git status failed, so the worktree could not be checked>",)
        )
        states.append(
            WorktreeState(
                name=path.name,
                path=path,
                branch=entry.branch,
                uncommitted_paths=uncommitted,
                commits_ahead_of_base=_count(
                    run_fn(path, "rev-list", "--count", f"{base_branch}..HEAD")
                ),
                unlanded_patches=_unlanded(run_fn(path, "cherry", base_branch, "HEAD")),
                live_process_pids=_live_pids_under(path, process_cwds),
                age_seconds=age_fn(path),
            )
        )
    return tuple(states)


@dataclass(frozen=True)
class ReapOutcome:
    """What happened to one worktree, in terms a report can print directly."""

    name: str
    removed: bool
    branch_removed: bool
    detail: str


def reap_worktree(
    repo_root: Path,
    state: WorktreeState,
    *,
    run_fn: RunGit = run_git,
    dry_run: bool = False,
) -> ReapOutcome:
    """Remove one worktree and its branch, if the predicate cleared it.

    **Git is asked to disagree, twice.** ``git worktree remove`` runs WITHOUT
    ``--force``, so git refuses a worktree carrying modified or untracked
    files; the branch is deleted with ``-d``, never ``-D``, so git refuses one
    that is not fully merged. If :func:`is_reapable` were ever wrong, two
    independent checks still stand between it and lost work — a reap path whose
    only safety is the predicate has a single bug between it and a deletion.
    (``-D`` is a blocked operation in this project for the same reason.)

    A git refusal is REPORTED, never retried with force. That is the whole
    value of asking.

    Both the worktree and the branch are addressed with what the collector read
    out of git, never with anything rebuilt from the directory name — see
    :class:`WorktreeState`.
    """
    refusal = reap_refusal_reason(state)
    if refusal is not None:
        return ReapOutcome(state.name, removed=False, branch_removed=False, detail=refusal)

    if dry_run:
        return ReapOutcome(
            state.name,
            removed=False,
            branch_removed=False,
            detail=(
                f"would remove {state.path} and its branch {state.branch}"
                if state.branch is not None
                else f"would remove {state.path}, which has no branch attached"
            ),
        )

    removal = run_fn(repo_root, "worktree", "remove", str(state.path))
    if removal.returncode != 0:
        # git overruled the predicate. Leaving the branch alone is deliberate:
        # a branch whose worktree still exists is not clutter, it is in use.
        return ReapOutcome(
            state.name,
            removed=False,
            branch_removed=False,
            detail=f"git refused to remove {state.path}: {removal.stderr.strip()}",
        )

    if state.branch is None:
        # A detached worktree has no branch to delete, and deleting one named
        # after its directory would act on a ref the predicate never cleared.
        return ReapOutcome(
            state.name,
            removed=True,
            branch_removed=False,
            detail=f"removed {state.path}; it had no branch attached, so none was deleted",
        )

    # Task 2.3: a removed worktree that leaves its branch behind has only moved
    # the clutter from `git worktree list` to `git branch`. Addressed by the
    # BARE name, deliberately NOT `branch_ref()`: unlike the general
    # ref-resolving commands `branch_ref()` exists for (`rev-parse`, `cherry`,
    # `merge-base`), `git branch -d` resolves its argument only inside
    # `refs/heads/` and REJECTS an already-qualified `refs/heads/<name>`
    # outright — verified live (Plan 00372) after a full-ref argument here
    # made every branch delete fail with "not found", never once succeeding.
    branch = run_fn(repo_root, "branch", "-d", state.branch)
    if branch.returncode != 0:
        return ReapOutcome(
            state.name,
            removed=True,
            branch_removed=False,
            detail=(
                f"removed {state.path}, but git kept the branch {state.branch}: "
                f"{branch.stderr.strip()}"
            ),
        )

    return ReapOutcome(
        state.name,
        removed=True,
        branch_removed=True,
        detail=f"removed {state.path} and its branch {state.branch}",
    )


#: The naming shape agent dispatch uses (`agent-<hex>-<hex>`). Scoped to it on
#: purpose: Plan 00349 and Plan 00048 both declined a general branch-pruning
#: policy, and Plan 00352 inherits that boundary rather than widening it.
AGENT_BRANCH_GLOB = "agent-*"

#: List with the FULL refname and strip it. `%(refname:short)` yields the
#: shortest UNAMBIGUOUS name, so a branch sharing its name with a tag comes back
#: as `heads/<name>` — a string no git command accepts, which silently breaks
#: every membership test and every `git branch -d` built from it. Plan 00254
#: reproduced the cost: a tag patch-equivalent to a protected ref got a branch
#: holding the only copy of a file force-deleted.
_BRANCH_FORMAT = "--format=%(refname)"


@dataclass(frozen=True)
class OrphanedBranch:
    """An `agent-*` branch that no worktree points at.

    Attributes:
        name: The branch name.
        merged_into_base: Whether `git branch --merged <base>` lists it. False
            also covers "git could not tell us", because a branch we cannot
            classify must not be deleted.
    """

    name: str
    merged_into_base: bool


def _branch_names(result: GitResult) -> list[str] | None:
    """Bare branch names from a `--format=%(refname)` listing, or None on failure."""
    if result.returncode != 0:
        return None
    return [strip_branch_ref(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def _attached_branches(listing: str) -> set[str]:
    """Branches that `git worktree list --porcelain` reports a worktree for."""
    return {
        line[len(_BRANCH_LINE_PREFIX) :].strip()
        for line in listing.splitlines()
        if line.startswith(_BRANCH_LINE_PREFIX)
    }


def collect_orphaned_branches(
    repo_root: Path, base_branch: str, *, run_fn: RunGit = run_git
) -> tuple[OrphanedBranch, ...]:
    """Agent branches with no worktree, each tagged with its merge status.

    Read-only. Orphaned is defined as the agent branches git lists MINUS the
    branches a worktree points at — which is why this belongs beside the
    worktree collector rather than in a command of its own: the second set is
    exactly what `git worktree list` already had to be read for.

    Returns an empty tuple when either listing fails. Without the worktree
    listing every branch would look orphaned, and without the branch listing
    there is nothing to classify; in both cases no candidates is the safe answer
    rather than a guess.
    """
    listing = run_fn(repo_root, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return ()

    all_names = _branch_names(
        run_fn(repo_root, "branch", "--list", AGENT_BRANCH_GLOB, _BRANCH_FORMAT)
    )
    if all_names is None:
        return ()

    merged_names = _branch_names(
        run_fn(
            repo_root,
            "branch",
            "--merged",
            base_branch,
            "--list",
            AGENT_BRANCH_GLOB,
            _BRANCH_FORMAT,
        )
    )
    # An unreadable --merged listing means the merge status is UNKNOWN. Treating
    # unknown as merged would turn a git failure into a deletion, so every
    # branch is marked unmerged and `prune_branch` refuses the lot.
    merged = set(merged_names) if merged_names is not None else set()

    attached = _attached_branches(listing.stdout)
    return tuple(
        OrphanedBranch(name=name, merged_into_base=name in merged)
        for name in all_names
        if name not in attached
    )


@dataclass(frozen=True)
class PruneOutcome:
    """What happened to one branch, in terms a report can print directly."""

    name: str
    deleted: bool
    detail: str


def prune_branch(
    repo_root: Path,
    branch: OrphanedBranch,
    *,
    run_fn: RunGit = run_git,
    dry_run: bool = False,
) -> PruneOutcome:
    """Delete one orphaned branch, if it is fully merged into the base.

    **Git is asked to disagree**, exactly as :func:`reap_worktree` does: the
    delete is `-d`, never `-D`, so git independently refuses a branch that is
    not fully merged even if the check above was wrong. A git refusal is
    REPORTED, never retried with force — that is the whole value of asking, and
    `-D` is a blocked operation in this project for the same reason.
    """
    if not branch.merged_into_base:
        return PruneOutcome(
            branch.name,
            deleted=False,
            detail=(
                f"{branch.name} is not fully merged into the base branch, or git "
                "could not say. Inspect it and delete it by hand if the work is "
                "accounted for."
            ),
        )

    if dry_run:
        return PruneOutcome(branch.name, deleted=False, detail=f"would delete branch {branch.name}")

    # Addressed by the BARE name, deliberately NOT `branch_ref()`: `git branch
    # -d` resolves its argument only inside `refs/heads/` and REJECTS an
    # already-qualified `refs/heads/<name>` outright — verified live (Plan
    # 00372). `branch_ref()`'s tag-ambiguity rationale (Plan 00254) covers the
    # general ref-resolving commands (`rev-parse`, `cherry`, `merge-base`),
    # never the `branch` subcommand.
    result = run_fn(repo_root, "branch", "-d", branch.name)
    if result.returncode != 0:
        return PruneOutcome(
            branch.name,
            deleted=False,
            detail=f"git kept the branch {branch.name}: {result.stderr.strip()}",
        )
    return PruneOutcome(branch.name, deleted=True, detail=f"deleted branch {branch.name}")
