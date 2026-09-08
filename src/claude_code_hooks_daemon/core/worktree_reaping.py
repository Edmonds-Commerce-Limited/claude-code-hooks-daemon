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

from dataclasses import dataclass


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
