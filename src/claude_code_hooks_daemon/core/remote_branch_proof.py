"""Whether remote branches may be deleted: the one proof every remote delete uses.

Plan 00571 Task 2.2 moved this out of the ``destructive_git`` remote-delete guard
(Plan 00558, issue #153) so ``branch-sweep --clean --remote`` deletes exactly what
the guard would let an agent's ``git push --delete`` delete, and no more. Two
callers, one proof: they cannot disagree.

The proof, for each named branch: a literal name that is not the default, exempt or
protected; no tag of the same name; a remote-tracking ref that is merged by the
cheapest offline evidence that holds (Plan 00594 DESIGN.md 2.1): ancestry of the
default branch (tracking or local) or, for an ordinary branch, of an integration
line's tracking ref; else SOME commit on the default's first-parent line (after
merge-base(default, tip), up to the default's tip) holding the branch's NET change:
its diff against that merge base, renames off, where every added or modified path
has the same blob and mode in the commit's tree and every deleted path is absent.
That is what a squash merge, a renamed pull request or a cherry-pick leaves
behind; the content is then permanently in the default's history, so patch-id
evidence never proves a branch alone, and an empty change (a park branch) proves
nothing. Every git call runs from the repository top level.
Results are cached by algorithm version, tip and default sha in the inventory
cache, so the next call is offline and cheap. Then the remote's LIVE tip, read with one batched
``git ls-remote`` per chunk, equal to that tracking tip. Every failure, timeout and
mismatch is a reason, never a pass. The listing is ``utils/remote_refs.py``'s, the
same one ``branch-sweep`` and ``delete-branch`` use, bounded to the named branches.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.branch_inventory import (
    merge_proof_key,
    read_merge_proofs,
    write_merge_proofs,
)
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_CONTENT_PRESERVED,
    TIER_MERGED,
    TIER_PATCH_EQUIVALENT,
    TIER_UNPROVEN,
    matches_any_glob,
    patch_equivalent,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX, branch_ref, run_git
from claude_code_hooks_daemon.utils.remote_refs import list_remote_refs

logger = logging.getLogger(__name__)

#: ``git merge-base`` exits 1 when the two commits share no ancestor.
_NO_MERGE_BASE: Final[int] = 1

#: Fields of one ``git diff --raw`` record (old mode, new mode, old blob, new blob,
#: status) and of one ``git ls-tree`` record (mode, type, blob).
_RAW_META_FIELDS: Final[int] = 5
_LS_TREE_META_FIELDS: Final[int] = 3

#: ``run_git`` decodes with ``errors="replace"``; this marks a path it could not decode.
_REPLACEMENT_CHAR: Final[str] = "\ufffd"

#: First-parent commits of the default one proof will inspect; more is unproven.
MAX_PROOF_CANDIDATES: Final[int] = 50

#: Paths per ``git ls-tree`` call, bounding the argv for a branch touching many files.
_LS_TREE_CHUNK: Final[int] = 200

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
        evidence: Branch name to the evidence that proved it (a ``branch_safety`` tier:
            ``merged``, ``patch-equivalent`` or ``content-preserved``).
    """

    tips: dict[str, str]
    problems: dict[str, str]
    evidence: dict[str, str]


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


class ProofUnavailableError(RuntimeError):
    """Git failed while judging a branch, so its answer is unknown and must not be cached."""


@dataclass(frozen=True)
class _PathChange:
    """One path the branch changed against the merge base (renames and copies off)."""

    path: str
    deleted: bool
    mode: str
    blob: str


def _net_change(directory: Path, base: str, tracking_ref: str) -> list[_PathChange]:
    """The branch's net change: ``git diff --raw -z --no-renames`` of base to tip.

    Raises:
        ProofUnavailableError: git failed, or a path is not valid UTF-8 (``run_git``
            decodes with replacement, so such a path could not be looked up again).
    """
    raw = run_git(
        directory,
        "diff",
        "--raw",
        "-z",
        "--no-renames",
        "--no-abbrev",
        "--no-ext-diff",
        base,
        tracking_ref,
        timeout=Timeout.GIT_CONTEXT,
    )
    if raw.returncode != 0:
        raise ProofUnavailableError(f"git diff failed for {tracking_ref}")
    fields = raw.stdout.split("\0")
    changes: list[_PathChange] = []
    for index in range(0, len(fields) - 1, 2):
        meta = fields[index].lstrip(":").split(" ")
        if len(meta) != _RAW_META_FIELDS:
            raise ProofUnavailableError(f"unreadable git diff --raw output for {tracking_ref}")
        if _REPLACEMENT_CHAR in fields[index + 1]:
            raise ProofUnavailableError(f"{tracking_ref} changes a path that is not valid UTF-8")
        _old_mode, new_mode, _old_blob, new_blob, status = meta
        changes.append(_PathChange(fields[index + 1], status.startswith("D"), new_mode, new_blob))
    return changes


def _tree_entries(directory: Path, commit: str, paths: list[str]) -> dict[str, tuple[str, str]]:
    """Map path to ``(mode, blob)`` as ``commit``'s tree holds it, for the paths it has.

    ``directory`` is the repository top level, so the root-relative paths of
    ``git diff --raw`` mean the same thing here.

    Raises:
        ProofUnavailableError: git failed, so there is no answer to cache.
    """
    held: dict[str, tuple[str, str]] = {}
    for start in range(0, len(paths), _LS_TREE_CHUNK):
        listing = run_git(
            directory,
            "--literal-pathspecs",
            "ls-tree",
            "-z",
            commit,
            "--",
            *paths[start : start + _LS_TREE_CHUNK],
            timeout=Timeout.GIT_CONTEXT,
        )
        if listing.returncode != 0:
            raise ProofUnavailableError(f"git ls-tree failed for {commit}")
        for entry in listing.stdout.split("\0"):
            meta, _, path = entry.partition("\t")
            parts = meta.split(" ")
            if path and len(parts) == _LS_TREE_META_FIELDS:
                held[path] = (parts[0], parts[2])
    return held


def _tree_holds(directory: Path, commit: str, changes: list[_PathChange]) -> bool:
    """Whether ``commit``'s tree holds every change: same blob and mode, deletions absent."""
    held = _tree_entries(directory, commit, [change.path for change in changes])
    return all(
        (
            change.path not in held
            if change.deleted
            else held.get(change.path) == (change.mode, change.blob)
        )
        for change in changes
    )


def _touching_commits(directory: Path, base: str, target: str, paths: list[str]) -> list[str]:
    """The first-parent commits in ``base..target`` that touched any of ``paths``.

    Raises:
        ProofUnavailableError: git failed, so there is no answer to cache.
    """
    commits: dict[str, None] = {}
    for start in range(0, len(paths), _LS_TREE_CHUNK):
        listing = run_git(
            directory,
            "--literal-pathspecs",
            "log",
            "--first-parent",
            "--format=%H",
            f"{base}..{target}",
            "--",
            *paths[start : start + _LS_TREE_CHUNK],
            timeout=Timeout.GIT_CONTEXT,
        )
        if listing.returncode != 0:
            raise ProofUnavailableError(f"git log failed for {target}")
        commits.update(dict.fromkeys(listing.stdout.split()))
    return list(commits)


def _holds_net_change(directory: Path, target: str, tracking_ref: str) -> bool:
    """Whether the default's first-parent history holds the whole net change of the branch.

    The net change is the branch's diff against ``merge-base(target, tip)``. It is
    held by a commit whose tree has every added or modified path at the same blob
    and mode and every deleted path absent. The target's tip is tried first, then
    the first-parent commits after the merge base that touched those paths (a state
    that holds the change was reached by a commit that touched one of them). Once a
    commit held it the content is permanently in the default's history, even if the
    default has changed it since. More candidates than ``MAX_PROOF_CANDIDATES`` is
    unproven, as is an empty net change (empty commits, or changes that cancel out).

    Raises:
        ProofUnavailableError: git failed, so there is no answer to cache.
    """
    base = run_git(directory, "merge-base", target, tracking_ref, timeout=Timeout.GIT_CONTEXT)
    if base.returncode == _NO_MERGE_BASE:
        return False
    if base.returncode != 0:
        raise ProofUnavailableError(f"git merge-base failed for {tracking_ref}")
    merge_base = base.stdout.strip()
    changes = _net_change(directory, merge_base, tracking_ref)
    if not changes:
        return False
    if _tree_holds(directory, target, changes):
        return True
    candidates = _touching_commits(directory, merge_base, target, [c.path for c in changes])
    if len(candidates) > MAX_PROOF_CANDIDATES:
        return False
    return any(_tree_holds(directory, commit, changes) for commit in candidates)


def _judge_offline(directory: Path, tracking_ref: str, targets: list[str]) -> str:
    """The tier that proves one tracking ref merged into a default ref, or ``unproven``.

    The default's history must hold the branch's net change (:func:`_holds_net_change`):
    that check comes FIRST and alone decides, so neither patch-id evidence nor an
    empty commit on main can prove a branch.
    The tier only names how the change got there: ``patch-equivalent`` when every
    commit has its patch in the default, else ``content-preserved`` (a squash). It is
    not ``branch_safety``'s local-delete tier, which proves only recoverability.

    Raises:
        ProofUnavailableError: git failed, so there is no answer to cache.
    """
    for target in targets:
        if not _holds_net_change(directory, target, tracking_ref):
            continue
        equivalent, count = patch_equivalent(directory, target, tracking_ref)
        if count is None:
            raise ProofUnavailableError(f"git cherry failed for {tracking_ref}")
        return TIER_PATCH_EQUIVALENT if equivalent else TIER_CONTENT_PRESERVED
    return TIER_UNPROVEN


def _offline_evidence(
    directory: Path, pending: dict[str, str], targets: list[str], refs: dict[str, tuple[str, str]]
) -> dict[str, str]:
    """``name -> tier`` for each pending tracking ref whose net change the default holds.

    ``pending`` maps the tracking refname to its tip. Answers are read from, and
    written to, the inventory cache keyed by algorithm version, tip and default sha,
    so a repeat call spawns no git. Targets at the same sha are judged once.
    """
    by_sha = {refs[target][0]: target for target in targets}
    judged_targets = list(by_sha.values())
    cached = read_merge_proofs(directory)
    fresh: dict[str, str] = {}
    found: dict[str, str] = {}
    for tracking_ref, tip in pending.items():
        key = merge_proof_key(tip, by_sha)
        tier = cached.get(key)
        if tier is None:
            try:
                tier = _judge_offline(directory, tracking_ref, judged_targets)
            except ProofUnavailableError as exc:
                log_and_continue(
                    logger,
                    exc,
                    reason="an unanswered proof leaves the branch unproven, which refuses its delete",
                )
                continue
            fresh[key] = tier
        if tier != TIER_UNPROVEN:
            found[tracking_ref] = tier
    if fresh:
        write_merge_proofs(directory, fresh)
    return found


def _merged_tracking_tips(
    directory: Path, remote: str, names: list[str], default: str, branches: BranchesConfig
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """``(name -> tracking tip of each proven name, name -> problem, name -> evidence)``.

    One listing call, then one ``for-each-ref --merged`` per target over all the named
    refs; only a branch ancestry did not settle pays the patch-id and tree checks. Judged from local git
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
        return (
            {},
            {
                name: f"`git for-each-ref` failed, so `{name}` could not be checked"
                for name in names
            },
            {},
        )
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
    evidence: dict[str, str] = {}
    if tips:
        default_targets = _default_proof_targets(remote, default, refs)
        # An integration line is proved against the default branch ONLY: being merged
        # into another line is no evidence the line may go.
        feature_names = {
            name for name in tips if not matches_any_glob(name, branches.integration_lines)
        }
        feature_tracking = [tracking[name] for name in feature_names]
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
                return {}, {**problems, **failed}, {}
            proven |= merged
        evidence = {name: TIER_MERGED for name in tips if tracking[name] in proven}
        # An integration line is never judged by patch-id or tree: only by ancestry.
        pending = {
            tracking[name]: tips[name]
            for name in tips
            if name in feature_names and tracking[name] not in proven
        }
        if pending and default_targets:
            found = _offline_evidence(directory, pending, default_targets, refs)
            for name in tips:
                if tracking[name] in found:
                    proven.add(tracking[name])
                    evidence[name] = found[tracking[name]]
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
    return tips, problems, {name: evidence[name] for name in tips}


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
    Every git call of the proof runs from the repository top level, resolved once, so
    a command typed in a subdirectory reads root-relative paths the way git printed them.
    """
    top = run_git(directory, "rev-parse", "--show-toplevel", timeout=Timeout.GIT_CONTEXT)
    if top.returncode != 0 or not top.stdout.strip():
        return RemoteProof(
            tips={},
            problems={
                name: f"the repository top level could not be resolved, so `{name}` is unchecked"
                for name in names
            },
            evidence={},
        )
    directory = Path(top.stdout.strip())
    tips, problems, evidence = _merged_tracking_tips(directory, remote, names, default, branches)
    stale = _live_tip_problems(directory, remote, tips)
    return RemoteProof(
        tips={name: tip for name, tip in tips.items() if name not in stale},
        problems={**problems, **stale},
        evidence={name: tier for name, tier in evidence.items() if name not in stale},
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
