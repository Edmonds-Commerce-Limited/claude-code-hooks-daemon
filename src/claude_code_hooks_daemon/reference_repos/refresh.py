"""Fetch a governed repo, and fast-forward it only when that is provably safe.

The only module in this package that touches the network. It runs from
SessionStart, which already owns a network budget; nothing on the PreToolUse
path may call in here (see :mod:`inspection` for why that boundary exists).

The owner's ruling was "the daemon pulls when provably safe; reports and never
touches otherwise", and the second half carries the weight. Staleness costs an
agent some wrong reasoning, which is recoverable. A pull into a repo holding
uncommitted work or local commits costs a person their work, which is not. So
every refusal is silent about cleverness and loud about what the human should
do instead.

The refusal DECISION is not re-derived here: :attr:`RepoState.safe_to_pull`
owns it, so the predicate and its tests live in one place. What this module adds
is the granularity a report needs — "dirty", "ahead" and "diverged" are one
boolean to the decision but three different remedies to a reader, and telling
someone with diverged history to commit their changes is useless advice.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.reference_repos.inspection import inspect_repo
from claude_code_hooks_daemon.reference_repos.model import RepoState
from claude_code_hooks_daemon.utils import git_sync

_NOTHING_TO_DO: Final[str] = "already up to date with its upstream; nothing to pull"
_PULL_DISABLED: Final[str] = "auto-pull is disabled, so the repo was fetched and reported only"
_FETCH_FAILED: Final[str] = (
    "git fetch did not succeed (offline, or the remote is unreachable), so freshness "
    "is reported from the refs already on disk"
)


@dataclass(frozen=True)
class RefreshOutcome:
    """What a refresh did, and the state it left behind.

    ``state`` is the reading AFTER the work, so a caller reports the repo as it
    now stands rather than as it was found.
    """

    state: RepoState
    fetched: bool
    pulled: bool
    detail: str


def _refusal_detail(state: RepoState) -> str:
    """Explain, actionably, why a fetched repo was not fast-forwarded.

    Ordered by what the reader must resolve FIRST. A diverged repo is also
    "ahead", and a dirty diverged repo is both — naming only the last condition
    checked would send someone to the wrong remedy.
    """
    if state.dirty:
        return (
            "not pulled: the working tree has uncommitted changes. Commit them, then "
            "`git -C <repo> pull --ff-only`"
        )
    if state.is_diverged:
        return (
            "not pulled: history has diverged, so a fast-forward is impossible. "
            "Resolve with `git -C <repo> pull --rebase` and review the result"
        )
    if state.is_ahead:
        return (
            "not pulled: the checkout carries local commit(s) the upstream does not. "
            "Push or remove them before this repo can fast-forward"
        )
    return _NOTHING_TO_DO


def refresh_repo(path: Path, *, allow_pull: bool = True) -> RefreshOutcome:
    """Fetch ``path``, then fast-forward it if and only if that is safe.

    Args:
        path: The governed checkout to refresh.
        allow_pull: When False, fetch and report without ever mutating the
            checkout. This is report-only mode, for an owner who wants the
            visibility without the daemon touching anything.

    Returns:
        A :class:`RefreshOutcome` whose ``state`` reflects the repo AFTER the
        work. Never raises for an ordinary git failure: this runs at
        SessionStart, and an exception would cost the whole session's startup
        context for something as mundane as being offline.
    """
    before = inspect_repo(path)
    if not before.checkable:
        # Nothing to fetch FROM, so fetching would only burn the budget.
        return RefreshOutcome(state=before, fetched=False, pulled=False, detail=before.reason)

    fetched = git_sync.fetch_all(path)
    state = inspect_repo(path)

    if not fetched:
        # Recorded ON THE STATE, not just in `detail`: the state is what gets
        # cached and handed to all three surfaces, and a caller keeping only
        # `.state` (all three do) would otherwise report refs from a failed
        # fetch as a confirmed all-clear.
        unverified = replace(state, fetch_failed=True)
        return RefreshOutcome(state=unverified, fetched=False, pulled=False, detail=_FETCH_FAILED)

    if not allow_pull:
        return RefreshOutcome(state=state, fetched=True, pulled=False, detail=_PULL_DISABLED)

    if not state.safe_to_pull:
        return RefreshOutcome(
            state=state, fetched=True, pulled=False, detail=_refusal_detail(state)
        )

    result = git_sync.pull_ff_only(path)
    return RefreshOutcome(
        state=inspect_repo(path),
        fetched=True,
        pulled=result.ok,
        detail=result.detail,
    )
