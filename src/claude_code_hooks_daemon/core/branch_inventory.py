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
5. per unmerged branch and target: a ``log`` walk (ahead, park commits),
   ``git cherry`` via :func:`branch_safety.cherry_unique_shas` and
   ``diff --shortstat`` (lines). Cached by ``(tip, target)`` in
   ``untracked/branch-inventory/cache.json`` and cut off at ``sweep.budget_ms``;
   a branch not reached is ``UNCLASSIFIED``, never guessed.

Every git error fails CLOSED: a branch whose proof could not be computed is
``UNCLASSIFIED``, never merged.

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
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.utils import git_sync
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import run_git

logger = logging.getLogger(__name__)

#: Repository-relative path of the per-pair cache.
CACHE_RELATIVE_PATH = Path("untracked/branch-inventory/cache.json")
_CACHE_VERSION = 1

_SECONDS_PER_DAY = 86_400
_HEADS = "refs/heads/"
_REMOTES = "refs/remotes/"
_REMOTE_HEAD = "HEAD"
_FIELD = "\x00"
_UNIT = "\x1f"
_GIT_TIMEOUT = Timeout.GIT_CONTEXT
_BOUNDARY_MARK = "-"

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
    MERGED_DEFAULT = "merged"
    MERGED_LINE = "merged-into-line"
    PATCH_EQUIVALENT = "patch-equivalent"
    PARKED = "parked"
    DORMANT = "dormant"
    LIVE = "live"
    UNCLASSIFIED = "not yet classified"


class DormancyStage(StrEnum):
    """DESIGN.md section 4 stages."""

    ADVISORY = "advisory"
    NOISY = "noisy"
    BLOCK = "block"


class Containment(StrEnum):
    """Where an idle branch's tip lives (DESIGN.md section 4)."""

    DEFAULT = "in the default branch"
    REMOTE_REF = "in another remote ref"
    OWN_REMOTE = "on its own remote only"
    NOWHERE = "nowhere"


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
    committed_at: int
    age_days: float
    parked_reason: str | None
    plan: str | None
    issue: int | None
    merged_into: str | None = None
    same_tip_as: tuple[str, ...] = ()
    dormancy_stage: DormancyStage | None = None
    containment: Containment | None = None
    contained_in: str | None = None


@dataclass(frozen=True)
class BranchInventory:
    """The result of one pass."""

    default_branch: str | None
    records: dict[str, BranchRecord]


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
class _PairFacts:
    """Step-5 facts for one ``(tip, target)`` pair, park commits excluded."""

    ahead: int
    unique: int
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


# --- step 1: refs -------------------------------------------------------------


def _ref_format(default_ref: str | None) -> str:
    ahead_behind = f"%(ahead-behind:{default_ref})" if default_ref else ""
    return _FIELD.join(
        (
            "%(refname)",
            "%(objectname)",
            "%(committerdate:unix)",
            "%(upstream)",
            ahead_behind,
            f"%(trailers:key={_PARK_REASON_KEY},valueonly,separator=%x1f)",
            "%(contents:subject)",
        )
    ).replace(_FIELD, "%00")


def _list_refs(repo: Path, remote: str, default_ref: str | None) -> list[_RefRow]:
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
    rows: list[_RefRow] = []
    for line in _lines_of(result.stdout):
        parts = line.split(_FIELD)
        if len(parts) != 7:
            continue
        refname, sha, date, upstream, ahead_behind, parked, subject = parts
        behind: int | None = None
        if ahead_behind:
            counts = ahead_behind.split()
            behind = int(counts[1]) if len(counts) == 2 and counts[1].isdigit() else None
        rows.append(
            _RefRow(
                refname=refname,
                sha=sha,
                committed_at=int(date) if date.isdigit() else 0,
                upstream=upstream.removeprefix(_REMOTES) or None,
                behind=behind,
                parked_reason=parked.split(_UNIT)[0].strip() or None,
                subject=subject,
            )
        )
    return rows


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


def _worktrees(repo: Path) -> dict[str, Path]:
    result = run_git(repo, "worktree", "list", "--porcelain", timeout=_GIT_TIMEOUT)
    if result.returncode != 0:
        logger.info("branch_inventory: worktree list failed: %s", result.stderr.strip())
        return {}
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


def _park_shas(log_output: str) -> tuple[list[str], set[str]] | None:
    """Range commits and the park commits among them, from a ``--boundary`` log."""
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
    return [sha for sha, _tree, _parents, _trailers in in_range], parks


def _lines(repo: Path, target: str, tip: str) -> int | None:
    result = run_git(repo, "diff", "--shortstat", f"{target}...{tip}", timeout=_GIT_TIMEOUT)
    if result.returncode != 0:
        return None
    return sum(int(count) for count in _SHORTSTAT_COUNT.findall(result.stdout))


def _pair_facts(repo: Path, tip: str, target: str, *, want_lines: bool) -> _PairFacts | None:
    """Ahead (parks excluded), unique patches (parks excluded) and lines; None on any failure."""
    keys = ",".join(f"key={key}" for key in _PARK_TRAILER_KEYS)
    log = run_git(
        repo,
        "log",
        "--boundary",
        f"--format=%m%x1f%H%x1f%T%x1f%P%x1f%(trailers:{keys},valueonly,separator=%x1d)",
        f"{target}..{tip}",
        timeout=_GIT_TIMEOUT,
    )
    if log.returncode != 0:
        return None
    walked = _park_shas(log.stdout)
    if walked is None:
        return None
    commits, parks = walked
    ahead = len(commits) - len(parks)
    if ahead == 0:
        return _PairFacts(ahead=0, unique=0, lines=0 if want_lines else None)
    unique = branch_safety.cherry_unique_shas(repo, target, tip, timeout=_GIT_TIMEOUT)
    if unique is None:
        return None
    lines = _lines(repo, target, tip) if want_lines else None
    if want_lines and lines is None:
        return None
    return _PairFacts(ahead=ahead, unique=len(set(unique) - parks), lines=lines)


# --- containment ------------------------------------------------------------------


def containment_of(
    repo: Path, *, name: str, tip: str, remote: str, default: str | None
) -> tuple[Containment, str | None] | None:
    """Where ``tip`` lives on ``remote`` (DESIGN.md section 4); None when git fails.

    The cherry arm of "in the default branch" is not repeated here: a branch
    whose patches are all in the default is classified patch-equivalent first.
    """
    if default is not None:
        default_ref = f"{_REMOTES}{remote}/{default}"
        ancestor = run_git(
            repo, "merge-base", "--is-ancestor", tip, default_ref, timeout=_GIT_TIMEOUT
        )
        if ancestor.returncode == 0:
            return Containment.DEFAULT, default_ref.removeprefix(_REMOTES)
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
    own = f"{_REMOTES}{remote}/{name}"
    head = f"{_REMOTES}{remote}/{_REMOTE_HEAD}"
    refs = sorted(ref for ref in result.stdout.splitlines() if ref and ref != head)
    others = [ref for ref in refs if ref != own]
    if others:
        return Containment.REMOTE_REF, others[0].removeprefix(_REMOTES)
    if own in refs:
        return Containment.OWN_REMOTE, own.removeprefix(_REMOTES)
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
    ahead, unique, lines = entry.get("ahead"), entry.get("unique"), entry.get("lines")
    if not isinstance(ahead, int) or not isinstance(unique, int):
        return None
    if lines is not None and not isinstance(lines, int):
        return None
    return _PairFacts(ahead=ahead, unique=unique, lines=lines)


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


def _matches(name: str, patterns: list[str]) -> bool:
    """Glob match on the branch name; ``*`` spans ``/`` (``release/*`` matches ``release/a/b``)."""
    return any(fnmatchcase(name, pattern) for pattern in patterns)


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

    def __init__(self, repo: Path, config: BranchesConfig, cache: _Cache) -> None:
        self.repo = repo
        self.config = config
        self.cache = cache
        self.deadline = time.monotonic() + config.sweep.budget_ms / 1000

    def _within_budget(self) -> bool:
        return time.monotonic() < self.deadline

    def facts(self, tip: str, target: _Target) -> _PairFacts | None:
        key = f"{tip}:{target.sha}"
        cached = _facts_from_cache(self.cache.pairs.get(key))
        if cached is not None:
            return cached
        if not self._within_budget():
            return None
        computed = _pair_facts(self.repo, tip, target.sha, want_lines=target.is_default)
        if computed is not None:
            self.cache.pairs[key] = {
                "ahead": computed.ahead,
                "unique": computed.unique,
                "lines": computed.lines,
            }
        return computed

    def containment(
        self, name: str, tip: str, default: str | None, remote_hash: str
    ) -> tuple[Containment, str | None] | None:
        key = f"{tip}:{remote_hash}:{name}"
        entry = self.cache.containment.get(key)
        if isinstance(entry, dict) and entry.get("containment") in {c.value for c in Containment}:
            ref = entry.get("ref")
            return Containment(entry["containment"]), ref if isinstance(ref, str) else None
        if not self._within_budget():
            return None
        found = containment_of(
            self.repo, name=name, tip=tip, remote=self.config.remote, default=default
        )
        if found is not None:
            self.cache.containment[key] = {"containment": found[0].value, "ref": found[1]}
        return found


def _group_rows(
    rows: list[_RefRow], remote: str
) -> dict[str, tuple[_RefRow | None, _RefRow | None]]:
    remote_prefix = f"{_REMOTES}{remote}/"
    grouped: dict[str, list[_RefRow | None]] = {}
    for row in rows:
        if row.refname.startswith(_HEADS):
            grouped.setdefault(row.refname.removeprefix(_HEADS), [None, None])[0] = row
        elif row.refname.startswith(remote_prefix):
            name = row.refname.removeprefix(remote_prefix)
            if name != _REMOTE_HEAD:
                grouped.setdefault(name, [None, None])[1] = row
    return {name: (pair[0], pair[1]) for name, pair in grouped.items()}


def build_inventory(
    repo: Path, config: BranchesConfig, *, now: float | None = None
) -> BranchInventory:
    """Classify every local and remote branch of ``repo`` (DESIGN.md section 2).

    Raises:
        BranchInventoryError: The refs could not be listed (not a repository,
            or git failed or timed out on the one bulk listing).
    """
    moment = time.time() if now is None else now
    remote = config.remote
    default = git_sync.resolve_default_branch(config, repo)
    default_ref = _default_ref(repo, remote, default)
    rows = _list_refs(repo, remote, default_ref)
    by_name = _group_rows(rows, remote)
    sha_of = {row.refname: row.sha for row in rows}
    remote_hash = hashlib.sha256(
        "\n".join(
            sorted(f"{r.refname} {r.sha}" for r in rows if r.refname.startswith(_REMOTES))
        ).encode()
    ).hexdigest()

    targets: list[_Target] = []
    if default is not None and default_ref is not None:
        targets.append(_Target(default, default_ref, sha_of[default_ref], is_default=True))
    for name in sorted(by_name):
        if name != default and _matches(name, config.integration_lines):
            local, remote_row = by_name[name]
            row = remote_row or local
            if row is not None:
                targets.append(_Target(name, row.refname, row.sha, is_default=False))

    merged_default: set[str] = set()
    if default is not None:
        for ref in (f"{_REMOTES}{remote}/{default}", f"{_HEADS}{default}"):
            if ref in sha_of:
                merged_default |= _merged_refs(repo, ref, remote)
    merged_lines = [(t, _merged_refs(repo, t.ref, remote)) for t in targets if not t.is_default]
    worktrees = _worktrees(repo)
    cache_path = repo / CACHE_RELATIVE_PATH
    run = _Pass(repo, config, _load_cache(cache_path))

    records: dict[str, BranchRecord] = {}
    for name in sorted(by_name):
        local, remote_row = by_name[name]
        chosen = local or remote_row
        if chosen is None:
            continue
        plan, issue = _links(name, chosen.subject)
        base: dict[str, Any] = {
            "name": name,
            "local_tip": local.sha if local else None,
            "remote_tip": remote_row.sha if remote_row else None,
            "upstream": local.upstream if local else None,
            "worktree": worktrees.get(name),
            "behind": chosen.behind,
            "committed_at": chosen.committed_at,
            "age_days": (moment - chosen.committed_at) / _SECONDS_PER_DAY,
            "parked_reason": chosen.parked_reason,
            "plan": plan,
            "issue": issue,
        }
        records[name] = _classify(
            run, name, chosen, base, targets, merged_default, merged_lines, default, remote_hash
        )

    records = _with_same_tips(records)
    _save_cache(cache_path, run.cache, {row.sha for row in rows})
    return BranchInventory(default_branch=default, records=records)


def _classify(
    run: _Pass,
    name: str,
    chosen: _RefRow,
    base: dict[str, Any],
    targets: list[_Target],
    merged_default: set[str],
    merged_lines: list[tuple[_Target, set[str]]],
    default: str | None,
    remote_hash: str,
) -> BranchRecord:
    config = run.config
    unmeasured: dict[str, Any] = {"ahead": None, "lines": None}
    if _matches(name, config.exempt):
        return BranchRecord(state=BranchState.EXEMPT, **base, **unmeasured)
    if name == default:
        return BranchRecord(state=BranchState.DEFAULT, **base, **unmeasured)
    if _matches(name, config.integration_lines):
        return BranchRecord(state=BranchState.INTEGRATION_LINE, **base, **unmeasured)
    if chosen.refname in merged_default:
        return BranchRecord(
            state=BranchState.MERGED_DEFAULT, merged_into=default, ahead=0, lines=0, **base
        )
    for line, merged in merged_lines:
        if chosen.refname in merged:
            return BranchRecord(
                state=BranchState.MERGED_LINE, merged_into=line.name, **base, **unmeasured
            )

    facts: list[tuple[_Target, _PairFacts]] = []
    for target in targets:
        found = run.facts(chosen.sha, target)
        if found is None:
            return BranchRecord(state=BranchState.UNCLASSIFIED, **base, **unmeasured)
        facts.append((target, found))
        if target.is_default and found.ahead == 0:
            break
    own: dict[str, Any] = unmeasured
    for target, found in facts:
        if target.is_default:
            own = {"ahead": found.ahead, "lines": found.lines}
    # Section 2 order: merged into the default, then into a line, then patch-equivalent.
    merged = [t for t, f in facts if f.ahead == 0]
    if merged:
        state = BranchState.MERGED_DEFAULT if merged[0].is_default else BranchState.MERGED_LINE
        return BranchRecord(state=state, merged_into=merged[0].name, **base, **own)
    equivalent = next((t for t, f in facts if f.unique == 0), None)
    if equivalent is not None:
        return BranchRecord(
            state=BranchState.PATCH_EQUIVALENT, merged_into=equivalent.name, **base, **own
        )

    if chosen.parked_reason is not None:
        return BranchRecord(state=BranchState.PARKED, **base, **own)
    stage = _stage(base["age_days"], config)
    if stage is None:
        return BranchRecord(state=BranchState.LIVE, **base, **own)
    found_in = run.containment(name, chosen.sha, default, remote_hash)
    return BranchRecord(
        state=BranchState.DORMANT,
        dormancy_stage=stage,
        containment=found_in[0] if found_in else None,
        contained_in=found_in[1] if found_in else None,
        **base,
        **own,
    )


_UNGROUPED = {BranchState.EXEMPT, BranchState.DEFAULT, BranchState.INTEGRATION_LINE}


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
