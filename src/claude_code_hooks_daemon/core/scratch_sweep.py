"""The read-only scratch sweep: one verdict per entry, as a table or JSON (Plan 00627 Task 1.7).

The sweep is a report and nothing else. It lists, ``lstat``s and judges; it
never creates, moves, packs or removes anything, and prints no file content
and no delete command; a filing proposal is printed, never acted on. Git is run once per sweep in the project (tracked files
under the root, worktrees, live remote tips, and the tracked lines that name
a scratch path) and, for a due entry holding a
repository, inside that repository under the rules of
:mod:`~claude_code_hooks_daemon.core.scratch_repos`.

One :class:`~claude_code_hooks_daemon.core.scratch_walk.WalkBudget` covers the
whole run. Each entry is judged as soon as it is walked and its node list is
dropped before the next walk, so memory grows with the number of entries, not
the number of inodes. An entry reached after the budget is spent still gets a
row (STUCK, or LIVE when its root's ctime proves it), and the report says it is
incomplete and why.
"""

from __future__ import annotations

import enum
import os
import stat
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import ScratchConfig
from claude_code_hooks_daemon.core.scratch_clock import NO_BIRTH_NOTE, EntryAge, entry_age
from claude_code_hooks_daemon.core.scratch_filing import (
    PlanIndex,
    Protection,
    build_plan_index,
    propose,
)
from claude_code_hooks_daemon.core.scratch_liveness import LivenessInputs, entry_liveness
from claude_code_hooks_daemon.core.scratch_references import (
    References,
    build_references,
)
from claude_code_hooks_daemon.core.scratch_repos import (
    ProjectGit,
    RepoFindings,
    blob_id,
    blob_length,
    classify_entry,
)
from claude_code_hooks_daemon.core.scratch_verdict import (
    NOT_EVALUATED,
    Judgement,
    Proof,
    RepositoryMarker,
    Verdict,
    judge,
    uncovered_nodes,
)
from claude_code_hooks_daemon.core.scratch_walk import (
    EntryStats,
    NodeKind,
    ScandirFn,
    WalkBudget,
    list_entries,
    walk_entry,
)
from claude_code_hooks_daemon.core.untracked_roots import SweepRoot
from claude_code_hooks_daemon.utils.bounded_walk import Bounded
from claude_code_hooks_daemon.utils.path_containment import (
    path_is_relative_to,
    path_relative_to,
)

_SECONDS_PER_HOUR = 3600.0

#: Said when no process working directory could be read at all.
NO_CWDS_NOTE = (
    "no process working directory could be read: the working-directory liveness "
    "signal was unavailable"
)

#: Table order: what needs a human first, what is in use last.
_TABLE_ORDER = (
    Verdict.STUCK,
    Verdict.PROTECTED,
    Verdict.REFERENCED,
    Verdict.UNCERTAIN,
    Verdict.DISPOSABLE,
    Verdict.LIVE,
)

_REPOSITORY_LABEL = {
    RepositoryMarker.FOUND: "repository",
    RepositoryMarker.NONE: "-",
    RepositoryMarker.UNKNOWN: "unknown (walk incomplete)",
}


#: P3's per-sweep hashing bounds (DESIGN.md section 3.2): files and bytes read.
P3_MAX_FILES = 20_000
P3_MAX_BYTES = 256 * 1024 * 1024


@dataclass
class HashBudget:
    """How many files and bytes P3 may still hash in this sweep."""

    max_files: int = P3_MAX_FILES
    max_bytes: int = P3_MAX_BYTES
    spent: bool = False

    def take(self, size: int) -> bool:
        """Spend one file of ``size`` bytes; False (and spent) when it does not fit."""
        if self.spent or self.max_files < 1 or size > self.max_bytes:
            self.spent = True
            return False
        self.max_files -= 1
        self.max_bytes -= size
        return True


#: Said when P3's hashing budget ran out: files left are not proved, never STUCK.
P3_BUDGET_NOTE = "the P3 hashing budget ran out: later files were not hashed and stay UNCERTAIN"


@dataclass(frozen=True)
class EntryRow:
    """One entry's line of the report. Holds no node list."""

    name: str
    kind: NodeKind
    verdict: Verdict
    reasons: tuple[str, ...]
    proofs: tuple[Proof, ...]
    repository: RepositoryMarker
    git_markers: tuple[str, ...]
    walk_complete: bool
    directories: int
    files: int
    bytes: int
    age_hours: float
    due: bool
    uncovered: tuple[str, ...]
    uncovered_count: int
    #: Where the entry could be filed, and the ``mv -n`` that would do it (empty: none).
    filing_destination: str = ""
    filing_command: str = ""


@dataclass(frozen=True)
class SweepReport:
    """The whole dry run."""

    root: str
    rows: tuple[EntryRow, ...]
    complete: bool
    incomplete_reasons: tuple[str, ...]
    notes: tuple[str, ...]
    not_evaluated: tuple[str, ...] = NOT_EVALUATED


def _relative(root: Path, project_root: Path) -> str | None:
    """``root`` from the project root, or None for a root outside the project."""
    if not path_is_relative_to(root, project_root):
        return None
    return path_relative_to(root, project_root).as_posix()


def _root_problem(root: Path) -> tuple[str, bool]:
    """Why ``root`` cannot be listed, and whether that is "it does not exist"."""
    try:
        info = root.lstat()
    except FileNotFoundError:
        return f"scratch root {root} does not exist: nothing to sweep", True
    except OSError as exc:
        return f"scratch root {root} could not be read: {type(exc).__name__}", False
    if stat.S_ISLNK(info.st_mode):
        return f"scratch root {root} is a link: not followed", False
    if not stat.S_ISDIR(info.st_mode):
        return f"scratch root {root} is not a directory", False
    return "", False


def run_sweep(
    sweep_root: SweepRoot,
    *,
    config: ScratchConfig,
    now: float,
    budget: WalkBudget,
    inputs: LivenessInputs,
    project_root: Path,
    project_git: ProjectGit | None,
    scandir: ScandirFn = os.scandir,
    hash_budget: HashBudget | None = None,
    plan_dir: str | None = None,
) -> SweepReport:
    """Judge every entry of a resolved sweep root; read only.

    The root comes from :func:`~claude_code_hooks_daemon.core.untracked_roots.resolve_sweep_root`,
    so a refused root (``untracked/repos``, a reference root, a ``"*"`` TTL) is
    reported and never listed, and an entry holding a never-swept path is skipped.
    ``project_git`` is the project's repository read once (None: git unavailable,
    so every due entry is STUCK: nothing can be proved about tracked files).
    ``plan_dir`` is the project's plan directory, indexed once for filing
    proposals (None: no plan folder is proposed).
    """
    root = sweep_root.path
    notes: list[str] = [] if inputs.cwds else [NO_CWDS_NOTE]
    if sweep_root.refusal or sweep_root.ttl_hours is None:
        return SweepReport(str(root), (), False, (sweep_root.refusal,), tuple(notes))
    ttl_hours = sweep_root.ttl_hours
    notes.extend(sweep_root.notes)
    problem, absent = _root_problem(root)
    if absent:
        return SweepReport(str(root), (), True, (), (*notes, problem))
    if problem:
        return SweepReport(str(root), (), False, (problem,), tuple(notes))
    listing = list_entries(root, scandir=scandir)
    if not listing.complete:
        return SweepReport(str(root), (), False, (listing.reason,), tuple(notes))
    resolved_root = root.resolve()
    relative_root = _relative(resolved_root, project_root.resolve())
    tracked = _tracked_by_entry(project_git, project_root, relative_root)
    references = build_references(project_git, relative_root)
    hashing = hash_budget or HashBudget()
    filing = _Filing(
        build_plan_index(project_root, plan_dir),
        project_root,
        relative_root,
        config.filing.max_bytes,
    )
    if project_git is not None and project_git.verified_note:
        notes.append(f"remote proof: {project_git.verified_note}")
    rows = [
        _judge_entry(
            root,
            resolved_root,
            relative_root,
            name,
            _EntryClock(ttl_hours, max(config.max_lifetime_hours, ttl_hours), now),
            budget,
            inputs,
            scandir,
            _EntryGit(
                project_git,
                None if tracked is None else tracked.get(name, ()),
                hashing,
                references.for_entry(name),
            ),
            filing,
        )
        for name in listing.value
        if name not in sweep_root.skip
    ]
    if hashing.spent:
        notes.append(P3_BUDGET_NOTE)
    if rows:
        # Phase 1 records no birth for any entry, so the note holds for every row: said once.
        notes.append(NO_BIRTH_NOTE)
    stopped = sum(not row.walk_complete for row in rows)
    reasons: list[str] = []
    if stopped:
        noun = "entry" if stopped == 1 else "entries"
        reasons.append(f"{stopped} {noun} not walked to the end")
    if budget.spent_reason:
        reasons.append(budget.spent_reason)
    if tracked is None:
        reasons.append("the project's tracked files under the root could not be listed")
    if references.unknown:
        reasons.append(references.unknown)
    return SweepReport(str(root), tuple(rows), not reasons, tuple(reasons), tuple(notes))


def _tracked_by_entry(
    project_git: ProjectGit | None, project_root: Path, relative_root: str | None
) -> dict[str, tuple[str, ...]] | None:
    """Tracked paths under the root by entry name; None when they could not be listed."""
    if project_git is None or relative_root is None:
        return None
    result = project_git.runner(project_root, "ls-files", "-z", "--", relative_root)
    if result.returncode != 0:
        return None
    by_entry: dict[str, list[str]] = {}
    prefix = f"{relative_root}/"
    for path in filter(None, result.stdout.split("\0")):
        if not path.startswith(prefix):
            return None
        rel = path[len(prefix) :]
        by_entry.setdefault(rel.split("/", 1)[0], []).append(rel)
    return {name: tuple(paths) for name, paths in by_entry.items()}


@dataclass(frozen=True)
class _EntryGit:
    """The project's git, and the entry's paths the project tracks (None: unknown)."""

    project: ProjectGit | None
    tracked: tuple[str, ...] | None
    hashing: HashBudget
    references: References


@dataclass(frozen=True)
class _Filing:
    """What a filing proposal needs, built once per sweep."""

    plans: PlanIndex
    project_root: Path
    relative_root: str | None
    max_bytes: int


@dataclass(frozen=True)
class _EntryClock:
    """The root's TTL, the lifetime backstop (never shorter than the TTL), and now."""

    ttl_hours: int
    max_lifetime_hours: int
    now: float


def _judge_entry(
    root: Path,
    resolved_root: Path,
    relative_root: str | None,
    name: str,
    clock: _EntryClock,
    budget: WalkBudget,
    inputs: LivenessInputs,
    scandir: ScandirFn,
    git: _EntryGit,
    filing: _Filing,
) -> EntryRow:
    now = clock.now
    walk = walk_entry(root, name, now=now, budget=budget, scandir=scandir)
    stats = walk.value
    age = entry_age(
        stats, now=now, ttl_hours=clock.ttl_hours, max_lifetime_hours=clock.max_lifetime_hours
    )
    liveness = entry_liveness(
        resolved_root / name,
        relative=f"{relative_root}/{name}" if relative_root else None,
        root_ctime_ns=stats.root_ctime_ns,
        birth=None,
        inputs=inputs,
    )
    repos: RepoFindings | None = None
    needs_git = not liveness and age.due and walk.complete and not stats.multi_linked
    if needs_git and git.project is not None:
        repos = classify_entry(
            root,
            name,
            nodes=tuple(node.path for node in stats.nodes),
            markers=stats.git_markers,
            project=git.project,
        )
    judgement = judge(
        walk,
        age=age,
        liveness=liveness,
        references=git.references,
        repos=repos,
        tracked=git.tracked,
    )
    if judgement.verdict is Verdict.UNCERTAIN:
        judgement = _with_p3(root, walk, age, repos, git, judgement)
    proposal = propose(
        name,
        kind=stats.kind,
        size=stats.bytes,
        verdict=judgement.verdict,
        protection=_protection(judgement.verdict, repos, git.tracked),
        plans=filing.plans,
        project_root=filing.project_root,
        relative_root=filing.relative_root,
        max_bytes=filing.max_bytes,
    )
    return EntryRow(
        name=name,
        kind=stats.kind,
        verdict=judgement.verdict,
        reasons=judgement.reasons,
        proofs=judgement.proofs,
        repository=judgement.repository,
        git_markers=judgement.git_markers,
        walk_complete=walk.complete,
        directories=stats.directories,
        files=stats.files,
        bytes=stats.bytes,
        age_hours=round(age.age_seconds / _SECONDS_PER_HOUR, 1),
        due=age.due,
        uncovered=judgement.uncovered,
        uncovered_count=judgement.uncovered_count,
        filing_destination=proposal.destination if proposal else "",
        filing_command=proposal.command if proposal else "",
    )


def _protection(
    verdict: Verdict, repos: RepoFindings | None, tracked: tuple[str, ...] | None
) -> Protection:
    """Why a PROTECTED entry is protected, in the order ``judge`` decides it."""
    if verdict is not Verdict.PROTECTED:
        return Protection.NONE
    if repos is not None and repos.protected:
        return Protection.REPOSITORY
    return Protection.TRACKED if tracked else Protection.NONE


def _with_p3(
    root: Path,
    walk: Bounded[EntryStats],
    age: EntryAge,
    repos: RepoFindings | None,
    git: _EntryGit,
    judgement: Judgement,
) -> Judgement:
    """Re-judge an UNCERTAIN entry once its uncovered regular files are hashed (P3).

    Nothing is hashed when the remote-held blob set is unknown, or when an
    uncovered node is not a regular file (the entry stays UNCERTAIN whatever
    the hashes say). The walk's node list bounds what is read.
    """
    blobs = git.project.remote_blobs if git.project is not None else None
    length = blob_length(blobs)
    if blobs is None or length is None:
        return judgement
    nodes = uncovered_nodes(walk.value.nodes, repos)
    if any(node.kind is not NodeKind.FILE for node in nodes):
        return judgement
    held: set[str] = set()
    for node in nodes:
        if not git.hashing.take(node.size):
            return judgement
        if blob_id(root / node.path, sha_length=length) in blobs:
            held.add(node.path)
    if len(held) < len(nodes):
        return judgement
    return judge(
        walk,
        age=age,
        liveness=(),
        references=git.references,
        repos=repos,
        tracked=git.tracked,
        p3=frozenset(held),
    )


def _printable(text: str) -> str:
    return "".join(char if char.isprintable() else f"\\x{ord(char):02x}" for char in text)


def _counts(report: SweepReport) -> dict[str, int]:
    counted = Counter(row.verdict for row in report.rows)
    return {verdict.value: counted[verdict] for verdict in Verdict if counted[verdict]}


def render_table(report: SweepReport, *, max_listed: int) -> list[str]:
    """The report as text, at most ``max_listed`` entry rows."""
    lines = [f"Scratch sweep of {_printable(report.root)} (dry run: nothing was changed)"]
    if not report.complete:
        lines.append("INCOMPLETE: " + "; ".join(report.incomplete_reasons))
    counts = _counts(report)
    summary = ", ".join(f"{verdict} {count}" for verdict, count in counts.items())
    lines.append(f"Entries: {len(report.rows)}" + (f" ({summary})" if summary else ""))
    lines.append("Not evaluated in this phase: " + ", ".join(report.not_evaluated))
    lines.extend(f"Note: {note}" for note in report.notes)
    if not report.rows:
        return lines
    ordered = sorted(report.rows, key=lambda row: (_TABLE_ORDER.index(row.verdict), row.name))
    lines.append("")
    lines.append(
        f"{'ENTRY':<32} {'VERDICT':<10} {'AGE_H':>7} {'DIRS':>6} {'FILES':>7} "
        f"{'BYTES':>11} {'PROOFS':<9} REPOSITORY / REASON"
    )
    for row in ordered[:max_listed]:
        proofs = ",".join(proof.value for proof in row.proofs) or "-"
        detail = "; ".join(
            [_REPOSITORY_LABEL[row.repository], *(_printable(reason) for reason in row.reasons)]
        )
        lines.append(
            f"{_printable(row.name):<32} {row.verdict.value:<10} {row.age_hours:>7.1f} "
            f"{row.directories:>6} {row.files:>7} {row.bytes:>11} {proofs:<9} {detail}"
        )
    hidden = len(ordered) - max_listed
    if hidden > 0:
        lines.append(f"... and {hidden} more (--json lists every entry)")
    lines.extend(_render_filing(ordered, max_listed=max_listed))
    return lines


def _render_filing(ordered: list[EntryRow], *, max_listed: int) -> list[str]:
    """The "Filing proposals" section: a suggestion per row, nothing acted on."""
    proposed = [row for row in ordered if row.filing_destination]
    if not proposed:
        return []
    lines = ["", "Filing proposals (suggestions only: nothing is moved by the sweep)"]
    for row in proposed[:max_listed]:
        lines.append(f"{_printable(row.name)}: {_printable(row.filing_destination)}")
        if row.filing_command:
            lines.append(f"    {row.filing_command}")
    hidden = len(proposed) - max_listed
    if hidden > 0:
        lines.append(f"... and {hidden} more proposal(s) (--json lists every entry)")
    return lines


def _row_json(row: EntryRow) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in vars(row).items():
        if isinstance(value, enum.Enum):
            document[key] = value.value
        elif isinstance(value, tuple):
            document[key] = [item.value if isinstance(item, enum.Enum) else item for item in value]
        else:
            document[key] = value
    return document


def report_json(report: SweepReport) -> dict[str, Any]:
    """The report as a JSON-ready document, every row included."""
    return {
        "root": report.root,
        "dry_run": True,
        "complete": report.complete,
        "incomplete_reasons": list(report.incomplete_reasons),
        "notes": list(report.notes),
        "not_evaluated": list(report.not_evaluated),
        "counts": _counts(report),
        "entries": [_row_json(row) for row in report.rows],
    }


__all__ = [
    "NO_CWDS_NOTE",
    "P3_BUDGET_NOTE",
    "P3_MAX_BYTES",
    "P3_MAX_FILES",
    "EntryRow",
    "HashBudget",
    "SweepReport",
    "render_table",
    "report_json",
    "run_sweep",
]
