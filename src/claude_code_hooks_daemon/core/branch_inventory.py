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
import re
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.utils import git_sync
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import run_git
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
#: Containment never counts tags; a version-2 entry may hold a tag's vouch.
_CACHE_VERSION = 3

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
_FIELD_COUNT = 7
_UNIT = "\x1f"
_GIT_TIMEOUT = Timeout.GIT_CONTEXT
_BOUNDARY_MARK = "-"
_OBJECT_NAME = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

#: Trailers that mark a park (or unpark) commit.
_PARK_TRAILER_KEYS = ("Parked-Reason", "Parked-By", "Unparked")
_PARK_REASON_KEY = "Parked-Reason"

_ISSUE_IN_NAME = re.compile(r"(?:^|[-_/])(?:issue|gh)-(\d+)(?=$|[-_/])", re.IGNORECASE)
_NAME_TOKEN_SPLIT = re.compile(r"[-_/.]")
_PLAN_TOKEN = re.compile(r"\d{2,5}")
_ISSUE_IN_SUBJECT = re.compile(r"Addresses #(\d+)")
_PLAN_IN_SUBJECT = re.compile(r"\bPlan (\d{2,5})\b")
_PLAN_WIDTH = 5
_SHORTSTAT_COUNT = re.compile(r"(\d+) (?:insertion|deletion)")

_UNMEASURED_REASON = (
    "the sweep budget ran out, or git failed, before this tip was measured against every target"
)


def _lines_of(output: str) -> list[str]:
    """Non-empty newline-separated lines.

    Not ``str.splitlines``: it also breaks on ``\\x1c``-``\\x1e``, and ``\\x1d``
    separates trailer values in the log format below.
    """
    return [line for line in output.split("\n") if line]


class BranchInventoryError(RuntimeError):
    """The refs could not be listed at all, so there is no inventory to return."""


class BranchState(StrEnum):
    """DESIGN.md section 2 states; the first that matches wins."""

    EXEMPT = "exempt"
    DEFAULT = "default"
    INTEGRATION_LINE = "integration-line"
    PROTECTED = "protected"
    MERGED_DEFAULT = "merged"
    MERGED_LINE = "merged-into-line"
    PATCH_EQUIVALENT = "patch-equivalent"
    PARKED = "parked"
    DORMANT = "dormant"
    LIVE = "live"
    UNCLASSIFIED = "not yet classified"


#: "Done, not deleted" (DESIGN.md section 2, states 3-5), strongest proof first.
_DONE_RANK = {
    BranchState.MERGED_DEFAULT: 0,
    BranchState.MERGED_LINE: 1,
    BranchState.PATCH_EQUIVALENT: 2,
}


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


@dataclass(frozen=True)
class _RefRow:
    refname: str
    sha: str
    committed_at: int
    upstream: str | None
    behind: int | None
    parked_reason: str | None
    subject: str


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


@dataclass
class _Cache:
    pairs: dict[str, dict[str, Any]] = field(default_factory=dict)
    containment: dict[str, dict[str, Any]] = field(default_factory=dict)


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
    )
    return "".join(f"{atom}%00" for atom in fields)


def _parse_row(refname: str, fields: list[str]) -> _Row:
    sha, date, upstream, ahead_behind, parked, subject = fields
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
    result = run_git(repo, "worktree", "list", "--porcelain", timeout=_GIT_TIMEOUT)
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


@dataclass(frozen=True)
class _Walk:
    commits: list[str]
    parks: set[str]
    merges: int


def _park_shas(log_output: str) -> _Walk | None:
    """Range commits, the park commits and the merge count, from a ``--boundary`` log."""
    trees: dict[str, str] = {}
    in_range: list[tuple[str, str, list[str], str]] = []
    for line in _lines_of(log_output):
        parts = line.split(_UNIT)
        if len(parts) != 5:
            return None
        mark, sha, tree, parents, trailers = parts
        trees[sha] = tree
        if mark != _BOUNDARY_MARK:
            in_range.append((sha, tree, parents.split(), trailers))
    parks = {
        sha
        for sha, tree, parents, trailers in in_range
        if trailers.strip() and len(parents) == 1 and trees.get(parents[0]) == tree
    }
    return _Walk(
        commits=[sha for sha, _tree, _parents, _trailers in in_range],
        parks=parks,
        merges=sum(1 for _sha, _tree, parents, _trailers in in_range if len(parents) > 1),
    )


def _lines(repo: Path, target: str, tip: str) -> int | None:
    result = run_git(repo, "diff", "--shortstat", f"{target}...{tip}", timeout=_GIT_TIMEOUT)
    if result.returncode != 0:
        return None
    return sum(int(count) for count in _SHORTSTAT_COUNT.findall(result.stdout))


def _pair_facts(repo: Path, tip: str, target: str, *, want_lines: bool) -> _PairFacts | None:
    """Ahead and unique patches (parks excluded), merges and lines; None on any failure."""
    keys = ",".join(f"key={key}" for key in _PARK_TRAILER_KEYS)
    log = run_git(
        repo,
        "log",
        "--boundary",
        f"--format=%m%x1f%H%x1f%T%x1f%P%x1f%(trailers:{keys},valueonly,unfold,separator=%x1d)",
        f"{target}..{tip}",
        timeout=_GIT_TIMEOUT,
    )
    if log.returncode != 0:
        return None
    walked = _park_shas(log.stdout)
    if walked is None:
        return None
    ahead = len(walked.commits) - len(walked.parks)
    if ahead == 0:
        return _PairFacts(ahead=0, unique=0, merges=0, lines=0 if want_lines else None)
    unique = branch_safety.cherry_unique_shas(repo, target, tip, timeout=_GIT_TIMEOUT)
    if unique is None:
        return None
    lines = _lines(repo, target, tip) if want_lines else None
    if want_lines and lines is None:
        return None
    return _PairFacts(
        ahead=ahead, unique=len(set(unique) - walked.parks), merges=walked.merges, lines=lines
    )


# --- never-work names ---------------------------------------------------------------


def _never_work(name: str, config: BranchesConfig, default: str | None) -> BranchState | None:
    """The non-work state of ``name``, or None when it is a work branch.

    Exempt, the default, an integration line or a protected name: never
    counted, never judged, and never "contained" work for another branch.
    """
    if branch_safety.matches_any_glob(name, config.exempt):
        return BranchState.EXEMPT
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
    vouching = [
        ref
        for ref in others
        if _never_work(ref.removeprefix(remote_prefix), config, default) is not None
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
    return _Cache(
        pairs=pairs if isinstance(pairs, dict) else {},
        containment=containment if isinstance(containment, dict) else {},
    )


def _save_cache(path: Path, cache: _Cache, live_tips: set[str]) -> None:
    """Write the cache, keeping only entries whose tip still exists."""
    document = {
        "version": _CACHE_VERSION,
        "pairs": {k: v for k, v in cache.pairs.items() if k.split(":", 1)[0] in live_tips},
        "containment": {
            k: v for k, v in cache.containment.items() if k.split(":", 1)[0] in live_tips
        },
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


def _facts_from_cache(entry: dict[str, Any] | None) -> _PairFacts | None:
    if not isinstance(entry, dict):
        return None
    ahead, unique, merges = entry.get("ahead"), entry.get("unique"), entry.get("merges")
    lines = entry.get("lines")
    if not (isinstance(ahead, int) and isinstance(unique, int) and isinstance(merges, int)):
        return None
    if lines is not None and not isinstance(lines, int):
        return None
    return _PairFacts(ahead=ahead, unique=unique, merges=merges, lines=lines)


# --- links ----------------------------------------------------------------------------


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
    ) -> None:
        self.repo = repo
        self.config = config
        self.cache = cache
        self.remote_refs = remote_refs
        self.deadline = time.monotonic() + config.sweep.budget_ms / 1000

    def _within_budget(self) -> bool:
        return time.monotonic() < self.deadline

    def facts(self, tip: str, target: _Target) -> _PairFacts | None:
        want_lines = target.is_default
        key = f"{tip}:{target.sha}:{'lines' if want_lines else 'nolines'}"
        cached = _facts_from_cache(self.cache.pairs.get(key))
        if cached is not None:
            return cached
        if not self._within_budget():
            return None
        computed = _pair_facts(self.repo, tip, target.sha, want_lines=want_lines)
        if computed is not None:
            self.cache.pairs[key] = {
                "ahead": computed.ahead,
                "unique": computed.unique,
                "merges": computed.merges,
                "lines": computed.lines,
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
        if not self._within_budget():
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
) -> BranchInventory:
    """Classify every local and remote branch of ``repo`` (DESIGN.md section 2).

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
    )
    cache_path = repo / CACHE_RELATIVE_PATH
    run = _Pass(repo, config, _load_cache(cache_path), remote_refs)

    records = {name: _record(run, context, name, *by_name[name]) for name in sorted(by_name)}
    records = _with_same_tips(records)
    _save_cache(cache_path, run.cache, set(sha_of.values()))
    return BranchInventory(
        default_branch=default,
        default_ref=default_ref,
        records=records,
        worktrees_known=context.worktrees is not None,
        remote_refs=made_listing(remote_refs),
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
            return _Verdict(BranchState.UNCLASSIFIED, reason=_UNMEASURED_REASON)
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
        return _Verdict(state, contained_by.name, contained_by.ref, ahead, lines)
    # A merge commit can carry content no patch-id shows, so it is never equivalent.
    equivalent = next((t for t, f in facts if f.unique == 0 and f.merges == 0), None)
    if equivalent is not None:
        return _Verdict(BranchState.PATCH_EQUIVALENT, equivalent.name, equivalent.ref, ahead, lines)
    return _Verdict(BranchState.LIVE, ahead=ahead, lines=lines)


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
    BranchState.DEFAULT,
    BranchState.INTEGRATION_LINE,
    BranchState.PROTECTED,
}


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
