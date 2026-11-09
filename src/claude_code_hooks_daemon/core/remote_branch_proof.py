"""Whether remote branches may be deleted: the one proof every remote delete uses.

Plan 00571 Task 2.2 moved this out of the ``destructive_git`` remote-delete guard
(Plan 00558, issue #153) so ``branch-sweep --clean --remote`` deletes exactly what
the guard would let an agent's ``git push --delete`` delete, and no more. Two
callers, one proof: they cannot disagree.

The proof, for each named branch: a literal name that is not the default, exempt or
protected; no tag of the same name; a remote-tracking ref whose tip is an ancestor
of the default branch (tracking or local) or, for an ordinary branch, of an
integration line's tracking ref; and the remote's LIVE tip, read with one batched
``git ls-remote`` per chunk, equal to that tracking tip. Every failure, timeout and
mismatch is a reason, never a pass. The listing is ``utils/remote_refs.py``'s, the
same one ``branch-sweep`` and ``delete-branch`` use, bounded to the named branches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon.branch_safety import matches_any_glob
from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX, branch_ref, run_git
from claude_code_hooks_daemon.utils.remote_refs import list_remote_refs

#: A name that is safe to hand to git as one argument: no expansion, quoting or
#: option-looking characters survive it.
LITERAL_BRANCH_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9._/+@-]+")

REMOTES_PREFIX: Final[str] = "refs/remotes/"
TAGS_PREFIX: Final[str] = "refs/tags/"

#: Branch patterns per `git ls-remote` call. One call per remote is the aim; this only
#: bounds the argv (Linux caps one argument at 128 KiB and the whole argv near 2 MiB),
#: and 500 names of ~100 bytes stay far below both while a realistic delete is one call.
LS_REMOTE_CHUNK: Final[int] = 500

_REF_FORMAT: Final[str] = "--format=%(objectname) %(objecttype) %(refname)"


@dataclass(frozen=True)
class RemoteProof:
    """The outcome of :func:`prove_remote_merged`.

    Attributes:
        tips: Branch name to the live remote tip, for every branch proven deletable.
        problems: Branch name to why it is not, for every other branch named.
    """

    tips: dict[str, str]
    problems: dict[str, str]


def branch_name(ref: str) -> str:
    """The branch name a delete ``ref`` (``name`` or ``refs/heads/name``) refers to."""
    return ref.removeprefix(HEADS_PREFIX)


def _refusal(name: str, default: str, branches: BranchesConfig) -> str | None:
    """Why ``name`` may never be deleted remotely by an agent, whatever the proof."""
    if name == default:
        return f"`{name}` is the default branch"
    if matches_any_glob(name, branches.exempt):
        return f"`{name}` is exempt (`branches.exempt`)"
    if matches_any_glob(name, branches.protected_names):
        return f"`{name}` is a protected name (`branches.protected_names`)"
    return None


def named_ref_problem(remote: str, ref: str, default: str, branches: BranchesConfig) -> str | None:
    """Why ``ref`` cannot be judged or is refused outright, before any git runs."""
    name = branch_name(ref)
    if not LITERAL_BRANCH_NAME.fullmatch(remote):
        return f"`{remote}` is not a literal remote name"
    if name.startswith(TAGS_PREFIX) or not LITERAL_BRANCH_NAME.fullmatch(name):
        return f"`{ref}` is not a literal branch name (tags are never deleted by an agent)"
    return _refusal(name, default, branches)


def _listed_refs(directory: Path, patterns: list[str]) -> dict[str, tuple[str, str]] | None:
    """Map refname to ``(object, type)`` for every ref matching ``patterns``, in one call.

    Keyed by the exact refname, so a pattern that also matches a longer ref never
    lends it to another name. None when git fails or times out.
    """
    listing = run_git(
        directory, "for-each-ref", _REF_FORMAT, *patterns, timeout=Timeout.GIT_CONTEXT
    )
    if listing.returncode != 0:
        return None
    refs: dict[str, tuple[str, str]] = {}
    for line in listing.stdout.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            refs[parts[2]] = (parts[0], parts[1])
    return refs


def _merged_into(directory: Path, target: str, refnames: list[str]) -> set[str] | None:
    """Which of ``refnames`` are ancestors of ``target``: one ``for-each-ref --merged``.

    None when git fails or times out.
    """
    merged = run_git(
        directory,
        "for-each-ref",
        f"--merged={target}",
        "--format=%(refname)",
        *refnames,
        timeout=Timeout.GIT_CONTEXT,
    )
    if merged.returncode != 0:
        return None
    return set(merged.stdout.splitlines())


def _default_proof_targets(
    remote: str, default: str, refs: dict[str, tuple[str, str]]
) -> list[str]:
    """The existing default-branch refs: the only proof an integration line accepts."""
    tracking_prefix = f"{REMOTES_PREFIX}{remote}/"
    return [
        ref
        for ref in (f"{tracking_prefix}{default}", branch_ref(default))
        if ref in refs and refs[ref][1] == "commit"
    ]


def _proof_targets(
    remote: str, default: str, branches: BranchesConfig, refs: dict[str, tuple[str, str]]
) -> list[str]:
    """The existing refs a merged branch may be an ancestor of: default, then lines."""
    tracking_prefix = f"{REMOTES_PREFIX}{remote}/"
    targets = _default_proof_targets(remote, default, refs)
    for refname, (_object, kind) in refs.items():
        line = refname.removeprefix(tracking_prefix)
        if (
            refname.startswith(tracking_prefix)
            and kind == "commit"
            and line not in (default, "HEAD")
            and matches_any_glob(line, branches.integration_lines)
        ):
            targets.append(refname)
    return targets


def _merged_tracking_tips(
    directory: Path, remote: str, names: list[str], default: str, branches: BranchesConfig
) -> tuple[dict[str, str], dict[str, str]]:
    """``(name -> tracking tip for every proven name, name -> problem for the rest)``.

    One listing call, then one ``for-each-ref --merged`` per target over all the named
    refs, so the cost does not grow with the number of branches. Judged from local git
    only; the remote's live tip is checked afterwards by :func:`_live_tip_problems`.
    """
    tracking = {name: f"{REMOTES_PREFIX}{remote}/{name}" for name in names}
    refs = _listed_refs(
        directory,
        [
            f"{REMOTES_PREFIX}{remote}",
            branch_ref(default),
            *[f"{TAGS_PREFIX}{name}" for name in names],
        ],
    )
    if refs is None:
        return {}, {
            name: f"`git for-each-ref` failed, so `{name}` could not be checked" for name in names
        }
    tips: dict[str, str] = {}
    problems: dict[str, str] = {}
    for name in names:
        listed = refs.get(tracking[name])
        if f"{TAGS_PREFIX}{name}" in refs:
            problems[name] = f"`{name}` is also the name of a tag, so the delete is ambiguous"
        elif listed is None or listed[1] != "commit":
            problems[name] = f"`{name}` has no remote-tracking ref `{tracking[name]}` here"
        else:
            tips[name] = listed[0]
    proven: set[str] = set()
    if tips:
        default_targets = _default_proof_targets(remote, default, refs)
        # An integration line is proved against the default branch ONLY: being merged
        # into another line is no evidence the line may go.
        feature_tracking = [
            tracking[name]
            for name in tips
            if not matches_any_glob(name, branches.integration_lines)
        ]
        for target in _proof_targets(remote, default, branches, refs):
            checked = (
                [tracking[name] for name in tips] if target in default_targets else feature_tracking
            )
            if not checked:
                continue
            merged = _merged_into(directory, target, checked)
            if merged is None:
                failed = {
                    n: f"`git for-each-ref --merged={target}` failed, so `{n}` could not be checked"
                    for n in tips
                }
                return {}, {**problems, **failed}
            proven |= merged
    lines = " or any integration line" if branches.integration_lines else ""
    for name in list(tips):
        if tracking[name] not in proven:
            del tips[name]
            if matches_any_glob(name, branches.integration_lines):
                problems[name] = (
                    f"`{name}` is an integration line not yet merged into the default "
                    f"branch `{default}` (another line does not count)"
                )
            else:
                problems[name] = f"`{name}` is not merged into `{default}`{lines}"
    return tips, problems


def live_remote_tips(directory: Path, remote: str, names: list[str]) -> dict[str, str]:
    """Map branch name to the tip ``remote`` reports, from one ``ls-remote`` per chunk.

    Fails closed: a failed or timed-out listing contributes nothing, so its branches
    are absent from the map. Lines are keyed by their exact ref, so a pattern that
    also matches a longer name (``feat`` and ``feat-2``) or a foreign ref ending in
    the name never lends its tip to another branch.
    """
    tips: dict[str, str] = {}
    for start in range(0, len(names), LS_REMOTE_CHUNK):
        chunk = names[start : start + LS_REMOTE_CHUNK]
        listing = list_remote_refs(
            directory,
            remote,
            patterns=tuple(f"{HEADS_PREFIX}{name}" for name in chunk),
            timeout=Timeout.GIT_CONTEXT,
        )
        if listing.failure is not None:
            continue
        for listed, tip in listing.refs:
            if listed.startswith(HEADS_PREFIX):
                tips[listed.removeprefix(HEADS_PREFIX)] = tip
    return tips


def _live_tip_problems(directory: Path, remote: str, local_tips: dict[str, str]) -> dict[str, str]:
    """Why the remote's live tips are not the merged ``local_tips`` (name to tip).

    The remote-tracking ref is only as fresh as the last fetch: a commit pushed since
    would be lost by the delete. ``git ls-remote`` asks the remote itself, once for
    all the branches; it never fetches.
    """
    if not local_tips:
        return {}
    live = live_remote_tips(directory, remote, list(local_tips))
    return {
        name: (
            f"the remote tip of `{name}` could not be confirmed as merged (it differs from "
            f"`{REMOTES_PREFIX}{remote}/{name}`, is gone, or `git ls-remote {remote}` failed); "
            "run `git fetch` and retry"
        )
        for name, tip in local_tips.items()
        if live.get(name) != tip
    }


def prove_remote_merged(
    directory: Path, remote: str, names: list[str], default: str, branches: BranchesConfig
) -> RemoteProof:
    """Prove each of ``names`` (bare branch names, already past :func:`named_ref_problem`).

    Contacts the remote (``ls-remote``) only for the names the local proof accepted.
    """
    tips, problems = _merged_tracking_tips(directory, remote, names, default, branches)
    stale = _live_tip_problems(directory, remote, tips)
    return RemoteProof(
        tips={name: tip for name, tip in tips.items() if name not in stale},
        problems={**problems, **stale},
    )


__all__ = [
    "LITERAL_BRANCH_NAME",
    "LS_REMOTE_CHUNK",
    "REMOTES_PREFIX",
    "TAGS_PREFIX",
    "RemoteProof",
    "branch_name",
    "live_remote_tips",
    "named_ref_problem",
    "prove_remote_merged",
]
