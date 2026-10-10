"""Report-only detection of two kinds of litter an always-on checkout accumulates.

Plan 00470 Task 4.1 follow-ups. Both are REPORT-FIRST, like
:mod:`claude_code_hooks_daemon.utils.stale_checkouts`: this module reads the
filesystem and git, deletes nothing, and prints the command a human or agent MAY
choose to run. Nothing here runs it.

* Old files under ``untracked/scratch/``, which agents are told to use and
  nothing reaps. The scan is bounded by an entry limit and a time budget, never
  follows a symlink, and says so when it stopped early.
* ``refs/integration/changed-green/<branch>`` refs whose branch no longer
  exists anywhere. The QA ``changed`` tier writes one when a branch goes green
  and never prunes it, and each one pins its commit against ``git gc``. A ref is
  reported only when NO local branch and NO remote-tracking branch carries the
  name, so a branch that still exists keeps its record.
"""

from __future__ import annotations

import os
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.git_repo import HEADS_PREFIX
from claude_code_hooks_daemon.utils.stale_checkouts import ScanDeadline

_SECONDS_PER_DAY: Final[float] = 86400.0
_MINUTES_PER_DAY: Final[int] = 1440

#: Where agents are told to put working notes, relative to the project root.
SCRATCH_RELATIVE_PATH: Final[str] = "untracked/scratch"

#: Default age past which a scratch file is reported.
DEFAULT_SCRATCH_DAYS: Final[int] = 14

#: A scratch tree can hold tens of thousands of files; this caps one scan.
SCRATCH_MAX_ENTRIES: Final[int] = 100_000

#: Wall-clock cap on one scratch scan, so it cannot stall the prompt it rides on.
SCRATCH_BUDGET_SECONDS: Final[float] = 3.0

#: Refs the report names; the rest are counted. The one command covers all of them.
MAX_LISTED_REFS: Final[int] = 5

#: Budget for the git calls of the gone-branch ref scan.
REF_SCAN_BUDGET_SECONDS: Final[float] = 5.0

#: The QA ``changed`` tier's per-branch record. The script that writes it
#: (``scripts/qa/llm_qa.py``) cannot be imported from here: keep the spellings in step.
CHANGED_GREEN_PREFIX: Final[str] = "refs/integration/changed-green/"

_REMOTES_PREFIX: Final[str] = "refs/remotes/"

_BYTE_UNITS: Final[tuple[str, ...]] = ("B", "KiB", "MiB", "GiB", "TiB")
_BYTES_PER_UNIT: Final[int] = 1024


def _human_bytes(size: int) -> str:
    """``size`` with a binary unit, whole bytes below 1 KiB."""
    value = float(size)
    unit = 0
    while value >= _BYTES_PER_UNIT and unit < len(_BYTE_UNITS) - 1:
        value /= _BYTES_PER_UNIT
        unit += 1
    return f"{size} B" if unit == 0 else f"{value:.1f} {_BYTE_UNITS[unit]}"


@dataclass
class _ScratchTally:
    """What one bounded walk of the scratch tree found."""

    old_files: int = 0
    old_bytes: int = 0
    oldest_age_seconds: float = 0.0
    entries_seen: int = 0
    incomplete: bool = False


def _walk_scratch(
    scratch: Path,
    cutoff_age_seconds: float,
    now: float,
    max_entries: int,
    deadline: ScanDeadline,
) -> _ScratchTally:
    """Count files older than the cutoff, stopping at the entry or time limit.

    Symlinks are neither followed nor counted: a link into another tree would
    report files that are not scratch's to clear.
    """
    tally = _ScratchTally()
    pending = [scratch]
    while pending:
        directory = pending.pop()
        try:
            scanner = os.scandir(directory)
        except OSError:
            # A directory that vanished or is unreadable is skipped; a report
            # must not fail because scratch is being cleaned as it is read.
            tally.incomplete = True
            continue
        with scanner:
            for entry in scanner:
                if tally.entries_seen >= max_entries or deadline.expired():
                    tally.incomplete = True
                    return tally
                tally.entries_seen += 1
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    tally.incomplete = True
                    continue
                age = now - info.st_mtime
                if age > cutoff_age_seconds:
                    tally.old_files += 1
                    tally.old_bytes += info.st_size
                    tally.oldest_age_seconds = max(tally.oldest_age_seconds, age)
    return tally


def collect_scratch_report(
    scratch: Path,
    max_age_days: int,
    *,
    now: float | None = None,
    max_entries: int = SCRATCH_MAX_ENTRIES,
    budget_seconds: float = SCRATCH_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    deadline: ScanDeadline | None = None,
) -> str | None:
    """The report on files under ``scratch`` older than ``max_age_days``, or None.

    ``deadline`` is a budget shared with other scans; without one the scan gets
    its own ``budget_seconds``.

    Quiet when the directory is absent or holds nothing old. A scan that hit its
    entry limit or time budget is never quiet: a short count from a scan that
    stopped early is not the same statement as one from a scan that finished.
    """
    if not scratch.is_dir():
        return None
    current = time.time() if now is None else now
    shared = deadline or ScanDeadline(budget_seconds, clock=clock)
    tally = _walk_scratch(scratch, max_age_days * _SECONDS_PER_DAY, current, max_entries, shared)
    if tally.incomplete:
        shared.exhausted = True
    if tally.old_files == 0 and not tally.incomplete:
        return None

    quoted = shlex.quote(str(scratch))
    lines = [
        "OLD SCRATCH FILES (report only; this advisory never runs the command below - "
        "inspect, then choose):"
    ]
    if tally.incomplete:
        lines.append(
            "SCAN INCOMPLETE: it stopped at its entry limit or time budget, so the "
            "figures below are a lower bound."
        )
    if tally.old_files:
        noun = "file" if tally.old_files == 1 else "files"
        oldest_days = int(tally.oldest_age_seconds // _SECONDS_PER_DAY)
        lines.append(
            f"  - {tally.old_files} {noun}, {_human_bytes(tally.old_bytes)}, older than "
            f"{max_age_days} days under {scratch}; oldest {oldest_days} days"
        )
        lines.append(
            f"      find {quoted} -type f -mmin +{max_age_days * _MINUTES_PER_DAY} -delete"
        )
    return "\n".join(lines)


def _remote_branch_names(refname: str, remotes: tuple[str, ...]) -> set[str]:
    """The branch name(s) a ``refs/remotes/...`` ref can stand for.

    The remote is matched against the configured remote names (longest first),
    because a remote name may itself contain a slash. A ref under no configured
    remote has no known split, so every tail after a slash counts as live: a
    branch is never reported gone on a guess.
    """
    rest = refname.removeprefix(_REMOTES_PREFIX)
    for remote in sorted(remotes, key=len, reverse=True):
        if rest.startswith(f"{remote}/"):
            return {rest.removeprefix(f"{remote}/")}
    return {rest[index + 1 :] for index, char in enumerate(rest) if char == "/"}


def _gone_branch_refs(repo_root: Path, deadline: ScanDeadline) -> tuple[str, ...] | None:
    """Changed-green refs whose branch exists nowhere, or None when git cannot say."""
    remote_listing = deadline.run(repo_root, "remote")
    if remote_listing.returncode != 0:
        return None
    remotes = tuple(remote_listing.stdout.splitlines())
    listing = deadline.run(
        repo_root,
        "for-each-ref",
        "--format=%(refname)",
        HEADS_PREFIX,
        _REMOTES_PREFIX,
        CHANGED_GREEN_PREFIX,
    )
    if listing.returncode != 0:
        return None
    recorded: list[str] = []
    live: set[str] = set()
    for refname in listing.stdout.splitlines():
        if refname.startswith(CHANGED_GREEN_PREFIX):
            recorded.append(refname)
        elif refname.startswith(HEADS_PREFIX):
            live.add(refname.removeprefix(HEADS_PREFIX))
        elif refname.startswith(_REMOTES_PREFIX):
            live |= _remote_branch_names(refname, remotes)
    return tuple(ref for ref in recorded if ref.removeprefix(CHANGED_GREEN_PREFIX) not in live)


def collect_gone_branch_ref_report(
    repo_root: Path,
    *,
    budget_seconds: float = REF_SCAN_BUDGET_SECONDS,
    deadline: ScanDeadline | None = None,
) -> str | None:
    """The report on changed-green refs of branches that no longer exist, or None.

    Quiet when git cannot answer, no ref is recorded, or every recorded branch
    still exists locally or on a remote. At most ``MAX_LISTED_REFS`` refs are
    named; the single command covers every one, so the report stays short however
    many refs have piled up. ``deadline`` is a budget shared with other scans.
    """
    shared = deadline or ScanDeadline(budget_seconds)
    gone = _gone_branch_refs(repo_root, shared)
    if not gone and not shared.exhausted:
        return None
    lines = [
        "CHANGED-GREEN REFS OF GONE BRANCHES (report only; this advisory never runs "
        "the command below - inspect, then choose):"
    ]
    if shared.exhausted:
        lines.append("SCAN INCOMPLETE: the time budget ran out before git answered.")
    if gone:
        noun = "ref" if len(gone) == 1 else "refs"
        lines.append(
            f"{len(gone)} changed-green {noun} whose branch no longer exists locally or on a remote:"
        )
        lines.extend(f"  - {ref}" for ref in gone[:MAX_LISTED_REFS])
        if len(gone) > MAX_LISTED_REFS:
            lines.append(f"  ... and {len(gone) - MAX_LISTED_REFS} more")
        quoted = " ".join(shlex.quote(ref) for ref in gone)
        lines.append(f"      printf 'delete %s\\n' {quoted} | git update-ref --stdin")
    return "\n".join(lines)
