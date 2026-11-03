"""The containment proof behind lossless force removal (Plan 00558 DESIGN section 11).

A ref may go without losing a commit when some OTHER ref still contains its
tip. "Other" excludes every ref the same command deletes, so a command that
deletes a branch together with its only holder is judged as a whole. Each later
deletion of a surviving holder is judged the same way, so no step loses work.

One ``git rev-list <tips> --not <holders>`` answers for many tips at once: a tip
some holder reaches is subtracted, so a tip still printed is held by nothing.
"""

from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import run_git

#: Every ref namespace whose refs survive a branch deletion and hold commits.
ALL_HOLDERS: Final[tuple[str, ...]] = ("refs/heads", "refs/remotes", "refs/tags")
#: Only remote-tracking refs: what ``branches.force_removal.mode: off`` trusts.
REMOTE_HOLDERS: Final[tuple[str, ...]] = ("refs/remotes",)


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
