"""Branch inventory and classification (Plan 00558, DESIGN.md sections 2, 4 and 5).

One record per branch NAME (a local branch and its remote copy are one record),
built for the sweep, the guards and the CLI from a fixed number of bulk git
processes plus a bounded per-branch step:

1. one ``for-each-ref`` over ``refs/heads`` and ``refs/remotes/<remote>``: tips,
   committer dates, upstreams, ahead/behind the default, the park trailer and
   the tip subject;
2. ``worktree list --porcelain``: the worktree holding each branch;
3. ``for-each-ref --merged=<target>`` per default ref and integration line: the
   bulk ancestry test;
4. same-tip grouping, in Python;
5. per unmerged tip and target: a ``log`` walk (ahead, park commits, merge
   commits), ``git cherry`` via :func:`branch_safety.cherry_unique_shas` and
   ``diff --shortstat`` (lines). Cached by ``(tip, target, lines wanted)`` in
   ``untracked/branch-inventory/cache.json`` and cut off at ``sweep.budget_ms``;
   a branch not reached is ``UNCLASSIFIED``, never guessed.

Every git error fails CLOSED: a branch whose proof could not be computed is
``UNCLASSIFIED``, never merged. In particular:

- a name whose local and remote copies sit at different tips is merged,
  patch-equivalent or contained only when EVERY copy is (the weakest proof
  wins), and ``proven_by`` names the ref that proved it, so a merge into an
  unpushed local default is told apart from one into ``<remote>/<default>``;
- a range holding a merge commit is never patch-equivalent: ``git cherry``
  never lists merges, so content added by a merge (a conflict resolution, an
  "evil merge") would otherwise be invisible;
- a listing row that cannot be parsed is ``UNCLASSIFIED`` with a reason, never
  dropped and never given a default date;
- a failed ``worktree list`` leaves ``worktree_known`` False, never "no worktree".

Park commits (DESIGN.md section 5): a commit whose tree equals its parent's and
that carries a ``Parked-*`` or ``Unparked`` trailer is not counted in ``ahead``
and never makes a branch look unique. ``lines`` is a tree diff, so empty commits
never reach it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import DEFAULT_STACK_MAX_DEPTH, BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.branch_keep import read_keeps
from claude_code_hooks_daemon.core.branch_park import (
    ParkRecord,
    park_covers_tip,
    read_park_records,
    walk_park_range,
)
from claude_code_hooks_daemon.core.branch_records import CREATOR_KEY
from claude_code_hooks_daemon.core.branch_stacks import read_tip_ancestry
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.utils import git_sync
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.load_scaling import branch_metadata_timeout, scaled_timeout
from claude_code_hooks_daemon.utils.remote_refs import (
    RemoteRefs,
    RemoteSource,
    holder_of,
    made_listing,
    resolve_source,
)

logger = logging.getLogger(__name__)

#: Repository-relative path of the per-pair cache.
CACHE_RELATIVE_PATH = Path("untracked/branch-inventory/cache.json")
#: Containment never counts tags; a version-2 entry may hold a tag's vouch. Version 5:
#: a park commit must carry the park writer's exact message (Plan 00617). Version 6:
#: the net change sees a submodule pointer git was told to ignore (Plan 00594).
_CACHE_VERSION = 6

_SECONDS_PER_DAY = 86_400
_REFS = "refs/"
_HEADS = "refs/heads/"
_REMOTES = "refs/remotes/"
_REMOTE_HEAD = "HEAD"
#: Field separator of the step-1 listing. A commit message cannot hold a NUL
#: (git refuses one), and neither can a ref name, sha, date or count.
_FIELD = "\x00"
#: for-each-ref ends every record with a newline after the format's trailing NUL.
_RECORD_END = "\n"
_FIELD_COUNT = 9
_UNIT = "\x1f"
_GIT_TIMEOUT = Timeout.GIT_CONTEXT
_OBJECT_NAME = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

_PARK_REASON_KEY = "Parked-Reason"

_ISSUE_IN_NAME = re.compile(r"(?:^|[-_/])(?:issue|gh)-(\d+)(?=$|[-_/])", re.IGNORECASE)
_NAME_TOKEN_SPLIT = re.compile(r"[-_/.]")
_PLAN_TOKEN = re.compile(r"\d{2,5}")
_ISSUE_IN_SUBJECT = re.compile(r"Addresses #(\d+)")
_PLAN_IN_SUBJECT = re.compile(r"\bPlan (\d{2,5})\b")
_PLAN_WIDTH = 5
_SHORTSTAT_COUNT = re.compile(r"(\d+) (?:insertion|deletion)")

#: Why a tip is UNCLASSIFIED: the run's time budget (``branches.sweep.budget_ms``) was spent.
BUDGET_REASON = (
    "the sweep budget ran out before this tip was measured against every target; "
    "raise branches.sweep.budget_ms, or run branch-sweep --budget-ms N"
)
#: Why a tip is UNCLASSIFIED when git itself failed on it; ``{target}`` names the target.
_GIT_FAILED_REASON = (
    "git failed measuring this tip against {target}; "
    "raising branches.sweep.budget_ms will not help"
)
#: Why a tip is UNCLASSIFIED in a shallow clone whose fork point was not fetched.
_SHALLOW_REASON = (
    "history not fetched: this is a shallow clone and no merge base with {target} "
    "is present; deepen the clone (git fetch --unshallow)"
)


@dataclass(frozen=True)
class HistoryNotFetched:
    """A shallow clone lacks the history needed to find the tip's merge base."""


class BranchInventoryError(RuntimeError):
    """The refs could not be listed at all, so there is no inventory to return."""


class BranchState(StrEnum):
    """DESIGN.md section 2 states; the first that matches wins."""

    EXEMPT = "exempt"
    #: Matches ``branches.bot_owned`` (``dependabot/*``): in no pool, never cleaned.
    BOT_OWNED = "bot-owned"
    #: Not this clone's branch (DESIGN.md section 2.2): in no pool, never cleaned
    #: automatically; ``BranchRecord.proof_state`` keeps a merge proof if it has one.
    FOREIGN = "foreign"
    DEFAULT = "default"
    INTEGRATION_LINE = "integration-line"
    PROTECTED = "protected"
    MERGED_DEFAULT = "merged"
    MERGED_LINE = "merged-into-line"
    PATCH_EQUIVALENT = "patch-equivalent"
    #: A park marker (an empty ``Parked-*`` commit) over work the default already holds:
    #: nothing is unique but the marker, so it is in no pool and its delete is proven.
    PARK_CARRIED = "park-carried"
    #: The remote-tracking default holds the branch's whole net change (a squash, or
    #: the same bytes reaching it another way). Proved only by an inventory built with
    #: ``prove_content`` (``branch-sweep --clean``); every other pass calls it LIVE.
    CONTENT_PRESERVED = "content-preserved"
    PARKED = "parked"
    DORMANT = "dormant"
    LIVE = "live"
    UNCLASSIFIED = "not yet classified"


#: "Done, not deleted" (DESIGN.md section 2, states 3-5), strongest proof first.
_DONE_RANK = {
    BranchState.MERGED_DEFAULT: 0,
    BranchState.MERGED_LINE: 1,
    BranchState.PATCH_EQUIVALENT: 2,
    BranchState.PARK_CARRIED: 3,
    BranchState.CONTENT_PRESERVED: 4,
}


class Pool(StrEnum):
    """The three pools a work branch can be in (Plan 00571 DESIGN.md section 1)."""

    OPEN = "open"
    PARKED = "parked"
    MERGED = "merged"


_POOL_OF_STATE = {
    BranchState.MERGED_DEFAULT: Pool.MERGED,
    BranchState.MERGED_LINE: Pool.MERGED,
    BranchState.PATCH_EQUIVALENT: Pool.MERGED,
    BranchState.CONTENT_PRESERVED: Pool.MERGED,
    BranchState.PARKED: Pool.PARKED,
    BranchState.LIVE: Pool.OPEN,
    BranchState.DORMANT: Pool.OPEN,
    # Fail closed: a branch not yet classified is counted as open work.
    BranchState.UNCLASSIFIED: Pool.OPEN,
}


def pool_of(state: BranchState) -> Pool | None:
    """The pool of a record in ``state``; None for a branch that is never work."""
    return _POOL_OF_STATE.get(state)


def pool_for_ref(*, merged: bool, park_carried: bool, parked: bool) -> Pool | None:
    """The pool of one ref from its facts: the rule the creation guard and the sweep share.

    A park marker over work the default holds is in no pool (None); a ref the
    default holds is MERGED; a park trailer on a tip nothing else holds is PARKED;
    anything else is open work. :func:`pool_of` is this rule applied to a state, and
    a test pins the two together.
    """
    if park_carried:
        return None
    if merged:
        return Pool.MERGED
    return Pool.PARKED if parked else Pool.OPEN


class DormancyStage(StrEnum):
    """DESIGN.md section 4 stages."""

    ADVISORY = "advisory"
    NOISY = "noisy"
    BLOCK = "block"


class Containment(StrEnum):
    """Where an idle branch's tip lives (DESIGN.md section 4).

    Only ``DEFAULT`` and ``REMOTE_REF`` make a cleanup candidate, and
    ``REMOTE_REF`` is granted only by a ref that is not itself work: the
    default, an integration line, an exempt or a protected branch on the
    remote (never a tag, which may be local only). Work
    branches that contain each other are ``OTHER_WORK_BRANCH``: two copies of
    unmerged work never vouch for each other.
    """

    DEFAULT = "in the default branch"
    REMOTE_REF = "in another remote ref"
    OWN_REMOTE = "on its own remote only"
    OTHER_WORK_BRANCH = "only in another work branch"
    NOWHERE = "nowhere"
    #: The remote holds it outside every ref this clone fetches (an archive
    #: namespace). Only an explicit ``ls-remote`` can show this, so it is granted
    #: only when the caller passed a listing; the offline inventory never reports it.
    REMOTE_UNFETCHED = "on the remote outside the fetched refs"


@dataclass(frozen=True)
class BranchRecord:
    """One branch name, local and remote copies together."""

    name: str
    state: BranchState
    local_tip: str | None
    remote_tip: str | None
    upstream: str | None
    worktree: Path | None
    ahead: int | None
    behind: int | None
    lines: int | None
    committed_at: int | None
    age_days: float | None
    parked_reason: str | None
    plan: str | None
    issue: int | None
    merged_into: str | None = None
    #: The ref that proved a done state, e.g. ``origin/main`` or (unpushed) ``main``.
    proven_by: str | None = None
    #: Why the record is ``UNCLASSIFIED``.
    reason: str | None = None
    #: False when ``git worktree list`` failed: ``worktree`` is then unknown, not absent.
    worktree_known: bool = True
    same_tip_as: tuple[str, ...] = ()
    dormancy_stage: DormancyStage | None = None
    containment: Containment | None = None
    contained_in: str | None = None
    #: Past the pool's ``max_age_days`` (a parked branch) or an unkept merged branch.
    stale: bool = False
    #: Consecutive empty park commits at a parked tip; above 1 it was re-parked.
    park_count: int | None = None
    #: The keep note on a merged branch's tip (``branch-keep``), if any.
    kept_reason: str | None = None
    kept_by: str | None = None
    kept_at: int | None = None
    #: Author of a FOREIGN branch's tip.
    author: str | None = None
    author_email: str | None = None
    #: The done state a FOREIGN branch was proven in (any ``_DONE_RANK`` state:
    #: merged, merged-into-line, patch-equivalent, park-carried, or content-preserved
    #: when built with ``prove_content``), so ``--clean --remote`` can still delete
    #: it, gated by the live remote-delete proof: proof matters more than ownership.
    proof_state: BranchState | None = None

    @property
    def cleanup_state(self) -> BranchState:
        """The state ``--clean`` judges: a foreign branch's proof, else its own state."""
        return self.proof_state or self.state


@dataclass(frozen=True)
class BranchInventory:
    """The result of one pass.

    ``default_ref`` is None when the default could not be resolved to a ref;
    nothing is then merged into the default, and a consumer should report the
    configuration rather than act on the verdicts.
    """

    default_branch: str | None
    default_ref: str | None
    records: dict[str, BranchRecord]
    worktrees_known: bool = True
    #: The one ``ls-remote`` the caller asked for, or None when the pass stayed offline.
    remote_refs: RemoteRefs | None = None
    #: Strict ancestors among the open-work tips (:func:`branch_stacks.read_tip_ancestry`);
    #: None when unknown, which groups no stack (fail closed: over-count).
    tip_ancestry: Mapping[str, frozenset[str]] | None = None
    #: ``branches.wip.stack_max_depth`` the pass was built with.
    stack_max_depth: int = DEFAULT_STACK_MAX_DEPTH


@dataclass(frozen=True)
class _RefRow:
    refname: str
    sha: str
    committed_at: int
    upstream: str | None
    behind: int | None
    parked_reason: str | None
    subject: str
    author_name: str
    author_email: str


@dataclass(frozen=True)
class _BadRow:
    """A listing row whose fields could not be read; its name is still known."""

    refname: str
    reason: str


_Row = _RefRow | _BadRow


@dataclass(frozen=True)
class _PairFacts:
    """Step-5 facts for one ``(tip, target)`` pair, park commits excluded."""

    ahead: int
    unique: int
    merges: int
    lines: int | None
    #: Park commits in the range (they are not in ``ahead``).
    parks: int = 0


@dataclass
class _Cache:
    pairs: dict[str, dict[str, Any]] = field(default_factory=dict)
    containment: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Consecutive park commits by tip sha: a count depends only on the tip.
    park_counts: dict[str, int] = field(default_factory=dict)
    #: Offline proof-of-merge evidence by ``tip:target shas`` (Plan 00594 DESIGN.md 2.1).
    proofs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Target:
    name: str
    ref: str
    sha: str
    is_default: bool


@dataclass(frozen=True)
class _Verdict:
    """The proof for ONE tip of a name; ``LIVE`` stands for "not done"."""

    state: BranchState
    merged_into: str | None = None
    proven_ref: str | None = None
    ahead: int | None = None
    lines: int | None = None
    reason: str | None = None


# --- step 1: refs -------------------------------------------------------------


def _ref_format(default_ref: str | None) -> str:
    ahead_behind = f"%(ahead-behind:{default_ref})" if default_ref else ""
    fields = (
        "%(refname)",
        "%(objectname)",
        "%(committerdate:unix)",
        "%(upstream)",
        ahead_behind,
        f"%(trailers:key={_PARK_REASON_KEY},valueonly,unfold,separator=%x1f)",
        "%(contents:subject)",
        "%(authorname)",
        "%(authoremail)",
    )
    return "".join(f"{atom}%00" for atom in fields)


def _parse_row(refname: str, fields: list[str]) -> _Row:
    sha, date, upstream, ahead_behind, parked, subject, author_name, author_email = fields
    if not _OBJECT_NAME.fullmatch(sha):
        return _BadRow(refname, f"unparseable object name {sha!r} in the ref listing")
    if not date.isdigit():
        return _BadRow(refname, f"unparseable committer date {date!r} in the ref listing")
    behind: int | None = None
    if ahead_behind:
        counts = ahead_behind.split()
        behind = int(counts[1]) if len(counts) == 2 and counts[1].isdigit() else None
    return _RefRow(
        refname=refname,
        sha=sha,
        committed_at=int(date),
        upstream=upstream.removeprefix(_REMOTES) or None,
        behind=behind,
        parked_reason=parked.split(_UNIT)[0].strip() or None,
        subject=subject,
        author_name=author_name,
        author_email=author_email.strip().removeprefix("<").removesuffix(">"),
    )


def _parse_listing(stdout: str) -> list[_Row]:
    """Split the NUL-delimited listing into rows, refusing anything misaligned.

    Records are counted by fields, not split on newlines, so a newline inside a
    value cannot cut a record in two. A misaligned listing raises: past that
    point no field can be trusted to belong to the ref beside it.
    """
    if not stdout:
        return []
    tokens = stdout.split(_FIELD)
    if tokens.pop() != _RECORD_END or len(tokens) % _FIELD_COUNT:
        raise BranchInventoryError("git for-each-ref output does not align to whole records")
    rows: list[_Row] = []
    for start in range(0, len(tokens), _FIELD_COUNT):
        fields = tokens[start : start + _FIELD_COUNT]
        refname = fields[0]
        if start:
            if not refname.startswith(_RECORD_END):
                raise BranchInventoryError(f"git for-each-ref record {refname!r} is misaligned")
            refname = refname.removeprefix(_RECORD_END)
        if not refname.startswith(_REFS) or not refname.isprintable() or " " in refname:
            raise BranchInventoryError(f"git for-each-ref record has no ref name: {refname!r}")
        rows.append(_parse_row(refname, fields[1:]))
    return rows


def _list_refs(repo: Path, remote: str, default_ref: str | None) -> list[_Row]:
    roots = (_HEADS.rstrip("/"), f"{_REMOTES}{remote}")
    result = run_git(
        repo, "for-each-ref", f"--format={_ref_format(default_ref)}", *roots, timeout=_GIT_TIMEOUT
    )
    if result.returncode != 0 and default_ref is not None:
        # git before 2.41 has no %(ahead-behind:); behind is then unknown.
        logger.info("branch_inventory: for-each-ref with ahead-behind failed; retrying without")
        result = run_git(
            repo, "for-each-ref", f"--format={_ref_format(None)}", *roots, timeout=_GIT_TIMEOUT
        )
    if result.returncode != 0:
        raise BranchInventoryError(f"git for-each-ref failed: {result.stderr.strip()}")
    return _parse_listing(result.stdout)


def _refs_hash(rows: list[_Row]) -> str:
    """Digest of every ref that can contain a tip: the remote-tracking refs.

    Keys the containment cache, so a moved, added or deleted remote ref
    invalidates every cached containment verdict. Tags are not containment
    (see :func:`containment_of`), so they are not in the key either.
    """
    remote_refs = sorted(
        f"{r.refname} {r.sha}"
        for r in rows
        if isinstance(r, _RefRow) and r.refname.startswith(_REMOTES)
    )
    return hashlib.sha256("\n".join(remote_refs).encode()).hexdigest()


def _ref_exists(repo: Path, ref: str) -> bool:
    return (
        run_git(repo, "show-ref", "--verify", "--quiet", ref, timeout=_GIT_TIMEOUT).returncode == 0
    )


def _default_ref(repo: Path, remote: str, default: str | None) -> str | None:
    if default is None:
        return None
    for ref in (f"{_REMOTES}{remote}/{default}", f"{_HEADS}{default}"):
        if _ref_exists(repo, ref):
            return ref
    return None


# --- step 2: worktrees ----------------------------------------------------------


def _worktrees(repo: Path) -> dict[str, Path] | None:
    """Branch name to worktree path; None (unknown, never "none") when git fails."""
    result = run_git(repo, "worktree", "list", "--porcelain", timeout=branch_metadata_timeout())
    if result.returncode != 0:
        logger.info("branch_inventory: worktree list failed: %s", result.stderr.strip())
        return None
    found: dict[str, Path] = {}
    path: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree ")).resolve()
        elif line.startswith("branch ") and path is not None:
            found[line.removeprefix("branch ").removeprefix(_HEADS)] = path
    return found


# --- step 3: bulk ancestry ------------------------------------------------------


def _merged_refs(repo: Path, target_ref: str, remote: str) -> set[str]:
    """Refs whose tip is an ancestor of ``target_ref``; empty (proves nothing) on failure."""
    result = run_git(
        repo,
        "for-each-ref",
        f"--merged={target_ref}",
        "--format=%(refname)",
        _HEADS.rstrip("/"),
        f"{_REMOTES}{remote}",
        timeout=_GIT_TIMEOUT,
    )
    if result.returncode != 0:
        logger.info("branch_inventory: --merged=%s failed: %s", target_ref, result.stderr.strip())
        return set()
    return {line for line in result.stdout.splitlines() if line and line != target_ref}


# --- step 5: per-pair facts -------------------------------------------------------


def _shortstat_lines(repo: Path, *diff_args: str) -> int | None:
    result = run_git(repo, "diff", "--shortstat", *diff_args, timeout=_GIT_TIMEOUT)
    if result.returncode != 0:
        return None
    return sum(int(count) for count in _SHORTSTAT_COUNT.findall(result.stdout))


def _has_no_merge_base(repo: Path, target: str, tip: str) -> bool:
    """True only when git positively reports no common ancestor (exit 1, no output)."""
    result = run_git(repo, "merge-base", target, tip, timeout=_GIT_TIMEOUT)
    return result.returncode == 1 and not result.stdout.strip()


def _lines(repo: Path, target: str, tip: str) -> int | None:
    """Lines the tip adds beyond the merge base; None when git cannot say.

    With no merge base the three-dot diff errors. The tip then shares nothing
    with the target, so everything in it is its own work: the diff from the
    empty tree.
    """
    lines = _shortstat_lines(repo, f"{target}...{tip}")
    if lines is not None or not _has_no_merge_base(repo, target, tip):
        return lines
    return _empty_tree_lines(repo, tip)


def _empty_tree_lines(repo: Path, tip: str) -> int | None:
    """Lines in the whole tip: its diff from the empty tree; None when git cannot say."""
    empty = run_git(repo, "hash-object", "-t", "tree", os.devnull, timeout=_GIT_TIMEOUT)
    if empty.returncode != 0 or not empty.stdout.strip():
        return None
    return _shortstat_lines(repo, empty.stdout.strip(), tip)


def _is_shallow(repo: Path) -> bool:
    """True when git positively reports a shallow repository."""
    result = run_git(repo, "rev-parse", "--is-shallow-repository", timeout=_GIT_TIMEOUT)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _pair_facts(
    repo: Path, tip: str, target: str, *, want_lines: bool
) -> _PairFacts | HistoryNotFetched | None:
    """Ahead and unique patches (parks excluded), merges and lines.

    None on any git failure; :class:`HistoryNotFetched` when a shallow clone lacks the fork point.
    """
    walked = walk_park_range(repo, target, tip, timeout=_GIT_TIMEOUT)
    if walked is None:
        return None
    ahead = len(walked.commits) - len(walked.parks)
    if ahead == 0:
        return _PairFacts(
            ahead=0, unique=0, merges=0, lines=0 if want_lines else None, parks=len(walked.parks)
        )
    if _has_no_merge_base(repo, target, tip):
        # Nothing is shared with the target, so nothing in the tip can be a patch the
        # target already holds: git cherry would compare against the target's whole
        # history and could call a rewritten-history branch equivalent. All of it is work.
        if _is_shallow(repo):
            return HistoryNotFetched()
        lines = _empty_tree_lines(repo, tip) if want_lines else None
        if want_lines and lines is None:
            return None
        return _PairFacts(
            ahead=ahead, unique=ahead, merges=walked.merges, lines=lines, parks=len(walked.parks)
        )
    unique = branch_safety.cherry_unique_shas(repo, target, tip, timeout=_GIT_TIMEOUT)
    if unique is None:
        return None
    lines = _lines(repo, target, tip) if want_lines else None
    if want_lines and lines is None:
        return None
    return _PairFacts(
        ahead=ahead,
        unique=len(set(unique) - walked.parks),
        merges=walked.merges,
        lines=lines,
        parks=len(walked.parks),
    )


# --- never-work names ---------------------------------------------------------------


def _never_work(name: str, config: BranchesConfig, default: str | None) -> BranchState | None:
    """The non-work state of ``name``, or None when it is a work branch.

    Exempt, the default, an integration line or a protected name: never
    counted, never judged, and never "contained" work for another branch.
    """
    if branch_safety.matches_any_glob(name, config.exempt):
        return BranchState.EXEMPT
    if branch_safety.matches_any_glob(name, config.bot_owned):
        return BranchState.BOT_OWNED
    if name == default:
        return BranchState.DEFAULT
    if branch_safety.matches_any_glob(name, config.integration_lines):
        return BranchState.INTEGRATION_LINE
    if branch_safety.matches_any_glob(name, config.protected_names):
        return BranchState.PROTECTED
    return None


def is_work_branch(name: str, config: BranchesConfig, default: str | None) -> bool:
    """Whether ``name`` is a work branch: not exempt, default, integration or protected."""
    return _never_work(name, config, default) is None


def worktrees_by_branch(repo: Path) -> dict[str, Path] | None:
    """Branch name to worktree path; None when git cannot list worktrees."""
    return _worktrees(repo)


def _short(ref: str) -> str:
    """``refs/remotes/origin/x`` -> ``origin/x``, ``refs/heads/x`` -> ``x``, else drop ``refs/``."""
    for prefix in (_REMOTES, _HEADS):
        if ref.startswith(prefix):
            return ref.removeprefix(prefix)
    return ref.removeprefix(_REFS)


# --- containment ------------------------------------------------------------------


def containment_of(
    repo: Path, *, name: str, tip: str, config: BranchesConfig, default: str | None
) -> tuple[Containment, str | None] | None:
    """Where ``tip`` lives among ``config.remote``'s tracking refs (DESIGN.md section 4).

    None when git fails. Only remote-tracking refs count: a local tag may never
    have been pushed, and counting one would report a branch no remote holds
    as contained, silencing its CONTAINED NOWHERE warning. Telling a pushed
    tag from a local one needs ``ls-remote``, a network call the inventory
    never makes. The cherry arm of "in the default branch" is not repeated
    here: a branch whose patches are all in the default is classified
    patch-equivalent first.
    """
    remote = config.remote
    if default is not None:
        default_ref = f"{_REMOTES}{remote}/{default}"
        ancestor = run_git(
            repo, "merge-base", "--is-ancestor", tip, default_ref, timeout=_GIT_TIMEOUT
        )
        if ancestor.returncode == 0:
            return Containment.DEFAULT, _short(default_ref)
    result = run_git(
        repo,
        "for-each-ref",
        f"--contains={tip}",
        "--format=%(refname)",
        f"{_REMOTES}{remote}",
        timeout=_GIT_TIMEOUT,
    )
    if result.returncode != 0:
        return None
    remote_prefix = f"{_REMOTES}{remote}/"
    own = f"{remote_prefix}{name}"
    head = f"{remote_prefix}{_REMOTE_HEAD}"
    others = sorted(ref for ref in result.stdout.splitlines() if ref and ref not in {head, own})
    # A bot's branch is nobody's integration target, so it never vouches.
    vouching = [
        ref
        for ref in others
        if _never_work(ref.removeprefix(remote_prefix), config, default)
        not in (None, BranchState.BOT_OWNED)
    ]
    if vouching:
        return Containment.REMOTE_REF, _short(vouching[0])
    if own in result.stdout.splitlines():
        return Containment.OWN_REMOTE, _short(own)
    if others:
        return Containment.OTHER_WORK_BRANCH, _short(others[0])
    return Containment.NOWHERE, None


# --- cache --------------------------------------------------------------------------


def _load_cache(path: Path) -> _Cache:
    if not path.is_file():
        return _Cache()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason="an unreadable inventory cache is rebuilt from git; it only saves time",
            level=logging.WARNING,
        )
        return _Cache()
    if not isinstance(data, dict) or data.get("version") != _CACHE_VERSION:
        return _Cache()
    pairs = data.get("pairs")
    containment = data.get("containment")
    park_counts = data.get("park_counts")
    proofs = data.get("proofs")
    return _Cache(
        proofs={
            key: tier
            for key, tier in (proofs if isinstance(proofs, dict) else {}).items()
            if isinstance(key, str) and isinstance(tier, str)
        },
        pairs=pairs if isinstance(pairs, dict) else {},
        containment=containment if isinstance(containment, dict) else {},
        park_counts={
            tip: count
            for tip, count in (park_counts if isinstance(park_counts, dict) else {}).items()
            if isinstance(count, int)
        },
    )


def _save_cache(path: Path, cache: _Cache, live_tips: set[str]) -> None:
    """Write the cache, keeping only entries whose tip still exists."""
    document = {
        "version": _CACHE_VERSION,
        "pairs": {k: v for k, v in cache.pairs.items() if k.split(":", 1)[0] in live_tips},
        "containment": {
            k: v for k, v in cache.containment.items() if k.split(":", 1)[0] in live_tips
        },
        "park_counts": {k: v for k, v in cache.park_counts.items() if k in live_tips},
        "proofs": {k: v for k, v in cache.proofs.items() if _proof_tip(k) in live_tips},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch = path.with_suffix(".tmp")
        scratch.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        scratch.replace(path)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="an unwritable inventory cache costs the next pass time, not correctness",
            level=logging.WARNING,
        )


#: Bump when the rule that decides a cached proof changes, so entries the old rule
#: wrote are never read. v3: some first-parent commit of the default, after the merge
#: base and up to its tip, holds the branch's net change. v4: a tip whose every commit
#: beyond the default is empty (one parent, its tree) is proven (Plan 00622). v5: that
#: emptiness is read from the stored commit objects only, never through a replace ref,
#: a graft or a commit-graph, so a v4 entry may record a forged object's answer. v6:
#: patch equivalence with every changed path held at its exact blob by some commit
#: proves (a v5 ``unproven`` would keep refusing it), and the only target is the
#: remote-tracking default (Plan 00626).
PROOF_ALGORITHM_VERSION: Final[str] = "v6"


def merge_proof_key(tip: str, target_shas: Iterable[str]) -> str:
    """The cache key of a tip's merge evidence against the default refs at these shas.

    Keyed by algorithm version, tip AND target, so a changed rule or a moved default
    invalidates it and a moved branch never reads another tip's answer.
    """
    return f"{PROOF_ALGORITHM_VERSION}:{tip}:{','.join(sorted(set(target_shas)))}"


def _proof_tip(key: str) -> str:
    """The tip a proof key names; "" for a key an older algorithm wrote (so it is pruned)."""
    version, _, rest = key.partition(":")
    return rest.split(":", 1)[0] if version == PROOF_ALGORITHM_VERSION else ""


def read_merge_proofs(repo: Path) -> dict[str, str]:
    """The cached merge evidence (``merge_proof_key`` to tier or ``unproven``); offline."""
    return dict(_load_cache(repo / CACHE_RELATIVE_PATH).proofs)


def write_merge_proofs(repo: Path, proofs: Mapping[str, str]) -> None:
    """Add ``proofs`` to the inventory cache, keeping every other entry it holds."""
    path = repo / CACHE_RELATIVE_PATH
    cache = _load_cache(path)
    cache.proofs.update(proofs)
    keys = [*cache.pairs, *cache.containment, *cache.park_counts]
    current = {key: tier for key, tier in cache.proofs.items() if _proof_tip(key)}
    cache.proofs = current
    live = {key.split(":", 1)[0] for key in keys} | {_proof_tip(key) for key in current}
    _save_cache(path, cache, live)


def _facts_from_cache(entry: dict[str, Any] | None) -> _PairFacts | None:
    if not isinstance(entry, dict):
        return None
    ahead, unique, merges = entry.get("ahead"), entry.get("unique"), entry.get("merges")
    lines = entry.get("lines")
    if not (isinstance(ahead, int) and isinstance(unique, int) and isinstance(merges, int)):
        return None
    if lines is not None and not isinstance(lines, int):
        return None
    parks = entry.get("parks")
    if not isinstance(parks, int):
        return None
    return _PairFacts(ahead=ahead, unique=unique, merges=merges, lines=lines, parks=parks)


# --- links ----------------------------------------------------------------------------


def issue_number_in_name(name: str) -> int | None:
    """The issue number a branch or agent name carries (``worktree-issue-203-x`` -> 203), if any."""
    match = _ISSUE_IN_NAME.search(name)
    return int(match.group(1)) if match else None


def _links(name: str, subject: str) -> tuple[str | None, int | None]:
    """Plan and issue from the branch name first, then from the tip subject."""
    issue: int | None = None
    remainder = name
    issue_match = _ISSUE_IN_NAME.search(name)
    if issue_match:
        issue = int(issue_match.group(1))
        remainder = name[: issue_match.start()] + name[issue_match.end() :]
    plan = next(
        (
            token.zfill(_PLAN_WIDTH)
            for token in _NAME_TOKEN_SPLIT.split(remainder)
            if _PLAN_TOKEN.fullmatch(token)
        ),
        None,
    )
    if issue is None:
        subject_issue = _ISSUE_IN_SUBJECT.search(subject)
        issue = int(subject_issue.group(1)) if subject_issue else None
    if plan is None:
        subject_plan = _PLAN_IN_SUBJECT.search(subject)
        plan = subject_plan.group(1).zfill(_PLAN_WIDTH) if subject_plan else None
    return plan, issue


# --- the pass -----------------------------------------------------------------------


def _stage(age_days: float, config: BranchesConfig) -> DormancyStage | None:
    if config.dormancy.mode == "off":
        return None
    advisory, noisy, block = config.dormancy.effective_days
    if age_days >= block and config.dormancy.mode == "block":
        return DormancyStage.BLOCK
    if age_days >= noisy:
        return DormancyStage.NOISY
    if age_days >= advisory:
        return DormancyStage.ADVISORY
    return None


class _Pass:
    """State for one inventory pass: the budget, the cache and the shared facts."""

    def __init__(
        self,
        repo: Path,
        config: BranchesConfig,
        cache: _Cache,
        remote_refs: RemoteSource | None = None,
        prove_content: bool = False,
    ) -> None:
        self.repo = repo
        self.config = config
        self.cache = cache
        self.remote_refs = remote_refs
        self.prove_content = prove_content
        self.deadline = time.monotonic() + config.sweep.budget_ms / 1000
        #: Why a (tip, target sha) pair went unmeasured this pass: the budget, or a git failure.
        self.unmeasured: dict[tuple[str, str], str] = {}
        self._park_records: dict[str, ParkRecord] | None = None

    def park_records(self) -> dict[str, ParkRecord]:
        """Every readable park record, read once per pass (one git process)."""
        if self._park_records is None:
            self._park_records = read_park_records(self.repo)
        return self._park_records

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Whether ``ancestor`` is in ``descendant``'s history; False when git cannot say."""
        result = run_git(
            self.repo, "merge-base", "--is-ancestor", ancestor, descendant, timeout=_GIT_TIMEOUT
        )
        return result.returncode == 0

    def within_budget(self) -> bool:
        """Whether the sweep's time budget (``sweep.budget_ms``) has not yet run out."""
        return time.monotonic() < self.deadline

    def park_count(self, tip: str) -> int | None:
        """Consecutive park commits at ``tip``: cached by tip, None when unknown.

        Unknown means the budget ran out before the count was measured, or git failed.
        """
        cached = self.cache.park_counts.get(tip)
        if cached is not None:
            return cached
        if not self.within_budget():
            return None
        count = _park_count(self.repo, tip)
        if count is not None:
            self.cache.park_counts[tip] = count
        return count

    def facts(self, tip: str, target: _Target) -> _PairFacts | None:
        want_lines = target.is_default
        key = f"{tip}:{target.sha}:{'lines' if want_lines else 'nolines'}"
        cached = _facts_from_cache(self.cache.pairs.get(key))
        if cached is not None:
            return cached
        if not self.within_budget():
            self.unmeasured[(tip, target.sha)] = BUDGET_REASON
            return None
        computed = _pair_facts(self.repo, tip, target.sha, want_lines=want_lines)
        if isinstance(computed, HistoryNotFetched):
            self.unmeasured[(tip, target.sha)] = _SHALLOW_REASON.format(target=target.name)
            return None
        if computed is None:
            self.unmeasured[(tip, target.sha)] = _GIT_FAILED_REASON.format(target=target.name)
        else:
            self.cache.pairs[key] = {
                "ahead": computed.ahead,
                "unique": computed.unique,
                "merges": computed.merges,
                "lines": computed.lines,
                "parks": computed.parks,
            }
        return computed

    def containment(
        self, name: str, tip: str, default: str | None, refs_hash: str
    ) -> tuple[Containment, str | None] | None:
        """The offline answer, upgraded by the remote listing when one was passed.

        The cache holds only the offline answer: a listing is a point-in-time
        network reading and must not outlive its command.
        """
        found = self._offline_containment(name, tip, default, refs_hash)
        if found is None or found[0] != Containment.NOWHERE or self.remote_refs is None:
            return found
        listing = resolve_source(self.remote_refs)
        held = holder_of(self.repo, listing, tip)
        if held is None:
            return found
        return Containment.REMOTE_UNFETCHED, f"{listing.remote}: {held}"

    def _offline_containment(
        self, name: str, tip: str, default: str | None, refs_hash: str
    ) -> tuple[Containment, str | None] | None:
        key = f"{tip}:{refs_hash}:{name}"
        entry = self.cache.containment.get(key)
        if isinstance(entry, dict) and entry.get("containment") in {c.value for c in Containment}:
            ref = entry.get("ref")
            return Containment(entry["containment"]), ref if isinstance(ref, str) else None
        if not self.within_budget():
            return None
        found = containment_of(self.repo, name=name, tip=tip, config=self.config, default=default)
        if found is not None:
            self.cache.containment[key] = {"containment": found[0].value, "ref": found[1]}
        return found


@dataclass(frozen=True)
class _Context:
    """Facts shared by every record of one pass."""

    default: str | None
    targets: list[_Target]
    #: ``(ref, refs merged into it)`` for the remote default ref, then the local one.
    merged_default: list[tuple[str, set[str]]]
    merged_lines: list[tuple[_Target, set[str]]]
    worktrees: dict[str, Path] | None
    refs_hash: str
    moment: float
    owners: OwnerRule


class OwnerRule:
    """DESIGN.md section 2.2, read once per pass and only when a branch needs it.

    A branch with a local ref is mine without a git call; only a remote-only
    branch needs the creator records and ``user.email``.
    """

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self._creators: set[str] | None = None
        self._email: str | None = None
        self._email_read = False

    def creators(self) -> set[str]:
        """Names carrying a ``hooksDaemonCreator`` record in this clone."""
        if self._creators is None:
            result = run_git(
                self._repo,
                "config",
                "--get-regexp",
                rf"^branch\..+\.{CREATOR_KEY}$",
                timeout=_GIT_TIMEOUT,
            )
            names: set[str] = set()
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    key = line.split(" ", 1)[0].removeprefix("branch.")
                    names.add(key.rsplit(".", 1)[0])
            self._creators = names
        return self._creators

    def email(self) -> str | None:
        """This clone's ``user.email`` (lower case), or None when unset."""
        if not self._email_read:
            result = run_git(self._repo, "config", "user.email", timeout=_GIT_TIMEOUT)
            value = result.stdout.strip().lower()
            self._email = value if result.returncode == 0 and value else None
            self._email_read = True
        return self._email

    def is_mine(self, name: str, *, has_local: bool, author_email: str | None) -> bool:
        """The owner rule, in order: creator record, local ref, author email.

        ``author_email`` is the remote tip's author, or None when unknown.
        """
        if has_local or name in self.creators():
            return True
        mine = self.email()
        return mine is not None and author_email is not None and author_email.lower() == mine


def _group_rows(rows: list[_Row], remote: str) -> dict[str, tuple[_Row | None, _Row | None]]:
    remote_prefix = f"{_REMOTES}{remote}/"
    grouped: dict[str, list[_Row | None]] = {}
    for row in rows:
        if row.refname.startswith(_HEADS):
            grouped.setdefault(row.refname.removeprefix(_HEADS), [None, None])[0] = row
        elif row.refname.startswith(remote_prefix):
            name = row.refname.removeprefix(remote_prefix)
            if name != _REMOTE_HEAD:
                grouped.setdefault(name, [None, None])[1] = row
    return {name: (pair[0], pair[1]) for name, pair in grouped.items()}


def build_inventory(
    repo: Path,
    config: BranchesConfig,
    *,
    now: float | None = None,
    remote_refs: RemoteSource | None = None,
    prove_content: bool = False,
) -> BranchInventory:
    """Classify every local and remote branch of ``repo`` (DESIGN.md section 2).

    ``prove_content`` lets a branch that is neither merged nor patch-equivalent be
    ``CONTENT_PRESERVED`` when the remote-tracking default holds its net change
    (:func:`_content_preserved`). Only ``branch-sweep --clean`` asks: the proof costs
    tree reads per branch, and a hook's inventory must keep counting such a branch
    as open work.

    ``remote_refs`` is the one ``ls-remote`` an explicit command (``branch-sweep``)
    made; a branch otherwise CONTAINED NOWHERE whose tip a listed ref holds is
    ``REMOTE_UNFETCHED``. The inventory itself never touches the network, so a hook
    path that leaves it None stays offline.

    Raises:
        BranchInventoryError: The refs could not be listed (not a repository,
            git failed or timed out on a bulk listing, or the listing did not
            parse into whole records).
    """
    moment = time.time() if now is None else now
    remote = config.remote
    default = git_sync.resolve_default_branch(config, repo)
    default_ref = _default_ref(repo, remote, default)
    rows = _list_refs(repo, remote, default_ref)
    by_name = _group_rows(rows, remote)
    sha_of = {row.refname: row.sha for row in rows if isinstance(row, _RefRow)}
    refs_hash = _refs_hash(rows)

    targets: list[_Target] = []
    if default is not None and default_ref is not None and default_ref in sha_of:
        targets.append(_Target(default, default_ref, sha_of[default_ref], is_default=True))
    for name in sorted(by_name):
        if name != default and branch_safety.matches_any_glob(name, config.integration_lines):
            local, remote_row = by_name[name]
            row = remote_row or local
            if isinstance(row, _RefRow):
                targets.append(_Target(name, row.refname, row.sha, is_default=False))

    merged_default: list[tuple[str, set[str]]] = []
    if default is not None:
        for ref in (f"{_REMOTES}{remote}/{default}", f"{_HEADS}{default}"):
            if ref in sha_of:
                merged_default.append((ref, _merged_refs(repo, ref, remote)))
    context = _Context(
        default=default,
        targets=targets,
        merged_default=merged_default,
        merged_lines=[(t, _merged_refs(repo, t.ref, remote)) for t in targets if not t.is_default],
        worktrees=_worktrees(repo),
        refs_hash=refs_hash,
        moment=moment,
        owners=OwnerRule(repo),
    )
    cache_path = repo / CACHE_RELATIVE_PATH
    run = _Pass(repo, config, _load_cache(cache_path), remote_refs, prove_content)

    records = {name: _record(run, context, name, *by_name[name]) for name in sorted(by_name)}
    records = _with_pools(run, _with_same_tips(records), moment)
    _save_cache(cache_path, run.cache, set(sha_of.values()))
    open_tips = frozenset(
        tip
        for record in records.values()
        if pool_of(record.state) == Pool.OPEN
        for tip in (record.local_tip, record.remote_tip)
        if tip is not None
    )
    return BranchInventory(
        default_branch=default,
        default_ref=default_ref,
        records=records,
        worktrees_known=context.worktrees is not None,
        remote_refs=made_listing(remote_refs),
        tip_ancestry=read_tip_ancestry(repo, open_tips, [ref for ref, _ in merged_default]),
        stack_max_depth=config.wip.stack_max_depth,
    )


def _row_facts(row: _RefRow | None, moment: float) -> dict[str, Any]:
    """The per-copy fields of a record, all unknown without a parsed row."""
    if row is None:
        return {"behind": None, "committed_at": None, "age_days": None, "parked_reason": None}
    return {
        "behind": row.behind,
        "committed_at": row.committed_at,
        "age_days": (moment - row.committed_at) / _SECONDS_PER_DAY,
        "parked_reason": row.parked_reason,
    }


def _record(
    run: _Pass, context: _Context, name: str, local: _Row | None, remote_row: _Row | None
) -> BranchRecord:
    """Classify one name, then take it out of every pool when it is not mine (section 2.2)."""
    record = _classify(run, context, name, local, remote_row)
    if (
        record.state in _UNGROUPED
        or not isinstance(remote_row, _RefRow)
        or context.owners.is_mine(
            name, has_local=local is not None, author_email=remote_row.author_email
        )
    ):
        return record
    done = record.state if record.state in _DONE_RANK else None
    return replace(
        record,
        state=BranchState.FOREIGN,
        author=remote_row.author_name or None,
        author_email=remote_row.author_email or None,
        proof_state=done,
        dormancy_stage=None,
        containment=None,
        contained_in=None,
    )


def _classify(
    run: _Pass, context: _Context, name: str, local: _Row | None, remote_row: _Row | None
) -> BranchRecord:
    """Classify one name over every copy it has (DESIGN.md section 2)."""
    copies = [row for row in (local, remote_row) if row is not None]
    parsed = [row for row in copies if isinstance(row, _RefRow)]
    display = parsed[0] if parsed else None
    plan, issue = _links(name, display.subject if display else "")
    fixed: dict[str, Any] = {
        "name": name,
        "local_tip": local.sha if isinstance(local, _RefRow) else None,
        "remote_tip": remote_row.sha if isinstance(remote_row, _RefRow) else None,
        "upstream": local.upstream if isinstance(local, _RefRow) else None,
        "worktree": context.worktrees.get(name) if context.worktrees is not None else None,
        "worktree_known": context.worktrees is not None,
        "plan": plan,
        "issue": issue,
    }
    unmeasured: dict[str, Any] = {"ahead": None, "lines": None}

    never = _never_work(name, run.config, context.default)
    if never is not None:
        return BranchRecord(
            state=never, **fixed, **_row_facts(display, context.moment), **unmeasured
        )
    bad = next((row for row in copies if isinstance(row, _BadRow)), None)
    if bad is not None:
        return BranchRecord(
            state=BranchState.UNCLASSIFIED,
            reason=f"{bad.refname}: {bad.reason}",
            **fixed,
            **_row_facts(None, context.moment),
            **unmeasured,
        )

    distinct: list[_RefRow] = []
    for row in parsed:
        if all(row.sha != seen.sha for seen in distinct):
            distinct.append(row)
    judged = [(row, _tip_verdict(run, context, row)) for row in distinct]
    unmeasurable = next(
        ((row, v) for row, v in judged if v.state == BranchState.UNCLASSIFIED), None
    )
    if unmeasurable is not None:
        row, verdict = unmeasurable
        return BranchRecord(
            state=BranchState.UNCLASSIFIED,
            reason=verdict.reason,
            **fixed,
            **_row_facts(row, context.moment),
            **unmeasured,
        )
    undone = [(row, v) for row, v in judged if v.state not in _DONE_RANK]
    if not undone:
        done = _weakest([v for _row, v in judged])
        return BranchRecord(
            state=done.state,
            merged_into=done.merged_into,
            proven_by=_short(done.proven_ref) if done.proven_ref else None,
            ahead=done.ahead,
            lines=done.lines,
            **fixed,
            **_row_facts(display, context.moment),
        )

    row, verdict = undone[0]
    facts = _row_facts(row, context.moment)
    own: dict[str, Any] = {"ahead": verdict.ahead, "lines": verdict.lines}
    if row.parked_reason is None and isinstance(local, _RefRow) and local.sha == row.sha:
        # A park with no trailer commit lives only in the record; its age is the record's.
        standing = run.park_records().get(name)
        if standing is not None and park_covers_tip(
            standing,
            row.sha,
            max_age_days=run.config.effective_pool_max_age(Pool.PARKED),
            is_ancestor=run.is_ancestor,
        ):
            facts["parked_reason"] = standing.reason
            facts["age_days"] = (context.moment - standing.parked_at) / _SECONDS_PER_DAY
            return BranchRecord(state=BranchState.PARKED, **fixed, **facts, **own)
    if row.parked_reason is not None:
        return BranchRecord(state=BranchState.PARKED, **fixed, **facts, **own)
    stage = _stage(facts["age_days"], run.config)
    if stage is None:
        return BranchRecord(state=BranchState.LIVE, **fixed, **facts, **own)
    found_in = run.containment(name, row.sha, context.default, context.refs_hash)
    return BranchRecord(
        state=BranchState.DORMANT,
        dormancy_stage=stage,
        containment=found_in[0] if found_in else None,
        contained_in=found_in[1] if found_in else None,
        **fixed,
        **facts,
        **own,
    )


def _tip_verdict(run: _Pass, context: _Context, row: _RefRow) -> _Verdict:
    """States 3-5 for ONE tip; ``LIVE`` when it is none of them."""
    for ref, merged in context.merged_default:
        if row.refname in merged:
            return _Verdict(
                BranchState.MERGED_DEFAULT, context.default, proven_ref=ref, ahead=0, lines=0
            )
    for line, merged in context.merged_lines:
        if row.refname in merged:
            return _Verdict(BranchState.MERGED_LINE, line.name, proven_ref=line.ref)

    facts: list[tuple[_Target, _PairFacts]] = []
    for target in context.targets:
        found = run.facts(row.sha, target)
        if found is None:
            return _Verdict(
                BranchState.UNCLASSIFIED,
                reason=run.unmeasured[(row.sha, target.sha)],
            )
        facts.append((target, found))
        if target.is_default and found.ahead == 0:
            break
    ahead: int | None = None
    lines: int | None = None
    for target, found in facts:
        if target.is_default:
            ahead, lines = found.ahead, found.lines
    # Section 2 order: merged into the default, then into a line, then patch-equivalent.
    contained_by = next((t for t, f in facts if f.ahead == 0), None)
    if contained_by is not None:
        state = BranchState.MERGED_DEFAULT if contained_by.is_default else BranchState.MERGED_LINE
        carried = next((f for t, f in facts if t is contained_by), None)
        if contained_by.is_default and carried is not None and carried.parks:
            # Not an ancestor, yet nothing but park markers is ahead: the work is in the default.
            state = BranchState.PARK_CARRIED
        return _Verdict(state, contained_by.name, contained_by.ref, ahead, lines)
    # A merge commit can carry content no patch-id shows, so it is never equivalent.
    equivalent = next((t for t, f in facts if f.unique == 0 and f.merges == 0), None)
    if equivalent is not None:
        return _Verdict(BranchState.PATCH_EQUIVALENT, equivalent.name, equivalent.ref, ahead, lines)
    held_by = _content_preserved(run, context, row)
    if held_by is not None:
        return _Verdict(BranchState.CONTENT_PRESERVED, context.default, held_by, ahead, lines)
    return _Verdict(BranchState.LIVE, ahead=ahead, lines=lines)


def _content_preserved(run: _Pass, context: _Context, row: _RefRow) -> str | None:
    """The remote-tracking default ref when it holds ``row``'s whole net change, else None.

    The proof is ``remote_branch_proof.holds_net_change`` (bounded by its path and
    candidate caps), against the REMOTE-tracking default only, never a local ref whose
    commits may be unpushed. Asked only when the pass was built with
    ``prove_content``. A spent budget or a git failure is None (the branch stays
    LIVE), and nothing is cached: a deleting caller re-proves every branch itself.
    """
    tracking = f"{_REMOTES}{run.config.remote}/{context.default}"
    if (
        not run.prove_content
        or context.default is None
        or all(ref != tracking for ref, _merged in context.merged_default)
        or not run.within_budget()
    ):
        return None
    # Imported here: remote_branch_proof imports this module.
    from claude_code_hooks_daemon.core import remote_branch_proof

    # The proof reads ROOT-relative paths: from a project below the top level a
    # lookup would miss, and a deleted path would read as absent, i.e. held.
    top = run_git(run.repo, "rev-parse", "--show-toplevel", timeout=_GIT_TIMEOUT)
    top_level = top.stdout.strip() if top.returncode == 0 else ""
    if not top_level:
        return None
    held = False
    try:
        held = remote_branch_proof.holds_net_change(
            Path(top_level),
            tracking,
            row.sha,
            timeout=scaled_timeout(Timeout.GIT_BRANCH_SAFETY, Timeout.GIT_BRANCH_SAFETY_MAX),
        )
    except remote_branch_proof.ProofUnavailableError as exc:
        log_and_continue(logger, exc, reason="an unanswered proof leaves the branch LIVE")
    return tracking if held else None


def _weakest(verdicts: list[_Verdict]) -> _Verdict:
    """The weakest done proof among a name's copies; a local-only ref is weaker than a remote one."""
    return max(
        verdicts,
        key=lambda v: (
            _DONE_RANK[v.state],
            v.proven_ref is not None and v.proven_ref.startswith(_HEADS),
        ),
    )


_UNGROUPED = {
    BranchState.EXEMPT,
    BranchState.BOT_OWNED,
    BranchState.FOREIGN,
    BranchState.DEFAULT,
    BranchState.INTEGRATION_LINE,
    BranchState.PROTECTED,
}


_PARK_LOG_DEPTH = 64
_RECORD_SEP = "\x1e"


def _park_count(repo: Path, tip: str) -> int | None:
    """Consecutive park commits (empty, ``Parked-Reason``) at ``tip``; None if git failed."""
    result = run_git(
        repo,
        "log",
        "--first-parent",
        "-n",
        str(_PARK_LOG_DEPTH),
        f"--format=%T{_UNIT}%(trailers:key={_PARK_REASON_KEY},valueonly,unfold){_RECORD_SEP}",
        tip,
        timeout=_GIT_TIMEOUT,
    )
    if result.returncode != 0:
        return None
    entries = [entry.lstrip("\n").split(_UNIT, 1) for entry in result.stdout.split(_RECORD_SEP)]
    entries = [entry for entry in entries if len(entry) == 2]
    count = 0
    for index, (tree, trailer) in enumerate(entries[:-1]):
        if not trailer.strip() or tree != entries[index + 1][0]:
            break
        count += 1
    return count


def _with_merged_pool(
    run: _Pass, records: dict[str, BranchRecord], moment: float
) -> dict[str, BranchRecord]:
    """Fill the keep fields and ``stale`` of every merged branch (one notes read per ref).

    The keep notes are not cached (``branch-keep`` writes them from other processes),
    so with the budget spent they are not read: the branches stay unclassified, never
    stale, as they are when the worktrees are unknown.
    """
    config = run.config
    merged = {name: r for name, r in records.items() if pool_of(r.state) == Pool.MERGED}
    if not merged or not run.within_budget():
        return dict(records)
    tips = {t for r in merged.values() for t in (r.local_tip, r.remote_tip) if t is not None}
    keeps = read_keeps(run.repo, tips, config.remote)
    max_age = config.effective_pool_max_age(Pool.MERGED)
    updated = dict(records)
    for name, record in merged.items():
        held = [keeps[t] for t in (record.local_tip, record.remote_tip) if t in keeps]
        keep = max(held, key=lambda candidate: candidate.at, default=None)
        if keep is not None:
            lapsed = (moment - keep.at) / _SECONDS_PER_DAY >= max_age
        else:
            lapsed = record.worktree is None and record.worktree_known
        updated[name] = replace(
            record,
            stale=config.merged.mode != "off" and lapsed,
            kept_reason=keep.reason if keep else None,
            kept_by=keep.by if keep else None,
            kept_at=keep.at if keep else None,
        )
    return updated


def _with_pools(
    run: _Pass, records: dict[str, BranchRecord], moment: float
) -> dict[str, BranchRecord]:
    """Fill ``stale``, ``park_count`` and the keep fields (Plan 00571 DESIGN.md section 3).

    The tip of a parked branch IS the park commit, so its age is the park's age.
    A merged branch is stale unless it is kept inside ``merged.max_age_days`` or a
    worktree holds it; with the worktrees unknown it is not called stale.
    """
    parked = run.config.parked
    max_age = run.config.effective_pool_max_age(Pool.PARKED)
    updated = _with_merged_pool(run, records, moment)
    for name, record in records.items():
        if record.state != BranchState.PARKED:
            continue
        tip = record.local_tip or record.remote_tip
        stale = parked.mode != "off" and record.age_days is not None and record.age_days >= max_age
        updated[name] = replace(
            record,
            stale=stale,
            park_count=run.park_count(tip) if tip is not None else None,
        )
    return updated


def _with_same_tips(records: dict[str, BranchRecord]) -> dict[str, BranchRecord]:
    """Fill ``same_tip_as`` among work branches (DESIGN.md section 2, step 4)."""
    by_tip: dict[str, list[str]] = {}
    for name, record in records.items():
        tip = record.local_tip or record.remote_tip
        if tip is not None and record.state not in _UNGROUPED:
            by_tip.setdefault(tip, []).append(name)
    updated = dict(records)
    for names in by_tip.values():
        if len(names) < 2:
            continue
        for name in names:
            others = tuple(sorted(other for other in names if other != name))
            updated[name] = replace(records[name], same_tip_as=others)
    return updated
