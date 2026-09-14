"""Read a governed repository's state from local refs alone — never the network.

Named ``inspection`` rather than ``inspect`` (as Plan 00401 Task 1.2 drafted it)
because a module called ``inspect.py`` shadows a standard-library module that
much of the ecosystem imports; the confusion that causes is not worth matching
a draft filename.

**No function here contacts a remote, and that is the architecture rather than
an optimisation.** ``Timeout.GIT_FETCH_SESSION`` and ``GIT_PULL_SESSION`` are
30s apiece against a 30s hook socket budget, so one fetch for one repo can
consume the entire budget — and a project can govern several. Doing that work
inside PreToolUse would reproduce the ``socket_timeout`` failure mode the daemon
already ships dedicated error text for. So SessionStart owns the fetching and
this module only ever reads what is already on disk.

The consequence is deliberate and worth stating plainly: immediately after
someone else pushes, a repo here still reads as up to date, because nothing has
fetched yet. Freshness is therefore "fresh as of the last fetch", which is why
the cache that feeds PreToolUse carries a TTL and why a missing or expired entry
reads as NOT VERIFIED rather than as fresh.

Classification order matters and is not arbitrary — each step is a precondition
for the next being meaningful. A detached HEAD has no branch, so asking about
its upstream is nonsense; a repo with no remote cannot have a meaningful
upstream either. Reporting the FIRST thing that is wrong gives the reader one
actionable remedy rather than a cascade of consequences.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState
from claude_code_hooks_daemon.utils import git_sync


def _unknown(path: Path, checkability: Checkability, *, branch: str | None = None) -> RepoState:
    """A reading for a repo whose freshness cannot be judged.

    Counts are zero and never "unknown sentinels": a caller that reaches for
    ``behind`` on an un-checkable repo should get a number that cannot be
    mistaken for staleness, and ``needs_attention`` already refuses to fire for
    these regardless of what the counts say.
    """
    return RepoState(
        path=path,
        checkability=checkability,
        branch=branch,
        default_branch=None,
        upstream=None,
        behind=0,
        ahead=0,
        dirty=False,
    )


def inspect_repo(path: Path) -> RepoState:
    """Return the current state of one governed repository.

    Performs NO network I/O — see the module docstring. Every probe reads local
    refs and the working tree only.

    Args:
        path: The repository checkout to read.

    Returns:
        A :class:`RepoState`. A repo that cannot be judged comes back with the
        classification saying WHY, never with a guess.
    """
    if not (path / ".git").exists():
        return _unknown(path, Checkability.NOT_A_REPO)

    branch = git_sync.current_branch(path)
    if branch is None:
        # No branch name means a detached HEAD: there is no branch position to
        # compare, so every later question is unanswerable.
        return _unknown(path, Checkability.DETACHED_HEAD)

    if not git_sync.remotes(path):
        return _unknown(path, Checkability.NO_REMOTE, branch=branch)

    status = git_sync.upstream_status(path)
    if status is None:
        return _unknown(path, Checkability.NO_UPSTREAM, branch=branch)

    return RepoState(
        path=path,
        checkability=Checkability.CHECKABLE,
        branch=branch,
        default_branch=git_sync.default_branch(path),
        upstream=status.upstream,
        behind=status.behind,
        ahead=status.ahead,
        dirty=not git_sync.working_tree_clean(path),
    )
