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
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.branch_cleanup import policy_refusal
from claude_code_hooks_daemon.core.branch_records import WORKTREE_CREATE_ROUTE, creator_route
from claude_code_hooks_daemon.core.worktree_naming import is_worktree_create_name
from claude_code_hooks_daemon.core.worktree_paths import WORKTREE_DIR_PATTERNS
from claude_code_hooks_daemon.daemon.branch_safety import delete_branches, new_bundle_path
from claude_code_hooks_daemon.utils.git_repo import (
    AGENT_BRANCH_PREFIX,
    GIT_TIMED_OUT,
    parse_worktree_porcelain,
    run_git,
    strip_branch_ref,
)
from claude_code_hooks_daemon.utils.load_scaling import scaled_timeout
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to


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

#: The porcelain code for a path git knows nothing about. ONLY this code is a
#: candidate for the generated-output filter below (Plan 00380): `git
#: check-ignore` answers about a PATH and cannot see that the same path is
#: tracked-and-modified inside the worktree, so allowing any other code would
#: let a real modification to an ignorable path be discarded silently.
_UNTRACKED_STATUS_CODE = "??"

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
        sorted(pid for pid, cwd in process_cwds.items() if path_is_relative_to(cwd, resolved))
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
        + ". This is a refusal by THIS command, not a reservation for a human: "
        "`git worktree remove --force <path>` is allowed only when nothing would "
        "be lost (R-GIT-WORKTREE-REMOVE-FORCE names any path that blocks it), so "
        "whoever is reading this — agent or human — can inspect, deal with each "
        "listed path, and remove it. It is accounted for when "
        "`git log --oneline <base>..<branch>` is empty AND every path listed "
        "above is generated output or a change already on the base. The reason "
        "this command will not decide that for you is that a rebased commit "
        "which already landed looks exactly like one that did not."
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
    # The shared parser attaches each branch line to ITS record, so the main
    # checkout's `refs/heads/main` cannot land on a neighbouring agent worktree.
    for record in parse_worktree_porcelain(listing):
        relative = str(record.path)[len(str(repo_root)) :].lstrip("/")
        if any(relative.startswith(pattern) for pattern in WORKTREE_DIR_PATTERNS):
            entries.append(_WorktreeEntry(path=record.path, branch=record.branch))
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


def _ignored_in_main(
    repo_root: Path,
    paths: tuple[str, ...],
    run_fn: RunGit,
) -> frozenset[str]:
    """Which of ``paths`` the MAIN checkout's ignore rules would exclude.

    Asked of ``repo_root`` rather than the worktree on purpose. A worktree's
    ``.gitignore`` is whatever its pinned commit carried, so a generated path
    added to the ignore list afterwards is invisible there — which is precisely
    how four worktrees came to be held by the daemon's own report file. Main is
    the current authority on what counts as generated.

    An empty set on failure, so an unanswerable question can never widen what
    gets reaped — the same doctrine as :data:`UNKNOWN_COUNT`.
    """
    if not paths:
        return frozenset()
    result = run_fn(repo_root, "check-ignore", *paths)
    if result.returncode != 0:
        # Exit 1 legitimately means "none of them", and any other failure means
        # "no answer". Both land here, and both correctly drop nothing.
        return frozenset()
    return frozenset(line for line in result.stdout.splitlines() if line)


def _work_paths(status: GitResult, repo_root: Path, run_fn: RunGit) -> tuple[str, ...]:
    """Uncommitted paths that could be work, generated output excluded.

    An unreadable status is not an empty one, so it becomes a sentinel that
    keeps the refusal explicit and names why. The sentinel is a MESSAGE, not a
    path, so it is never handed to ``git check-ignore``.
    """
    if status.returncode != 0:
        return ("<git status failed, so the worktree could not be checked>",)

    entries = [
        (line[:2], line[_STATUS_PREFIX_WIDTH:]) for line in status.stdout.splitlines() if line
    ]
    untracked = tuple(path for code, path in entries if code == _UNTRACKED_STATUS_CODE)
    generated = _ignored_in_main(repo_root, untracked, run_fn)
    return tuple(
        path for code, path in entries if not (code == _UNTRACKED_STATUS_CODE and path in generated)
    )


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
        uncommitted = _work_paths(status, repo_root, run_fn)
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

    The removal runs under ``Timeout.GIT_WORKTREE_REMOVE``, not ``run_git``'s
    metadata default: it deletes the whole tree. If even that is exceeded, the
    outcome says the removal was interrupted and may be partial, and names the
    recovery (``git worktree prune``, then ``git branch -d``) rather than
    retrying or forcing.

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

    removal_budget = scaled_timeout(Timeout.GIT_WORKTREE_REMOVE, Timeout.GIT_WORKTREE_REMOVE_MAX)
    removal = run_fn(repo_root, "worktree", "remove", str(state.path), timeout=removal_budget)
    if removal.returncode == GIT_TIMED_OUT:
        # git was killed part-way through deleting the tree, so what is on disk
        # is neither the worktree nor its absence. Retrying `worktree remove`
        # fails on the missing `.git`; `prune` forgets the registration instead.
        recovery = "git worktree prune"
        if state.branch is not None:
            recovery += f", then git branch -d {state.branch}"
        return ReapOutcome(
            state.name,
            removed=False,
            branch_removed=False,
            detail=(
                f"removal of {state.path} was interrupted at the "
                f"{removal_budget:.0f} s limit and may be partial: "
                f"{removal.stderr.strip()}. Recover with {recovery}"
            ),
        )
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
    branch = run_fn(
        repo_root,
        "branch",
        "-d",
        state.branch,
        timeout=scaled_timeout(Timeout.GIT_CONTEXT, Timeout.GIT_WORKTREE_CLEANUP_MAX),
    )
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


def is_daemon_created_branch(name: str) -> bool:
    """Whether orphan pruning may consider ``name``: an agent or WorktreeCreate branch.

    Agent dispatch names ``agent-<hex>-<hex>``; WorktreeCreate ``<slug>-<8 hex>``.

    Scoped on purpose: Plans 00349 and 00048 declined a general branch-pruning
    policy, so only names the daemon or agent dispatch generate are eligible
    (Plan 00558 DESIGN.md section 8 adds the ``<slug>-<8 hex>`` names).
    """
    return name.startswith(AGENT_BRANCH_PREFIX) or is_worktree_create_name(name)


#: List with the FULL refname and strip it. `%(refname:short)` yields the
#: shortest UNAMBIGUOUS name, so a branch sharing its name with a tag comes back
#: as `heads/<name>` — a string no git command accepts, which silently breaks
#: every membership test and every `git branch -d` built from it. Plan 00254
#: reproduced the cost: a tag patch-equivalent to a protected ref got a branch
#: holding the only copy of a file force-deleted.
_BRANCH_FORMAT = "--format=%(refname)"


@dataclass(frozen=True)
class OrphanedBranch:
    """An agent or WorktreeCreate-recorded branch that no worktree points at.

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
        record.branch for record in parse_worktree_porcelain(listing) if record.branch is not None
    }


def _prunable(repo_root: Path, name: str, base_branch: str, config: BranchesConfig) -> bool:
    """Whether orphan pruning may consider ``name``.

    The configured policy (default, integration lines, protected, exempt) always
    applies. An ``agent-*`` branch is then eligible by its name; any other branch
    only when its creator record says WorktreeCreate made it, because the
    ``<slug>-<8 hex>`` shape alone also matches ``release-20261104``.
    """
    if policy_refusal(name, config, base_branch, refuse_lines=True) is not None:
        return False
    if name.startswith(AGENT_BRANCH_PREFIX):
        return True
    try:
        return creator_route(repo_root, name) == WORKTREE_CREATE_ROUTE
    except RuntimeError:
        # An unreadable record proves nothing, and an unproven branch is kept.
        return False


def collect_orphaned_branches(
    repo_root: Path,
    base_branch: str,
    *,
    run_fn: RunGit = run_git,
    config: BranchesConfig | None = None,
) -> tuple[OrphanedBranch, ...]:
    """Agent and WorktreeCreate-recorded branches with no worktree, tagged with merge status.

    Read-only. Orphaned is defined as the agent branches git lists MINUS the
    branches a worktree points at — which is why this belongs beside the
    worktree collector rather than in a command of its own: the second set is
    exactly what `git worktree list` already had to be read for.

    Returns an empty tuple when either listing fails. Without the worktree
    listing every branch would look orphaned, and without the branch listing
    there is nothing to classify; in both cases no candidates is the safe answer
    rather than a guess.
    """
    unattached = _unattached_branches(repo_root, base_branch, run_fn)
    if unattached is None:
        return ()
    names, merged = unattached
    policy = config if config is not None else BranchesConfig()
    return tuple(
        OrphanedBranch(name=name, merged_into_base=name in merged)
        for name in names
        if is_daemon_created_branch(name) and _prunable(repo_root, name, base_branch, policy)
    )


def _unattached_branches(
    repo_root: Path, base_branch: str, run_fn: RunGit
) -> tuple[list[str], set[str]] | None:
    """``(branches no worktree points at, those merged into base)``; None on a git failure.

    An unreadable ``--merged`` listing means the merge status is UNKNOWN. Treating
    unknown as merged would turn a git failure into a deletion, so every branch is
    then reported unmerged and nothing is pruned.
    """
    listing = run_fn(repo_root, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return None
    listed = _branch_names(run_fn(repo_root, "branch", "--list", _BRANCH_FORMAT))
    if listed is None:
        return None
    merged_names = _branch_names(
        run_fn(repo_root, "branch", "--merged", base_branch, "--list", _BRANCH_FORMAT)
    )
    attached = _attached_branches(listing.stdout)
    names = [name for name in listed if name not in attached]
    return names, set(merged_names) if merged_names is not None else set()


def collect_skipped_merged_branches(
    repo_root: Path,
    base_branch: str,
    *,
    run_fn: RunGit = run_git,
    config: BranchesConfig | None = None,
) -> tuple[str, ...]:
    """Merged branches with no worktree that orphan pruning skips for their NAME.

    The policy names (default, integration lines, protected, exempt) are not
    skips and are left out; so is anything not merged into ``base_branch``. What
    remains is exactly what ``--reap-branches`` declines because it is not
    agent-owned (Plan 00571 Task 2.4): reported, never deleted here.
    """
    unattached = _unattached_branches(repo_root, base_branch, run_fn)
    if unattached is None:
        return ()
    names, merged = unattached
    policy = config if config is not None else BranchesConfig()
    return tuple(
        name
        for name in names
        if name in merged
        and policy_refusal(name, policy, base_branch, refuse_lines=True) is None
        and not (is_daemon_created_branch(name) and _prunable(repo_root, name, base_branch, policy))
    )


@dataclass(frozen=True)
class PruneOutcome:
    """What happened to one branch, in terms a report can print directly."""

    name: str
    deleted: bool
    detail: str
    #: A merged branch the delete was asked to remove and did not. Distinct from a
    #: dry run or an unmerged branch, which were never going to be deleted.
    kept: bool = False


def prune_branch(
    repo_root: Path,
    branch: OrphanedBranch,
    *,
    base_branch: str,
    bundle_dir: Path | None = None,
    dry_run: bool = False,
) -> PruneOutcome:
    """Delete one orphaned branch, if it is fully merged into the base.

    The delete goes through :func:`branch_safety.delete_branches`, the engine behind
    ``delete-branch``, so the two commands agree on every branch: containment is
    proved against ``base_branch`` (which also covers a branch merged but ahead of
    its upstream, where ``git branch -d`` refuses), git's own delete check still
    runs, and a recovery bundle is written under ``bundle_dir`` when given. A
    refusal is REPORTED as ``kept``, never retried with force. A git failure the engine
    cannot classify (an expired budget) propagates as ``CalledProcessError``; the caller
    reports it as kept.

    Raises:
        CalledProcessError: if git fails in a way the proof cannot classify.
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

    report = delete_branches(
        repo_root,
        [branch.name],
        protected_ref=base_branch,
        protected_names=(base_branch,),
        bundle_path=(
            new_bundle_path(bundle_dir, "worktree-reap") if bundle_dir is not None else None
        ),
        content_tier=False,
    )
    if branch.name not in report.deleted:
        return PruneOutcome(
            branch.name,
            deleted=False,
            kept=True,
            detail=f"kept the branch {branch.name}: {'; '.join(report.blockers) or 'not deleted'}",
        )
    suffix = f" (recovery bundle {report.bundle})" if report.bundle is not None else ""
    return PruneOutcome(branch.name, deleted=True, detail=f"deleted branch {branch.name}{suffix}")
