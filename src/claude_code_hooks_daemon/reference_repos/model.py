"""What a governed reference repository's state IS, separate from what to do about it.

``RepoState`` carries facts and the predicates derivable from them. It carries
no enforcement policy, deliberately: three surfaces consume this value — a
SessionStart sweep, a PreToolUse handler and a CLI report — and only one of them
blocks anything. A ``should_block`` property here would bake one consumer's
configurable mode into the value the other two share.

Two of the plan's safety invariants live here rather than in the callers, so
that no caller can forget them:

``un-checkable never demands attention``
    A repo with no remote, no upstream, or a detached HEAD is reported once and
    then stays out of the way. This project keeps a canary clone whose origin is
    invalid BY DESIGN; if un-checkable could demand attention, every session
    would open with a complaint nobody can act on, and the reports that matter
    would be skimmed past.

``dirty, ahead or diverged is never safe to pull``
    Report only. Staleness costs an agent some wrong reasoning; a pull into a
    repo carrying local work costs someone their work, which is the strictly
    worse outcome. The refusal branches mirror ``git_upstream_checker``'s
    ``_auto_pull`` rather than re-deriving them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final


class Checkability(StrEnum):
    """Whether a repo's freshness can be judged at all, and if not, why.

    The distinction between "stale" and "cannot be checked" is the one that
    keeps this system usable. Collapsing them would either block on repos
    nobody can fix, or silently pass repos nobody verified.
    """

    CHECKABLE = "checkable"
    NOT_A_REPO = "not-a-repo"
    NO_REMOTE = "no-remote"
    DETACHED_HEAD = "detached-head"
    NO_UPSTREAM = "no-upstream"


_REASONS: Final[dict[Checkability, str]] = {
    Checkability.CHECKABLE: "checkable — freshness is known and up to date can be asserted",
    Checkability.NOT_A_REPO: "not a git repository, so there is nothing to compare",
    Checkability.NO_REMOTE: "no remote configured, so there is no upstream truth to compare against",
    Checkability.DETACHED_HEAD: "detached HEAD, so no branch position can be judged",
    Checkability.NO_UPSTREAM: "branch has no upstream, so ahead/behind is undefined",
}


@dataclass(frozen=True)
class RepoState:
    """A point-in-time reading of one governed reference repository.

    Frozen because the same instance is cached and handed to several consumers;
    a mutable reading could be altered by whichever one looked at it first.
    """

    path: Path
    checkability: Checkability
    branch: str | None
    default_branch: str | None
    upstream: str | None
    behind: int
    ahead: int
    dirty: bool
    #: True when the last fetch ATTEMPT failed, so ``behind``/``ahead`` were
    #: computed from whatever refs were already on disk. Defaults False because
    #: ``inspect_repo`` never attempts a fetch; only ``refresh_repo`` can know.
    fetch_failed: bool = False

    @property
    def checkable(self) -> bool:
        """True when freshness can be judged at all."""
        return self.checkability is Checkability.CHECKABLE

    @property
    def verified(self) -> bool:
        """True when this reading was actually confirmed against the remote.

        Distinct from :attr:`checkable`, and the distinction is one a real
        canary exposed: a repo can have a remote and an upstream (so it IS
        checkable) while that remote is unreachable, leaving ``behind`` computed
        from stale refs. Counting such a repo as "up to date" is a confident
        all-clear about a repo nobody checked.

        Deliberately NOT folded into :attr:`needs_attention`: an unreachable
        remote is usually permanent, and a complaint nobody can action, repeated
        every session, is one a reader learns to skim.
        """
        return self.checkable and not self.fetch_failed

    @property
    def reason(self) -> str:
        """A sentence explaining this repo's checkability, for any report."""
        return _REASONS[self.checkability]

    @property
    def is_behind(self) -> bool:
        """True when the upstream carries commits this checkout does not."""
        return self.behind > 0

    @property
    def is_ahead(self) -> bool:
        """True when this checkout carries commits the upstream does not."""
        return self.ahead > 0

    @property
    def is_diverged(self) -> bool:
        """True when both sides carry commits the other does not."""
        return self.is_behind and self.is_ahead

    @property
    def is_on_default_branch(self) -> bool:
        """True when the checkout sits on its default branch.

        An UNKNOWN default branch reads as True rather than False. Unknown is
        not the same as wrong, and reporting a mismatch nobody can confirm
        would manufacture work out of missing information.
        """
        if self.default_branch is None:
            return True
        return self.branch == self.default_branch

    @property
    def needs_attention(self) -> bool:
        """True when a reader should be told about this repo before trusting it.

        Un-checkable is never attention-worthy — see the module docstring.
        """
        if not self.checkable:
            return False
        return self.is_behind or not self.is_on_default_branch

    @property
    def safe_to_pull(self) -> bool:
        """True only when a fast-forward pull is both possible and wanted.

        Requires: checkable, something to fetch down (``behind``), no local
        commits (``ahead``), and a clean tree. A repo that is already current is
        not unsafe — there is simply nothing to do, and pulling anyway would be
        work with no result.
        """
        if not self.verified:
            # A failed fetch brought nothing down, so there is nothing newly
            # available to fast-forward ONTO -- pulling would either no-op or
            # fail again against the same unreachable remote.
            return False
        if self.dirty or self.is_ahead:
            return False
        return self.is_behind
