"""Whether remote branches may be deleted: the one proof every remote delete uses.

Plan 00571 Task 2.2 moved this out of the ``destructive_git`` remote-delete guard
(Plan 00558, issue #153) so ``branch-sweep --clean --remote`` deletes exactly what
the guard would let an agent's ``git push --delete`` delete, and no more. Two
callers, one proof: they cannot disagree.

The proof, for each named branch: a literal name that is not the default, exempt or
protected; no tag of the same name; a remote-tracking ref that is merged by the
cheapest offline evidence that holds (Plan 00594 DESIGN.md 2.1): ancestry of the
REMOTE-tracking default (never the local branch, whose commits may be unpushed:
Plan 00626) or, for an ordinary branch, of an integration line's tracking ref; else
SOME commit on the default's first-parent line (after merge-base(default, tip), up
to the default's tip) holding the branch's NET change: its diff against that merge
base, renames off, where every added or modified path has the same blob and mode in
the commit's tree and every deleted path is absent. That is what a squash merge, a
renamed pull request or a cherry-pick leaves behind; the content is then
permanently in the default's history. Cherry-picks the default interleaved with its
own edits leave no single such commit; they are proven when every commit's patch is
in the default (``git cherry``, no merges) AND every changed path is held at its
exact blob by SOME such commit (Plan 00626). Patch-id evidence never proves a
branch alone, and an empty change proves nothing, with TWO exceptions: a tip whose every commit beyond the default is a park commit
(``branch_park.is_park_residue``, the one rule) is ``park-carried``, decided before the
net-change check; and a tip whose every commit beyond the default is empty (one parent,
that parent's tree, any message: ``branch_park.is_content_free``) is
``empty-commits-only`` (Plan 00622). Either way the work is in the default and the delete
loses only those commits. Last, an ordinary branch none of that proves is
``surviving-content`` when every file it adds or changes against
merge-base(remote default, tip) has the same mode and blob at the same path on the
tip of a remote-tracking holder (the default, else an integration line) that the
same command does not delete; each holder relied on is a live-tip anchor, and this
tier is never cached (Plan 00594 Task 3.8). Every git call runs from the repository top level.
Results are written to the inventory cache by algorithm version, tip and remote
default sha, for the offline branch-creation count; only a cached ``unproven`` is
reused here, because a positive read from a writable file could be forged. Then the
remote's LIVE tips, read with one batched ``git ls-remote`` per chunk: the branch's
equal to its tracking tip, and the proving target's (the default, or the line that
proved ancestry) equal to the tracking sha the proof read. Every failure, timeout and
mismatch is a reason, never a pass. The listing is ``utils/remote_refs.py``'s, the
same one ``branch-sweep`` and ``delete-branch`` use, bounded to the named branches.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Collection
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
from claude_code_hooks_daemon.core.branch_park import (
    is_content_free,
    is_park_residue,
    park_marked_refs,
)
from claude_code_hooks_daemon.daemon.branch_safety import (
    TIER_CONTENT_PRESERVED,
    TIER_EMPTY_COMMITS_ONLY,
    TIER_MERGED,
    TIER_PARK_CARRIED,
    TIER_PATCH_EQUIVALENT,
    TIER_SURVIVING_CONTENT,
    TIER_UNPROVEN,
    matches_any_glob,
    patch_equivalent,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX, SEE_SUBMODULES, run_git
from claude_code_hooks_daemon.utils.git_sync import resolve_remote_default_branch
from claude_code_hooks_daemon.utils.remote_refs import list_remote_refs

logger = logging.getLogger(__name__)

#: ``git merge-base`` exits 1 when the two commits share no ancestor.
_NO_MERGE_BASE: Final[int] = 1

#: Fields of one ``git diff --raw`` record (old mode, new mode, old blob, new blob,
#: status) and of one ``git ls-tree`` record (mode, type, blob).
_RAW_META_FIELDS: Final[int] = 5

#: The tree mode of a submodule pointer (a gitlink).
_GITLINK_MODE: Final[str] = "160000"
_LS_TREE_META_FIELDS: Final[int] = 3

#: ``run_git`` decodes with ``errors="replace"``; this marks a path it could not decode.
_REPLACEMENT_CHAR: Final[str] = "\ufffd"

#: First-parent commits of the default one proof will inspect; more is unproven.
MAX_PROOF_CANDIDATES: Final[int] = 50

#: Paths a branch may change and still be proven on the hook path. Each candidate
#: costs one ``ls-tree`` per ``_LS_TREE_CHUNK`` paths, so an unbounded branch could
#: run past the hook timeout on its first, uncached judgement; past this it is unproven.
MAX_PROOF_PATHS: Final[int] = 2000

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
            ``merged``, ``park-carried``, ``empty-commits-only``, ``patch-equivalent``,
            ``content-preserved`` or ``surviving-content``).
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
    """The remote-tracking default, if it exists: the only proof an integration line accepts.

    Never the LOCAL default branch: its commits may not be pushed, and a remote delete
    proven against them would lose work the remote default does not hold (Plan 00626).
    """
    ref = f"{REMOTES_PREFIX}{remote}/{default}"
    return [ref] if ref in refs and refs[ref][1] == "commit" else []


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


def _surviving_holder(
    directory: Path,
    tip: str,
    own_ref: str,
    refs: dict[str, tuple[str, str]],
    remote: str,
    doomed: Collection[str],
) -> str | None:
    """A remote-tracking ref that still exists and contains ``tip``, else None.

    The owner's rule (Q14): a branch whose every commit is an ancestor of another
    branch that survives the command loses nothing when it goes. One
    ``for-each-ref --contains`` lists the refs holding the tip; ``doomed`` (every
    branch the same command deletes) and the branch itself never count, and the
    ``HEAD`` alias is not a branch. The first holder by name is returned so the
    answer is stable, and the caller anchors it so the remote's live tip is confirmed.
    """
    prefix = f"{REMOTES_PREFIX}{remote}/"
    held = run_git(
        directory,
        "for-each-ref",
        f"--contains={tip}",
        "--format=%(refname)",
        prefix,
        timeout=Timeout.GIT_CONTEXT,
    )
    if held.returncode != 0:
        return None
    for ref in sorted(held.stdout.splitlines()):
        if (
            ref != own_ref
            and ref not in doomed
            and ref != f"{prefix}HEAD"
            and refs.get(ref, ("", ""))[1] == "commit"
        ):
            return ref
    return None


class ProofUnavailableError(RuntimeError):
    """Git failed while judging a branch, so its answer is unknown and must not be cached."""


@dataclass(frozen=True)
class _PathChange:
    """One path the branch changed against the merge base (renames and copies off)."""

    path: str
    deleted: bool
    mode: str
    blob: str
    gitlink: bool = False


def _net_change(
    directory: Path, base: str, tracking_ref: str, *, timeout: float
) -> list[_PathChange]:
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
        SEE_SUBMODULES,
        base,
        tracking_ref,
        timeout=timeout,
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
        old_mode, new_mode, _old_blob, new_blob, status = meta
        changes.append(
            _PathChange(
                fields[index + 1],
                status.startswith("D"),
                new_mode,
                new_blob,
                _GITLINK_MODE in (old_mode, new_mode),
            )
        )
    return changes


def gitlink_change_held(
    directory: Path, target: str, tracking_ref: str, *, timeout: float = Timeout.GIT_CONTEXT
) -> bool:
    """Whether patch-id evidence may stand for the branch's submodule pointers.

    ``git cherry`` drops a gitlink from its patch-ids under ``.gitmodules``
    ``ignore = all``, and takes no flag to undo it, so a commit that adds a file
    the target has AND moves a submodule pointer reads as already upstream. True
    when the branch's net change moves no pointer, or when the target's history
    holds the whole net change path by path (pointer included). No merge base is
    False: the net change cannot be read, and ``git cherry`` then matches against
    the whole history. ``directory`` must be the repository top level.

    Raises:
        ProofUnavailableError: git failed, so there is no answer.
    """
    base = run_git(directory, "merge-base", target, tracking_ref, timeout=timeout)
    if base.returncode == _NO_MERGE_BASE:
        return False
    if base.returncode != 0:
        raise ProofUnavailableError(f"git merge-base failed for {tracking_ref}")
    changes = _net_change(directory, base.stdout.strip(), tracking_ref, timeout=timeout)
    if not any(change.gitlink for change in changes):
        return True
    state = _net_change_state(directory, target, tracking_ref, timeout=timeout)
    return state in (_HELD, _HELD_PER_PATH)


def _tree_entries(
    directory: Path, commit: str, paths: list[str], *, timeout: float
) -> dict[str, tuple[str, str]]:
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
            timeout=timeout,
        )
        if listing.returncode != 0:
            raise ProofUnavailableError(f"git ls-tree failed for {commit}")
        for entry in listing.stdout.split("\0"):
            meta, _, path = entry.partition("\t")
            parts = meta.split(" ")
            if path and len(parts) == _LS_TREE_META_FIELDS:
                held[path] = (parts[0], parts[2])
    return held


def _touching_commits(
    directory: Path, base: str, target: str, paths: list[str], *, timeout: float
) -> list[str]:
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
            timeout=timeout,
        )
        if listing.returncode != 0:
            raise ProofUnavailableError(f"git log failed for {target}")
        commits.update(dict.fromkeys(listing.stdout.split()))
    return list(commits)


def holds_net_change(
    directory: Path, target: str, tracking_ref: str, *, timeout: float = Timeout.GIT_CONTEXT
) -> bool:
    """Whether the default's first-parent history holds the whole net change of the branch.

    Shared with ``branch_safety``'s local ``content-preserved`` tier, so a local and a
    remote delete rest on the same per-path proof (Plan 00618 B-1).

    The net change is the branch's diff against ``merge-base(target, tip)``. It is
    held by a commit whose tree has every added or modified path at the same blob
    and mode and every deleted path absent. The target's tip is tried first, then
    the first-parent commits after the merge base that touched those paths (a state
    that holds the change was reached by a commit that touched one of them). Once a
    commit held it the content is permanently in the default's history, even if the
    default has changed it since. More candidates than ``MAX_PROOF_CANDIDATES``, or
    more changed paths than ``MAX_PROOF_PATHS``, is unproven, as is an empty net
    change (empty commits, or changes that cancel out). ``target`` is whatever ref
    the caller names: the remote-delete proof passes only the remote-tracking
    default, whose live tip it then confirms (Plan 00626); ``branch_safety``'s local
    delete passes local refs. ``timeout`` is each git call's budget: the hook-context default here, the
    load-scaled branch-safety budget from ``delete-branch``. A timeout is a failure.

    Raises:
        ProofUnavailableError: git failed, so there is no answer to cache.
    """
    return _net_change_state(directory, target, tracking_ref, timeout=timeout) == _HELD


_HELD: Final[str] = "held"
_HELD_PER_PATH: Final[str] = "held-per-path"
_EMPTY: Final[str] = "empty"
_NOT_HELD: Final[str] = "not-held"


def _held_changes(
    directory: Path, commit: str, changes: list[_PathChange], *, timeout: float
) -> set[str]:
    """The paths of ``changes`` that ``commit``'s tree holds: same blob and mode, or absent."""
    held = _tree_entries(directory, commit, [change.path for change in changes], timeout=timeout)
    return {
        change.path
        for change in changes
        if (
            change.path not in held
            if change.deleted
            else held.get(change.path) == (change.mode, change.blob)
        )
    }


def _net_change_state(directory: Path, target: str, tracking_ref: str, *, timeout: float) -> str:
    """:func:`holds_net_change`'s answer, telling an EMPTY net change from one not held.

    ``_HELD``: one commit (the target's tip, else a first-parent commit after the merge
    base that touched a changed path) holds the whole net change. ``_HELD_PER_PATH``:
    no single commit does, but every changed path is held at the branch's exact blob
    and mode (a deletion: absent) by SOME such commit. That is what cherry-picks the
    default interleaved with its own edits leave behind (Plan 00626); it proves a
    branch only together with patch equivalence (:func:`_judge_offline`), never alone.
    ``_EMPTY`` (the branch's diff against the merge base is nothing) is never a proof
    here; only the caller's empty-commit walk may prove such a branch (Plan 00622).
    No merge base at all is ``_NOT_HELD``, so ``git cherry``'s whole-history match
    never reaches a proof.

    Raises:
        ProofUnavailableError: git failed, so there is no answer to cache.
    """
    base = run_git(directory, "merge-base", target, tracking_ref, timeout=timeout)
    if base.returncode == _NO_MERGE_BASE:
        return _NOT_HELD
    if base.returncode != 0:
        raise ProofUnavailableError(f"git merge-base failed for {tracking_ref}")
    merge_base = base.stdout.strip()
    changes = _net_change(directory, merge_base, tracking_ref, timeout=timeout)
    if not changes:
        return _EMPTY
    if len(changes) > MAX_PROOF_PATHS:
        return _NOT_HELD
    every_path = {change.path for change in changes}
    seen = _held_changes(directory, target, changes, timeout=timeout)
    if seen == every_path:
        return _HELD
    paths = [c.path for c in changes]
    candidates = _touching_commits(directory, merge_base, target, paths, timeout=timeout)
    if len(candidates) > MAX_PROOF_CANDIDATES:
        return _NOT_HELD
    for commit in candidates:
        held = _held_changes(directory, commit, changes, timeout=timeout)
        if held == every_path:
            return _HELD
        seen |= held
    return _HELD_PER_PATH if seen == every_path else _NOT_HELD


@dataclass(frozen=True)
class _ContentFinding:
    """What :func:`_surviving_content` found for one branch.

    ``gaps`` are the paths whose content no holder's tip has; empty is the proof.
    ``holders`` are the holder refs whose tips the proof relied on (each path's first
    holder). The caller anchors these and the default (the merge base's source), so
    the live check confirms each is still the tip the proof read.
    """

    gaps: list[str]
    holders: list[str]


def _surviving_content(
    directory: Path, tracking_ref: str, tracking_default: str, holders: list[str]
) -> _ContentFinding | None:
    """Whether every file the branch adds or changes already exists on a holder's tip.

    The branch's net change is its diff against ``merge-base(tracking_default, tip)``:
    the REMOTE-tracking default only, never the local one (Plan 00626). Each added or
    changed path must have the same mode and blob at the same path on at least one
    holder's tip. ``holders`` are remote-tracking refs: the default first, then the
    declared integration lines, never a ref this command deletes (the caller's filter).
    A path the branch DELETES is not content and is ignored, so a branch of only
    deletions, or of no change at all, has nothing to find elsewhere and is ``None``,
    as is a branch with no merge base against the default or with more changed paths
    than ``MAX_PROOF_PATHS``.

    Raises:
        ProofUnavailableError: git failed, so there is no answer.
    """
    base = run_git(
        directory, "merge-base", tracking_default, tracking_ref, timeout=Timeout.GIT_CONTEXT
    )
    if base.returncode == _NO_MERGE_BASE:
        return None
    if base.returncode != 0:
        raise ProofUnavailableError(f"git merge-base failed for {tracking_ref}")
    changes = _net_change(directory, base.stdout.strip(), tracking_ref, timeout=Timeout.GIT_CONTEXT)
    content = [change for change in changes if not change.deleted]
    if not content or len(changes) > MAX_PROOF_PATHS:
        return None
    paths = [change.path for change in content]
    held = [
        (holder, _tree_entries(directory, holder, paths, timeout=Timeout.GIT_CONTEXT))
        for holder in holders
    ]
    gaps: list[str] = []
    used: dict[str, None] = {}
    for change in content:
        holder = next(
            (
                ref
                for ref, entries in held
                if entries.get(change.path) == (change.mode, change.blob)
            ),
            None,
        )
        if holder is None:
            gaps.append(change.path)
        else:
            used[holder] = None
    return _ContentFinding(sorted(gaps), list(used))


#: Paths named in a refusal before the rest are counted.
_GAP_PREVIEW: Final[int] = 5


def _content_gap_note(gaps: list[str] | None) -> str:
    """The sentence saying why the surviving-content proof did not accept a branch."""
    if gaps is None:
        return (
            "; nor can its content be shown to exist elsewhere (it adds or changes no file, "
            "has no merge base with the remote default, or changes more than "
            f"{MAX_PROOF_PATHS} paths)"
        )
    shown = ", ".join(f"`{path}`" for path in gaps[:_GAP_PREVIEW])
    rest = len(gaps) - _GAP_PREVIEW
    more = f" and {rest} more" if rest > 0 else ""
    return (
        f"; and {len(gaps)} file(s) it holds exist with that content on no surviving ref "
        f"(the remote default or an integration line's remote tip): {shown}{more}"
    )


def _judge_offline(directory: Path, tracking_ref: str, targets: list[str]) -> str:
    """The tier that proves one tracking ref merged into a default ref, or ``unproven``.

    The default's history must hold the branch's net change, and that check comes
    FIRST, so neither patch-id evidence alone nor an empty commit on the default can
    prove a branch. Held by one commit (:func:`holds_net_change`): ``patch-equivalent``
    when every commit has its patch in the default, else ``content-preserved`` (a
    squash), the same proof ``branch_safety``'s local ``content-preserved`` tier
    requires. Held only path by path (``_HELD_PER_PATH``: cherry-picks the default
    interleaved with its own edits, Plan 00626): ``patch-equivalent`` and nothing
    else, so ``git cherry`` must ALSO find every non-park commit's patch, with no merge
    in the range. The exact blobs close patch-id's whitespace blindness, and a merge
    base is required, so its whole-history match never proves.
    An EMPTY net change proves nothing by itself; such a branch is proven only when
    every commit it has beyond the default is empty (one parent, that parent's tree,
    any message): ``empty-commits-only`` (Plan 00622). Only an empty net change pays
    for that walk.

    Raises:
        ProofUnavailableError: git failed, so there is no answer to cache.
    """
    for target in targets:
        state = _net_change_state(directory, target, tracking_ref, timeout=Timeout.GIT_CONTEXT)
        if state == _EMPTY:
            content_free = is_content_free(directory, tracking_ref, target)
            if content_free is None:
                raise ProofUnavailableError(f"git log failed for {tracking_ref}")
            if content_free:
                return TIER_EMPTY_COMMITS_ONLY
            continue
        if state not in (_HELD, _HELD_PER_PATH):
            continue
        equivalent, count = patch_equivalent(directory, target, tracking_ref)
        if count is None:
            raise ProofUnavailableError(f"git cherry failed for {tracking_ref}")
        if equivalent:
            return TIER_PATCH_EQUIVALENT
        if state == _HELD:
            return TIER_CONTENT_PRESERVED
    return TIER_UNPROVEN


def _offline_evidence(
    directory: Path, pending: dict[str, str], targets: list[str], refs: dict[str, tuple[str, str]]
) -> dict[str, str]:
    """``name -> tier`` for each pending tracking ref whose net change the default holds.

    ``pending`` maps the tracking refname to its tip. Answers are written to the
    inventory cache keyed by algorithm version, tip and the REMOTE default's sha (the
    only target), so the offline branch-creation count can read them. A cached
    ``unproven`` is reused, since it can only refuse. A cached POSITIVE is never
    trusted here: the cache is a plain file in the working tree that anyone can write,
    so a delete that rested on it could be forged (Plan 00626); it is recomputed.
    Targets at the same sha are judged once.
    """
    by_sha = {refs[target][0]: target for target in targets}
    judged_targets = list(by_sha.values())
    cached = read_merge_proofs(directory)
    fresh: dict[str, str] = {}
    found: dict[str, str] = {}
    for tracking_ref, tip in pending.items():
        key = merge_proof_key(tip, by_sha)
        tier = cached.get(key)
        if tier != TIER_UNPROVEN:
            try:
                judged = _judge_offline(directory, tracking_ref, judged_targets)
            except ProofUnavailableError as exc:
                log_and_continue(
                    logger,
                    exc,
                    reason="an unanswered proof leaves the branch unproven, which refuses its delete",
                )
                continue
            if judged != tier:
                fresh[key] = judged
            tier = judged
        if tier != TIER_UNPROVEN:
            found[tracking_ref] = tier
    if fresh:
        write_merge_proofs(directory, fresh)
    return found


@dataclass(frozen=True)
class _LocalProof:
    """What the offline half proved, before the remote's live tips confirm it.

    ``anchors`` maps each proven name to the proof targets it rests on, as remote
    branch name to the tracking sha the proof read, so the live check can confirm
    the remote still has exactly those (Plan 00626).
    """

    tips: dict[str, str]
    problems: dict[str, str]
    evidence: dict[str, str]
    anchors: dict[str, dict[str, str]]


def _merged_tracking_tips(
    directory: Path,
    remote: str,
    names: list[str],
    default: str,
    branches: BranchesConfig,
    also_deleting: Collection[str] = (),
) -> _LocalProof:
    """Each name's tracking tip, problem or evidence, judged from local git only.

    ``also_deleting`` names other branches the same command removes: neither they nor
    ``names`` may vouch for a branch's content (:func:`_surviving_content_gaps`).

    One listing call, then one ``for-each-ref --merged`` per target over all the named
    refs; only a branch ancestry did not settle pays the patch-id and tree checks.
    Every target is a REMOTE-tracking ref: a remote delete is proven against what the
    remote holds, never the local default, whose commits may not be pushed (Plan
    00626). A missing tracking default refuses every name. The remote's live tips,
    the deleted branches' and the targets', are checked afterwards by
    :func:`_live_tip_problems`.
    """
    tracking = {name: f"{REMOTES_PREFIX}{remote}/{name}" for name in names}
    tracking_default = f"{REMOTES_PREFIX}{remote}/{default}"
    refs = _listed_refs(
        directory,
        [f"{REMOTES_PREFIX}{remote}", *[f"{TAGS_PREFIX}{name}" for name in names]],
    )
    if refs is None:
        return _LocalProof(
            {},
            {
                name: f"`git for-each-ref` failed, so `{name}` could not be checked"
                for name in names
            },
            {},
            {},
        )
    if refs.get(tracking_default, ("", ""))[1] != "commit":
        return _LocalProof(
            {},
            {
                name: (
                    f"the remote default `{tracking_default}` does not exist here, so `{name}` "
                    f"cannot be proven merged on {remote}; run `git fetch {remote}` and retry"
                )
                for name in names
            },
            {},
            {},
        )
    tips: dict[str, str] = {}
    problems: dict[str, str] = {}
    anchored_by: dict[str, str] = {}
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
    content_gaps: dict[str, list[str] | None] = {}
    content_anchors: dict[str, list[str]] = {}
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
                return _LocalProof({}, {**problems, **failed}, {}, {})
            for ref in merged - proven:
                anchored_by[ref] = target
            proven |= merged
        evidence = {name: TIER_MERGED for name in tips if tracking[name] in proven}
        doomed = {f"{REMOTES_PREFIX}{remote}/{n}" for n in (*names, *also_deleting)}
        # Contained in another branch that survives this command (Q14): every commit
        # is held there, so the delete loses nothing. Never for an integration line.
        for name in sorted(feature_names):
            if tracking[name] in proven:
                continue
            holder = _surviving_holder(directory, tips[name], tracking[name], refs, remote, doomed)
            if holder is not None:
                proven.add(tracking[name])
                evidence[name] = TIER_MERGED
                anchored_by[tracking[name]] = holder
        # An integration line is never judged by patch-id or tree: only by ancestry.
        pending = {
            tracking[name]: tips[name]
            for name in tips
            if name in feature_names and tracking[name] not in proven
        }
        # A park marker over work the default holds: decided by the inventory's rule,
        # before the (cached) net-change proof, which reads an empty change as unproven.
        undecided = [n for n in tips if n in feature_names and tracking[n] not in proven]
        marked = (
            park_marked_refs(
                directory, [tracking[n] for n in undecided], timeout=Timeout.GIT_CONTEXT
            )
            if default_targets
            else set()
        )
        for name in [n for n in undecided if tracking[n] in marked]:
            if any(is_park_residue(directory, tips[name], target) for target in default_targets):
                proven.add(tracking[name])
                evidence[name] = TIER_PARK_CARRIED
                pending.pop(tracking[name], None)
        if pending and default_targets:
            found = _offline_evidence(directory, pending, default_targets, refs)
            for name in tips:
                if tracking[name] in found:
                    proven.add(tracking[name])
                    evidence[name] = found[tracking[name]]
        # Not merged by any history evidence: is anything in it unique? Judged afresh
        # every time (a cached answer would not see a line or default moving), and
        # against surviving refs only, so a ref deleted with it cannot vouch for it.
        # Every holder is a remote-tracking ref (Plan 00626); each one relied on, and the
        # default that sets the merge base, is confirmed live by `_live_tip_problems`
        # through the anchors.
        holders = [
            target
            for target in _proof_targets(remote, default, branches, refs)
            if target not in doomed
        ]
        for name in sorted(feature_names):
            if tracking[name] in proven or tracking_default not in holders:
                continue
            finding: _ContentFinding | None
            try:
                finding = _surviving_content(directory, tracking[name], tracking_default, holders)
            except ProofUnavailableError as exc:
                log_and_continue(
                    logger,
                    exc,
                    reason="an unanswered content proof leaves the branch unproven, which refuses its delete",
                )
                finding = None
            if finding is not None and not finding.gaps and finding.holders:
                proven.add(tracking[name])
                evidence[name] = TIER_SURVIVING_CONTENT
                # The default is a proof input even when no path is credited to it: it
                # sets the merge base, so a remote default rewound past a commit the
                # branch carries would drop that commit out of the diff unseen.
                content_anchors[name] = list(dict.fromkeys([tracking_default, *finding.holders]))
            else:
                content_gaps[name] = None if finding is None else finding.gaps
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
                note = _content_gap_note(content_gaps[name]) if name in content_gaps else ""
                problems[name] = f"`{name}` is not merged into `{default}`{lines}{note}"
    tracking_prefix = f"{REMOTES_PREFIX}{remote}/"
    anchors: dict[str, dict[str, str]] = {}
    for name in tips:
        targets = content_anchors.get(name) or [anchored_by.get(tracking[name], tracking_default)]
        anchors[name] = {
            target.removeprefix(tracking_prefix): refs[target][0] for target in targets
        }
    return _LocalProof(tips, problems, {name: evidence[name] for name in tips}, anchors)


def live_remote_tips(directory: Path, remote: str, names: list[str]) -> dict[str, str]:
    """Map branch name to the tip ``remote`` reports, from one ``ls-remote`` per chunk.

    Fails closed: a failed or timed-out listing contributes nothing, so its branches
    are absent from the map. Lines are keyed by their exact ref, so a pattern that
    also matches a longer name (``feat`` and ``feat-2``) or a foreign ref ending in
    the name never lends its tip to another branch.
    """
    return live_remote_listing(directory, remote, names)[0]


def live_remote_listing(
    directory: Path, remote: str, names: list[str]
) -> tuple[dict[str, str], list[str]]:
    """:func:`live_remote_tips` plus the reason of each listing that failed."""
    tips: dict[str, str] = {}
    failures: list[str] = []
    for start in range(0, len(names), LS_REMOTE_CHUNK):
        chunk = names[start : start + LS_REMOTE_CHUNK]
        listing = list_remote_refs(
            directory,
            remote,
            patterns=tuple(f"{HEADS_PREFIX}{name}" for name in chunk),
            timeout=Timeout.GIT_CONTEXT,
        )
        if listing.failure is not None:
            failures.append(listing.failure)
            continue
        for listed, tip in listing.refs:
            if listed.startswith(HEADS_PREFIX):
                tips[listed.removeprefix(HEADS_PREFIX)] = tip
    return tips, failures


def _live_tip_problems(directory: Path, remote: str, proof: _LocalProof) -> dict[str, str]:
    """Why the remote's live tips are not the ones the offline proof read.

    The remote-tracking refs are only as fresh as the last fetch, and any of them can
    be moved locally (``git update-ref``). A commit pushed to the branch since would
    be lost by the delete; a proof target (the default, or the integration line that
    proved ancestry) the remote does not hold at that sha proves nothing about the
    remote. ``git ls-remote`` asks the remote itself, once for every branch and
    target; it never fetches. A failed listing confirms nothing.
    """
    if not proof.tips:
        return {}
    targets = {line for anchor in proof.anchors.values() for line in anchor}
    live, failures = live_remote_listing(directory, remote, sorted({*proof.tips, *targets}))
    cause = f" (git ls-remote said: {'; '.join(failures)})" if failures else ""
    problems: dict[str, str] = {}
    for name, tip in proof.tips.items():
        if live.get(name) != tip:
            problems[name] = (
                f"the remote tip of `{name}` could not be confirmed as merged (it differs from "
                f"`{REMOTES_PREFIX}{remote}/{name}`, is gone, or `git ls-remote {remote}` failed)"
                f"{cause}; run `git fetch` and retry"
            )
            continue
        moved = [line for line, sha in proof.anchors.get(name, {}).items() if live.get(line) != sha]
        if moved or not proof.anchors.get(name):
            problems[name] = (
                f"`{name}` was proven against `{REMOTES_PREFIX}{remote}/{', '.join(moved)}`, "
                f"which differs from what {remote} holds now (or `git ls-remote {remote}` "
                f"failed){cause}; run `git fetch {remote}` and retry"
            )
    return {**problems, **_push_url_problems(directory, remote, proof, live, set(problems))}


def _other_push_urls(directory: Path, remote: str) -> list[str] | None:
    """Each push URL of ``remote`` that is not its fetch URL, or None when unreadable.

    ``git ls-remote <remote>`` reads the fetch URL while ``git push <remote> --delete``
    goes to every push URL (``pushurl`` / ``pushInsteadOf``), which may be another
    repository. ``git remote get-url`` applies both rewrites. A URL that would parse
    as an option is unreadable, never passed on.
    """
    fetch = run_git(directory, "remote", "get-url", remote, timeout=Timeout.GIT_CONTEXT)
    push = run_git(
        directory, "remote", "get-url", "--push", "--all", remote, timeout=Timeout.GIT_CONTEXT
    )
    if fetch.returncode != 0 or push.returncode != 0:
        return None
    urls = [url for url in push.stdout.splitlines() if url]
    if not urls or any(url.startswith("-") for url in urls):
        return None
    return [url for url in dict.fromkeys(urls) if url != fetch.stdout.strip()]


def _push_url_problems(
    directory: Path, remote: str, proof: _LocalProof, live: dict[str, str], settled: set[str]
) -> dict[str, str]:
    """Why a push URL that differs from the fetch URL does not hold what the proof read.

    Every push URL must report each deleted branch at its proven tip and each anchor
    at its proven sha, exactly as the fetch URL did; a push URL naming the same
    repository by another spelling therefore passes. The URL is never quoted, as it
    can carry a credential.
    """
    pending = [name for name in proof.tips if name not in settled]
    if not pending:
        return {}
    urls = _other_push_urls(directory, remote)
    if urls is None:
        return {
            name: (
                f"a push URL of {remote} could not be read, so the delete's destination is "
                f"unconfirmed and `{name}` is unchecked"
            )
            for name in pending
        }
    problems: dict[str, str] = {}
    for url in urls:
        names = sorted({*pending, *(line for n in pending for line in proof.anchors[n])})
        pushed, _ = live_remote_listing(directory, url, names)
        for name in pending:
            expected = {name: proof.tips[name], **proof.anchors[name]}
            if any(
                pushed.get(ref) != live.get(ref) or live.get(ref) != sha
                for ref, sha in expected.items()
            ):
                problems[name] = (
                    f"a push URL of {remote} (where the delete goes) does not hold `{name}` "
                    f"and what proved it at the tips its fetch URL reported, so `{name}` is "
                    "unconfirmed there"
                )
    return problems


def prove_remote_merged(
    directory: Path,
    remote: str,
    names: list[str],
    default: str,
    branches: BranchesConfig,
    also_deleting: Collection[str] = (),
) -> RemoteProof:
    """Prove each of ``names`` (bare branch names, already past :func:`named_ref_problem`).

    ``also_deleting`` is every other branch the same command deletes; none may vouch
    for another's content (the surviving-content tier).

    Contacts the remote (``ls-remote``) only for the names the local proof accepted.
    ``default`` must be the remote's own default (:func:`resolve_remote_default_branch`),
    whoever resolved it: a caller that took a local ``main`` fallback is refused here,
    so no remote-delete path can judge against a stale branch (Plan 00626).
    Every git call of the proof runs from the repository top level, resolved once, so
    a command typed in a subdirectory reads root-relative paths the way git printed them.
    """
    top = run_git(directory, "rev-parse", "--show-toplevel", timeout=Timeout.GIT_CONTEXT)
    if top.returncode != 0 or not top.stdout.strip():
        return RemoteProof(
            tips={},
            problems={
                name: f"not inside a work tree (no top level to run the proof from), so `{name}` is unchecked"
                for name in names
            },
            evidence={},
        )
    directory = Path(top.stdout.strip())
    remote_default = resolve_remote_default_branch(branches, directory, remote=remote)
    if remote_default != default:
        known = f"`{remote_default}`" if remote_default else "unknown here"
        return RemoteProof(
            tips={},
            problems={
                name: (
                    f"`{default}` is not confirmed as {remote}'s default branch ({known}: "
                    f"`branches.default: auto` reads only `refs/remotes/{remote}/HEAD`; run "
                    f"`git remote set-head {remote} --auto` or set `branches.default`), so "
                    f"`{name}` is unchecked"
                )
                for name in names
            },
            evidence={},
        )
    local = _merged_tracking_tips(directory, remote, names, default, branches, also_deleting)
    stale = _live_tip_problems(directory, remote, local)
    return RemoteProof(
        tips={name: tip for name, tip in local.tips.items() if name not in stale},
        problems={**local.problems, **stale},
        evidence={name: tier for name, tier in local.evidence.items() if name not in stale},
    )


__all__ = [
    "LITERAL_BRANCH_NAME",
    "LS_REMOTE_CHUNK",
    "REMOTES_PREFIX",
    "TAGS_PREFIX",
    "RemoteProof",
    "branch_name",
    "live_remote_listing",
    "live_remote_tips",
    "named_ref_problem",
    "prove_remote_merged",
]
