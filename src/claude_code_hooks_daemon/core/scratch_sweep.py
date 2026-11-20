"""The read-only scratch sweep: one verdict per entry, as a table or JSON (Plan 00627 Task 1.7).

Phase 1 is a report and nothing else. It lists, ``lstat``s and judges; it
never creates, moves, packs or removes anything, never opens a file, and
prints no file content and no removal command.

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
from claude_code_hooks_daemon.core.scratch_clock import NO_BIRTH_NOTE, entry_age
from claude_code_hooks_daemon.core.scratch_liveness import LivenessInputs, entry_liveness
from claude_code_hooks_daemon.core.scratch_verdict import (
    NOT_EVALUATED,
    Proof,
    RepositoryMarker,
    Verdict,
    judge,
)
from claude_code_hooks_daemon.core.scratch_walk import (
    NodeKind,
    ScandirFn,
    WalkBudget,
    list_entries,
    walk_entry,
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
    Verdict.REPOSITORY,
    Verdict.UNCERTAIN,
    Verdict.DISPOSABLE,
    Verdict.LIVE,
)

_REPOSITORY_LABEL = {
    RepositoryMarker.FOUND: "repository, not judged",
    RepositoryMarker.NONE: "-",
    RepositoryMarker.UNKNOWN: "unknown (walk incomplete)",
}


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
    try:
        return root.relative_to(project_root).as_posix()
    except ValueError:
        return None


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
    root: Path,
    *,
    config: ScratchConfig,
    now: float,
    budget: WalkBudget,
    inputs: LivenessInputs,
    project_root: Path,
    scandir: ScandirFn = os.scandir,
) -> SweepReport:
    """Judge every entry of scratch root ``root``; read only."""
    notes: list[str] = [] if inputs.cwds else [NO_CWDS_NOTE]
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
    rows = [
        _judge_entry(root, resolved_root, relative_root, name, config, now, budget, inputs, scandir)
        for name in listing.value
    ]
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
    return SweepReport(str(root), tuple(rows), not reasons, tuple(reasons), tuple(notes))


def _judge_entry(
    root: Path,
    resolved_root: Path,
    relative_root: str | None,
    name: str,
    config: ScratchConfig,
    now: float,
    budget: WalkBudget,
    inputs: LivenessInputs,
    scandir: ScandirFn,
) -> EntryRow:
    walk = walk_entry(root, name, now=now, budget=budget, scandir=scandir)
    stats = walk.value
    age = entry_age(
        stats, now=now, ttl_hours=config.ttl_hours, max_lifetime_hours=config.max_lifetime_hours
    )
    liveness = entry_liveness(
        resolved_root / name,
        relative=f"{relative_root}/{name}" if relative_root else None,
        root_ctime_ns=stats.root_ctime_ns,
        birth=None,
        inputs=inputs,
    )
    judgement = judge(walk, age=age, liveness=liveness)
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
    "EntryRow",
    "SweepReport",
    "render_table",
    "report_json",
    "run_sweep",
]
