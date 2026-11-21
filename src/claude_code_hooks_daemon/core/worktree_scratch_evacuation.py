"""Whether a worktree's scratch may be evacuated before the worktree is reaped (Plan 00627 Task 6.2).

Evacuation archives every entry of a linked worktree's scratch root into the
main checkout's store, so ``worktree-reap --reap`` can then remove the
worktree. It ignores the TTL, so it is all or nothing: this gate decides on
one complete classification, BEFORE the question is asked and before anything
is packed, and one entry it cannot clear refuses the whole worktree.

Root-level entries only. A session directory (``s-*``) anywhere refuses the
worktree: once the worktree is gone, restore cannot recreate the session
directory its children's records name (DESIGN.md section 13), so a human
files or deletes them by hand.

An entry passes when its walk is complete and it is either due with an
actionable verdict, or not due and held by its TTL alone. It must also have a
readable birth stamp (the consent binds a not-due entry to its inode, fix A)
and hold no inode another user owns (fix B). Every other row is a blocker
named with its verdict.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.core.scratch_archive_apply import (
    ACTIONABLE,
    Pressure,
    consent_to,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    DEFAULT_MAX_DEPTH,
    WalkRefused,
    open_dir,
    walk_tree,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import PackRefused, refuse_foreign_owner
from claude_code_hooks_daemon.core.scratch_session import is_session_dir_name
from claude_code_hooks_daemon.core.scratch_sweep import EntryRow, SweepReport, pending_verdict
from claude_code_hooks_daemon.utils.birth_time import birth_stamp
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

_LOG = logging.getLogger(__name__)

SESSION_BLOCKER = (
    "{name}: a session directory: evacuation handles root-level entries only, "
    "and restore cannot recreate it once the worktree is gone (DESIGN.md section 13)"
)
NO_BIRTH_STAMP = "{name}: no birth stamp"


@dataclass(frozen=True)
class EvacuationGate:
    """The gate's decision on one report: blockers, or the consent the run is bound to."""

    blockers: tuple[str, ...]
    #: Bound to the not-due entries the report lists; None whenever anything blocks.
    consent: Pressure | None
    entries: int
    not_due: int
    #: ``(verdict, count)`` of the verdict each entry would be archived under, sorted.
    by_verdict: tuple[tuple[str, int], ...]


def evacuation_consent(report: SweepReport, ttl_hours: float) -> Pressure | None:
    """Consent to every not-due entry of ``report`` as it stands now, bound to its inode."""
    return consent_to(report, Pressure(idle_hours=0, ttl_hours=ttl_hours))


def evacuation_gate(
    report: SweepReport,
    *,
    ttl_hours: float,
    max_inodes: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> EvacuationGate:
    """Decide on ``report`` whether every entry of its root may be evacuated."""
    blockers = _report_blockers(report)
    if not blockers:
        blockers = _inode_blockers(report, max_inodes=max_inodes, max_depth=max_depth)
    consent: Pressure | None = None
    if not blockers:
        consent = evacuation_consent(report, ttl_hours)
        blockers = _unconsented(report, consent)
    counts = Counter(pending_verdict(row).value for row in report.rows)
    return EvacuationGate(
        blockers=tuple(blockers),
        consent=None if blockers else consent,
        entries=len(report.rows),
        not_due=sum(1 for row in report.rows if not row.due),
        by_verdict=tuple(sorted(counts.items())),
    )


def _report_blockers(report: SweepReport) -> list[str]:
    """What the classification alone refuses: incompleteness, sessions, a holding row."""
    if not report.complete:
        return [f"classification incomplete: {'; '.join(report.incomplete_reasons)}"]
    blockers = [SESSION_BLOCKER.format(name=Path(sub.root).name) for sub in report.sessions]
    for row in report.rows:
        reason = _row_blocker(row)
        if reason:
            blockers.append(reason)
    return blockers


def _row_blocker(row: EntryRow) -> str:
    """Why ``row`` refuses the worktree, or "" when it may be evacuated."""
    if is_session_dir_name(row.name):
        return SESSION_BLOCKER.format(name=row.name)
    if not row.walk_complete:
        return f"{row.name}: walk incomplete"
    if row.due:
        return "" if row.verdict in ACTIONABLE else f"{row.name}: {row.verdict.value}"
    if row.ttl_hold is None:
        return f"{row.name}: {row.verdict.value}"
    if row.ttl_hold not in ACTIONABLE:
        return f"{row.name}: {row.ttl_hold.value} (not yet due)"
    return ""


def _inode_blockers(report: SweepReport, *, max_inodes: int, max_depth: int) -> list[str]:
    """Each entry's birth stamp readable and no inode another user owns, checked before any pack."""
    if not report.rows:
        return []
    try:
        root_fd = open_dir(Path(report.root))
    except OSError as exc:
        log_and_continue(_LOG, exc, reason=f"{report.root}: not opened, nothing evacuated")
        return [f"{report.root}: could not be opened"]
    try:
        return [
            reason
            for row in report.rows
            if (reason := _entry_blocker(root_fd, row.name, max_inodes, max_depth))
        ]
    finally:
        os.close(root_fd)


def _entry_blocker(root_fd: int, name: str, max_inodes: int, max_depth: int) -> str:
    try:
        stamp = birth_stamp(root_fd, name)
    except OSError as exc:
        log_and_continue(_LOG, exc, reason=f"{name!r}: birth stamp unreadable, not evacuated")
        return NO_BIRTH_STAMP.format(name=name)
    if stamp is None:
        return NO_BIRTH_STAMP.format(name=name)
    try:
        listing = walk_tree(root_fd, name, max_inodes=max_inodes, max_depth=max_depth)
        refuse_foreign_owner(listing, name)
    except PackRefused as exc:
        return f"{name}: {exc}"
    except (WalkRefused, OSError) as exc:
        log_and_continue(_LOG, exc, reason=f"{name!r} cannot be walked, not evacuated")
        return f"{name}: cannot be walked"
    return ""


def _unconsented(report: SweepReport, consent: Pressure | None) -> list[str]:
    """A not-due entry the consent could not bind (its stamp unreadable now) is a blocker."""
    bound = consent.consented if consent is not None and consent.consented else frozenset()
    return [
        NO_BIRTH_STAMP.format(name=row.name)
        for row in report.rows
        if not row.due and str(Path(report.root) / row.name) not in bound
    ]
