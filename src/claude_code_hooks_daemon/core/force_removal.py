"""The containment proof behind lossless force removal (Plan 00558 DESIGN section 11).

A ref may go without losing a commit when some OTHER ref still contains its
tip. "Other" excludes every ref the same command deletes, so a command that
deletes a branch together with its only holder is judged as a whole. Each later
deletion of a surviving holder is judged the same way, so no step loses work.

One ``git rev-list <tips> --not <holders>`` answers for many tips at once: a tip
some holder reaches is subtracted, so a tip still printed is held by nothing.
"""

import logging
import time
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import GIT_COMMAND_ERRORS, git_deadline, run_git

logger = logging.getLogger(__name__)

#: Every ref namespace whose refs survive a branch deletion and hold commits.
ALL_HOLDERS: Final[tuple[str, ...]] = ("refs/heads", "refs/remotes", "refs/tags")
#: Only remote-tracking refs: what ``branches.force_removal.mode: off`` trusts.
REMOTE_HOLDERS: Final[tuple[str, ...]] = ("refs/remotes",)


#: Wall-clock seconds the whole patch-equivalence search may take: well under the daemon's
#: chain deadline (20 s), past which the whole PreToolUse chain is denied unjudged.
PATCH_PROOF_BUDGET_SECONDS: Final[float] = 6.0


class ContainmentUnknown(Exception):
    """Git could not say which tips another ref holds; callers fail closed."""


def _holder_arguments(excluded_refs: Collection[str], namespaces: Sequence[str]) -> list[str]:
    """``--not`` and one ``--glob`` per namespace, each preceded by its exclusions.

    git clears ``--exclude`` at every ``--glob``, so each namespace carries its own.
    A namespace without a wildcard matches everything beneath it, nested names too.
    """
    arguments = ["--not"]
    for namespace in namespaces:
        prefix = f"{namespace}/"
        arguments.extend(
            f"--exclude={ref}" for ref in sorted(excluded_refs) if ref.startswith(prefix)
        )
        arguments.append(f"--glob={namespace}")
    return arguments


def uncontained_tips(
    repo: Path,
    tips: Sequence[str],
    excluded_refs: Collection[str],
    namespaces: Sequence[str] = ALL_HOLDERS,
) -> frozenset[str]:
    """The ``tips`` (full object names) that no ref outside ``excluded_refs`` contains.

    Raises:
        ContainmentUnknown: When git fails or times out; nothing is then proven.
    """
    if not tips:
        return frozenset()
    listing = run_git(
        repo,
        "rev-list",
        *tips,
        *_holder_arguments(excluded_refs, namespaces),
        timeout=Timeout.GIT_CONTEXT,
    )
    if listing.returncode != 0:
        raise ContainmentUnknown(f"git rev-list failed: {listing.stderr.strip()}")
    printed = set(listing.stdout.split())
    return frozenset(tip for tip in tips if tip in printed)


def _surviving_refs(
    repo: Path, excluded_refs: Collection[str], namespaces: Sequence[str]
) -> list[str]:
    """Full names of every ref in ``namespaces`` the command does not delete."""
    listing = run_git(
        repo, "for-each-ref", "--format=%(refname)", *namespaces, timeout=Timeout.GIT_CONTEXT
    )
    if listing.returncode != 0:
        raise ContainmentUnknown(f"git for-each-ref failed: {listing.stderr.strip()}")
    return [ref for ref in listing.stdout.split() if ref not in excluded_refs]


def patch_held_tips(
    repo: Path,
    tips: Sequence[str],
    excluded_refs: Collection[str],
    namespaces: Sequence[str] = ALL_HOLDERS,
    *,
    budget: float = PATCH_PROOF_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> frozenset[str]:
    """The ``tips`` whose every patch some surviving ref already holds (N752).

    The whole search shares one wall-clock ``budget``; a tip not proven when it runs
    out is not held (the per-git-call limits alone do not bound the loop).

    A commit reachable from no surviving ref is still lost-free when a surviving
    ref carries the same patch (a cherry-pick, a rebase): the same patch-equivalence
    ``branch_safety`` uses for a branch, and as there it is never trusted alone. The
    surviving ref's history must also hold the tip's net change, and no submodule
    pointer may be left to a patch-id that cannot see it. Anything git cannot answer
    is not held (fails closed).

    Raises:
        ContainmentUnknown: When the surviving refs cannot be listed.
    """
    # Imported here: remote_branch_proof imports branch_safety, which imports this package.
    from claude_code_hooks_daemon.core import remote_branch_proof
    from claude_code_hooks_daemon.daemon.branch_safety import patch_equivalent

    top = run_git(repo, "rev-parse", "--show-toplevel", timeout=Timeout.GIT_CONTEXT)
    if top.returncode != 0 or not top.stdout.strip():
        return frozenset()
    top_level = Path(top.stdout.strip())
    refs = _surviving_refs(top_level, excluded_refs, namespaces)
    deadline = clock() + budget
    held: set[str] = set()
    proof_errors: tuple[type[BaseException], ...] = (
        remote_branch_proof.ProofUnavailableError,
        *GIT_COMMAND_ERRORS,
    )
    # Every git call below shares the deadline, so one slow ref cannot outlast it: a call
    # past it reports a timeout, which each proof reads as "not held".
    with git_deadline(deadline, clock):
        for tip in tips:
            for ref in refs:
                if clock() >= deadline:
                    # Out of time is not held: the removal is refused with this guard's own
                    # reason, before the chain deadline denies the call unjudged.
                    return frozenset(held)
                if not _shares_history(top_level, ref, tip):
                    continue
                try:
                    proven = (
                        patch_equivalent(top_level, ref, tip) == (True, 0)
                        and remote_branch_proof.holds_net_change(top_level, ref, tip)
                        and remote_branch_proof.gitlink_change_held(top_level, ref, tip)
                    )
                except proof_errors as error:
                    log_and_continue(
                        logger,
                        error,
                        reason=f"patch proof of {tip} against {ref} unavailable, so not held",
                    )
                    proven = False
                if proven and clock() < deadline:
                    held.add(tip)
                    break
    return frozenset(held)


def _shares_history(repo: Path, ref: str, tip: str) -> bool:
    """Whether ``ref`` and ``tip`` have a merge base: the cheap pre-filter for the patch proof.

    With none, ``git cherry`` matches against the whole history and the net-change
    proof has no base, so such a ref can never prove a tip.
    """
    return run_git(repo, "merge-base", ref, tip, timeout=Timeout.GIT_CONTEXT).returncode == 0


def lost_commit_count(
    repo: Path,
    tip: str,
    excluded_refs: Collection[str],
    namespaces: Sequence[str] = ALL_HOLDERS,
) -> int | None:
    """How many commits reachable from ``tip`` no surviving ref reaches; None if unknown."""
    counted = run_git(
        repo,
        "rev-list",
        "--count",
        tip,
        *_holder_arguments(excluded_refs, namespaces),
        timeout=Timeout.GIT_CONTEXT,
    )
    if counted.returncode != 0 or not counted.stdout.strip().isdigit():
        return None
    return int(counted.stdout.strip())
