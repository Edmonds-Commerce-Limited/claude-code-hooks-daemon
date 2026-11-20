"""Apply the scratch sweep: archive, verify, record, then remove (Plan 00627 Task 3.8).

DESIGN.md section 5.2. One run, under the store lock, in this order:

1. Staging directories a crashed restore left are reclaimed.
2. Every leftover ``.sweeping-`` claim is resumed (finished or renamed back).
3. Every other entry is fingerprinted BEFORE it is classified, so a change made
   while classification runs is caught at the claim.
4. The classification is taken fresh, inside this call (a report is never an
   input). An incomplete report claims nothing new.
5. Only a due DISPOSABLE or UNCERTAIN entry is claimed; the claim re-checks
   the fingerprint, a fresh liveness reading and a fresh reference reading.
6. It is packed and verified, its record appended, and the claimed tree is
   removed by :mod:`~claude_code_hooks_daemon.core.scratch_archive_remove`,
   the only module that deletes from a scratch root. This module calls no
   deleting primitive at all.
7. Unfinished adoptions are reported, not finished.
8. Expiry runs LAST, holding any archive whose entry still has a ``.sweeping-``
   tree (a partly removed tree whose archive is the only copy) or that a
   tracked file still names.

REFERENCED, STUCK, PROTECTED and LIVE entries are never touched; that REFERENCED
is not archived diverges from DESIGN 5.2 (recorded in DESIGN section 13).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from claude_code_hooks_daemon.core.scratch_archive import (
    AdoptEvent,
    ArchiveRecord,
    ArchiveStore,
    StoreAudit,
    StoreRefused,
    new_archive_id,
)
from claude_code_hooks_daemon.core.scratch_archive_adopt import unfinished_adoptions
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    CLAIM_PREFIX,
    DEFAULT_MAX_DEPTH,
    Claimed,
    ClaimRefused,
    ClaimStuck,
    Fingerprint,
    RenamedBack,
    WalkRefused,
    bounded_names,
    claim,
    fingerprint_at,
    open_dir,
    release,
)
from claude_code_hooks_daemon.core.scratch_archive_expire import (
    ExpiryOutcome,
    ExpiryRefused,
    expire_due,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    PackRefused,
    PackResult,
    TarTool,
    pack,
)
from claude_code_hooks_daemon.core.scratch_archive_remove import (
    RemoveRefused,
    Resumed,
    remove_claimed,
    resume_claimed,
)
from claude_code_hooks_daemon.core.scratch_archive_restore import Reclaimed, reclaim_staging
from claude_code_hooks_daemon.core.scratch_sweep import EntryRow, SweepReport
from claude_code_hooks_daemon.core.scratch_verdict import Verdict

#: The only verdicts an apply run acts on, and only when the entry is due.
ACTIONABLE = frozenset({Verdict.DISPOSABLE, Verdict.UNCERTAIN})

#: Step names passed to ``after_step`` (the crash-test seam).
STEP_CLAIM = "claim"
STEP_PACK = "pack"
STEP_APPEND = "append"

RESTORE_COMMAND = "hooks-daemon scratch-sweep restore {archive_id}"


@dataclass(frozen=True)
class ApplyFacts:
    """Sources of fresh facts; each is CALLED inside the run, never cached across runs.

    ``entry_live(name)`` must check both ``<root>/<name>`` and
    ``<root>/.sweeping-<name>`` (after the claim's rename a process inside has
    its working directory under the claimed name). ``referenced(name)`` is True
    when a tracked file names the entry or that cannot be known. Either raising
    counts as "not safe".
    """

    classify: Callable[[], SweepReport]
    entry_live: Callable[[str], bool]
    referenced: Callable[[str], bool]


@dataclass(frozen=True)
class ApplySettings:
    """Where and how one run packs."""

    root: Path
    #: The root from the project, recorded as each entry's ``original_path`` prefix.
    original_prefix: str
    checkout: str
    tar: TarTool
    max_inodes: int
    #: Hours by verdict string, from ``scratch.archive``.
    retention_hours: Mapping[str, float]
    clock: Callable[[], datetime]
    max_depth: int = DEFAULT_MAX_DEPTH


@dataclass(frozen=True)
class EntryOutcome:
    """What one run did with one entry the classification listed."""

    name: str
    #: archived | not-actionable | not-fingerprinted | refused | renamed-back | stuck | left-claimed
    outcome: str
    reason: str = ""
    archive_id: str = ""


@dataclass(frozen=True)
class ApplyResult:
    """Everything one apply run did and found."""

    complete: bool
    incomplete_reasons: tuple[str, ...]
    reclaimed: tuple[Reclaimed, ...]
    resumed: tuple[Resumed, ...]
    entries: tuple[EntryOutcome, ...]
    expired: tuple[ExpiryOutcome, ...]
    unfinished_adoptions: tuple[AdoptEvent, ...]
    audit: StoreAudit
    notes: tuple[str, ...]


def _no_step(step: str, name: str) -> None:
    """The default ``after_step``: nothing."""


def apply_sweep(
    store: ArchiveStore,
    facts: ApplyFacts,
    settings: ApplySettings,
    *,
    after_step: Callable[[str, str], None] = _no_step,
) -> ApplyResult:
    """Run one apply pass; the caller holds ``store.lock()``.

    ``after_step(step, name)`` is called after each claim, pack and record
    append; tests raise from it to simulate a kill between steps.
    """
    store.require_lock("apply")
    notes: list[str] = []
    root_fd = open_dir(settings.root)
    try:
        reclaimed = reclaim_staging(store, max_depth=settings.max_depth)
        resumed = tuple(
            _resume(root_fd, name, store, settings)
            for name in bounded_names(root_fd, settings.max_inodes)
            if name.startswith(CLAIM_PREFIX)
        )
        # Listed again: a claim renamed back above is an entry to judge this run.
        names = bounded_names(root_fd, settings.max_inodes)
        fingerprints = _fingerprint_all(root_fd, names, settings)
        report = facts.classify()
        entries = [
            _apply_row(root_fd, row, report, fingerprints, store, facts, settings, after_step)
            for row in report.rows
        ]
        adoptions = unfinished_adoptions(store)
        if adoptions:
            notes.append(
                f"{len(adoptions)} unfinished adoption(s) reported, not finished: "
                "finishing needs a verdict only a fresh row supplies"
            )
        expired = _expire(root_fd, store, facts, settings, notes)
        audit = store.audit()
        if audit.unrecorded_archives:
            notes.append(
                f"{len(audit.unrecorded_archives)} archive(s) no record names "
                "(a run stopped between pack and record): left in place"
            )
    finally:
        os.close(root_fd)
    return ApplyResult(
        complete=report.complete,
        incomplete_reasons=report.incomplete_reasons,
        reclaimed=reclaimed,
        resumed=resumed,
        entries=tuple(entries),
        expired=expired,
        unfinished_adoptions=adoptions,
        audit=audit,
        notes=tuple(notes),
    )


def _resume(
    root_fd: int, claimed_name: str, store: ArchiveStore, settings: ApplySettings
) -> Resumed:
    """Resume one leftover claim; a refusal leaves it whole and is reported stuck."""
    name = claimed_name.removeprefix(CLAIM_PREFIX)
    try:
        return resume_claimed(
            root_fd,
            claimed_name,
            store,
            checkout=settings.checkout,
            tar=settings.tar,
            max_inodes=settings.max_inodes,
            clock=settings.clock,
            retention_hours=settings.retention_hours,
            max_depth=settings.max_depth,
        )
    except (RemoveRefused, ValueError) as exc:
        return Resumed(name, "stuck", f"resume refused: {exc}")


def _fingerprint_all(
    root_fd: int, names: list[str], settings: ApplySettings
) -> dict[str, Fingerprint]:
    """Each unclaimed entry's fingerprint; an entry that cannot be walked is left out."""
    prints: dict[str, Fingerprint] = {}
    for name in names:
        if name.startswith(CLAIM_PREFIX):
            continue
        try:
            prints[name] = fingerprint_at(
                root_fd, name, max_inodes=settings.max_inodes, max_depth=settings.max_depth
            )
        except (WalkRefused, OSError):
            continue
    return prints


def _actionable(row: EntryRow) -> bool:
    return row.due and row.walk_complete and row.verdict in ACTIONABLE


def _safe(facts: ApplyFacts, name: str) -> bool:
    """A fresh liveness and reference reading both say the entry may go."""
    return not facts.entry_live(name) and not facts.referenced(name)


def _apply_row(
    root_fd: int,
    row: EntryRow,
    report: SweepReport,
    fingerprints: Mapping[str, Fingerprint],
    store: ArchiveStore,
    facts: ApplyFacts,
    settings: ApplySettings,
    after_step: Callable[[str, str], None],
) -> EntryOutcome:
    name = row.name
    if not report.complete or not _actionable(row):
        return EntryOutcome(name, "not-actionable", row.verdict.value)
    expected = fingerprints.get(name)
    if expected is None:
        return EntryOutcome(name, "not-fingerprinted", "no fingerprint taken before classification")
    try:
        result = claim(
            root_fd,
            name,
            expected,
            max_inodes=settings.max_inodes,
            max_depth=settings.max_depth,
            liveness_ok=lambda: _safe(facts, name),
        )
    except (ClaimRefused, ValueError) as exc:
        return EntryOutcome(name, "refused", str(exc))
    except ClaimStuck as exc:
        return EntryOutcome(name, "stuck", str(exc))
    if isinstance(result, RenamedBack):
        return EntryOutcome(name, "renamed-back", result.reason)
    try:
        after_step(STEP_CLAIM, name)
        return _archive_claimed(result, row, store, settings, after_step)
    finally:
        result.close()


def _archive_claimed(
    handle: Claimed,
    row: EntryRow,
    store: ArchiveStore,
    settings: ApplySettings,
    after_step: Callable[[str, str], None],
) -> EntryOutcome:
    name = handle.name
    try:
        packed = pack(
            handle,
            store,
            new_archive_id(),
            tar=settings.tar,
            max_inodes=settings.max_inodes,
            max_depth=settings.max_depth,
        )
    except (PackRefused, OSError) as exc:
        # An I/O error mid-pack renames back like a refusal; a partial archive it
        # leaves has no record, so the store audit reports it and nothing removes by it.
        try:
            back = release(handle, f"pack refused: {exc}")
        except ClaimStuck as stuck:
            return EntryOutcome(name, "stuck", str(stuck))
        return EntryOutcome(name, "renamed-back", back.reason)
    after_step(STEP_PACK, name)
    record = _record(row, packed, settings)
    try:
        store.append(record)
    except (StoreRefused, OSError) as exc:
        # The claim stays: the next run's resume finds no record and renames it back.
        return EntryOutcome(name, "left-claimed", f"record not appended: {exc}")
    after_step(STEP_APPEND, name)
    try:
        remove_claimed(
            handle.parent_fd,
            handle.claimed_name,
            store,
            record,
            tar=settings.tar,
            max_inodes=settings.max_inodes,
            max_depth=settings.max_depth,
            clock=settings.clock,
            retention_hours=settings.retention_hours,
            expected=handle.fingerprint,
        )
    except RemoveRefused as exc:
        return EntryOutcome(name, "left-claimed", str(exc), packed.archive_id)
    return EntryOutcome(name, "archived", "", packed.archive_id)


def _record(row: EntryRow, packed: PackResult, settings: ApplySettings) -> ArchiveRecord:
    verdict = row.verdict.value
    packed_at = settings.clock()
    expires_at = packed_at + timedelta(hours=settings.retention_hours[verdict])
    return ArchiveRecord(
        archive_id=packed.archive_id,
        original_path=str(PurePosixPath(settings.original_prefix) / row.name),
        checkout=settings.checkout,
        verdict=verdict,
        proof_ids=tuple(proof.value for proof in row.proofs),
        packed_at=packed_at.isoformat(),
        expires_at=expires_at.isoformat(),
        counts=dict(packed.counts),
        archive_size=packed.size,
        sha256=packed.sha256,
        skipped=packed.skipped,
        restore_command=RESTORE_COMMAND.format(archive_id=packed.archive_id),
    )


def _claim_present(root_fd: int, name: str) -> bool:
    try:
        os.stat(CLAIM_PREFIX + name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _expire(
    root_fd: int,
    store: ArchiveStore,
    facts: ApplyFacts,
    settings: ApplySettings,
    notes: list[str],
) -> tuple[ExpiryOutcome, ...]:
    """Expire due archives LAST; hold any whose entry is still claimed or still named.

    A record of another root cannot be checked from this one (neither its claim
    nor its references), so it is held.
    """
    prefix = PurePosixPath(settings.original_prefix)

    def still_referenced(records: tuple[ArchiveRecord, ...]) -> bool:
        for record in records:
            path = PurePosixPath(record.original_path)
            if path.parent != prefix:
                return True
            if _claim_present(root_fd, path.name) or facts.referenced(path.name):
                return True
        return False

    try:
        return expire_due(
            store,
            clock=settings.clock,
            retention_hours=settings.retention_hours,
            still_referenced=still_referenced,
        )
    except (ExpiryRefused, StoreRefused) as exc:
        notes.append(f"expiry did not run: {exc}")
        return ()
