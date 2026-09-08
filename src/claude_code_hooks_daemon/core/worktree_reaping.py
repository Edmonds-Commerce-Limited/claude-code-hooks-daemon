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
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.core.worktree_paths import WORKTREE_DIR_PATTERNS
from claude_code_hooks_daemon.utils.git_repo import run_git

#: Stands in for a count git could not supply. NEGATIVE on purpose: every
#: refusal rule below tests `!= 0`, so a collection failure can never be read
#: as "nothing to lose" no matter which rule sees it first.
UNKNOWN_COUNT = -1

#: `git status --porcelain` prefixes each path with two status characters and a
#: space (`A  path`, `?? path`).
_STATUS_PREFIX_WIDTH = 3

RunGit = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class WorktreeState:
    """What a collector observed about one worktree.

    Deliberately plain data, so the decision is testable without a git
    repository and the git-running half can be exercised separately.

    Attributes:
        name: The worktree's directory name, used in the refusal message.
        uncommitted_paths: Paths `git status --porcelain` reports — staged,
            unstaged or untracked, all treated alike.
        commits_ahead_of_base: `git rev-list --count <base>..HEAD`.
        unlanded_patches: `git cherry <base> HEAD` lines marked `+`. Recorded
            because it is the far more accurate signal of real divergence, but
            it is NOT trusted to clear a worktree on its own — see the module
            docstring.
    """

    name: str
    uncommitted_paths: tuple[str, ...]
    commits_ahead_of_base: int
    unlanded_patches: int


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


def _worktree_paths(listing: str, repo_root: Path) -> list[Path]:
    """The agent worktrees in `git worktree list --porcelain` output.

    The main checkout appears in that listing too and must never become a reap
    candidate, so paths are kept only when they sit under one of the sanctioned
    worktree directories — the same tuple the path-classifying helpers use.
    """
    paths = []
    for line in listing.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = line.split(" ", 1)[1].strip()
        relative = candidate[len(str(repo_root)) :].lstrip("/")
        if any(relative.startswith(pattern) for pattern in WORKTREE_DIR_PATTERNS):
            paths.append(Path(candidate))
    return paths


def _count(result: subprocess.CompletedProcess[str]) -> int:
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


def _unlanded(result: subprocess.CompletedProcess[str]) -> int:
    """`git cherry` lines marked `+`, or :data:`UNKNOWN_COUNT` on failure.

    `-` means git found an equivalent patch already on the base.
    """
    if result.returncode != 0:
        return UNKNOWN_COUNT
    return sum(1 for line in result.stdout.splitlines() if line.startswith("+"))


def collect_worktree_states(
    repo_root: Path, base_branch: str, *, run_fn: RunGit = run_git
) -> tuple[WorktreeState, ...]:
    """Read each agent worktree's state from git.

    Read-only: this asks git questions and removes nothing. Pair it with
    :func:`is_reapable` to decide, and leave acting to an explicit caller.

    Returns an empty tuple when the listing itself cannot be read — with no
    listing there are no candidates, which is the safe answer rather than a
    guess.
    """
    listing = run_fn(repo_root, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return ()

    states = []
    for path in _worktree_paths(listing.stdout, repo_root):
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
                uncommitted_paths=uncommitted,
                commits_ahead_of_base=_count(
                    run_fn(path, "rev-list", "--count", f"{base_branch}..HEAD")
                ),
                unlanded_patches=_unlanded(run_fn(path, "cherry", base_branch, "HEAD")),
            )
        )
    return tuple(states)
