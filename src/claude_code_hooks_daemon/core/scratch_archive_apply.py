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

import dataclasses
import logging
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
    fingerprint_of,
    open_dir,
    release,
    walk_tree,
)
from claude_code_hooks_daemon.core.scratch_archive_expire import (
    ExpiryOutcome,
    ExpiryRefused,
    expire_due,
    expired_ids,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    PackRefused,
    PackResult,
    TarTool,
    pack,
    refuse_foreign_owner,
)
from claude_code_hooks_daemon.core.scratch_archive_remove import (
    RemoveRefused,
    Resumed,
    record_claim,
    remove_claimed,
    resume_claimed,
)
from claude_code_hooks_daemon.core.scratch_archive_restore import Reclaimed, reclaim_staging
from claude_code_hooks_daemon.core.scratch_session import (
    is_session_dir_name,
    remove_empty_session_dir,
)
from claude_code_hooks_daemon.core.scratch_sweep import EntryRow, SweepReport
from claude_code_hooks_daemon.core.scratch_verdict import KEEP_MARKER, Verdict
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

_LOG = logging.getLogger(__name__)

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
    #: A session directory empty this long after its last recorded birth is removed; None: never.
    empty_session_hours: float | None = None
    #: ``(st_dev, st_ino)`` the root must have when opened; None: not checked (a top-level root).
    expected_identity: tuple[int, int] | None = None


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
    if settings.expected_identity is not None:
        info = os.fstat(root_fd)
        if (info.st_dev, info.st_ino) != settings.expected_identity:
            os.close(root_fd)
            # Checked before any reclaim or resume: nothing in a swapped directory is touched.
            return acted_on_nothing(
                store, f"{settings.root.name} is not the directory that was listed"
            )
    try:
        reclaimed = reclaim_staging(store, max_depth=settings.max_depth)
        resumed = tuple(
            _resume(root_fd, name, store, settings)
            for name in bounded_names(root_fd, settings.max_inodes)
            if name.startswith(CLAIM_PREFIX)
        )
        # Listed again: a claim renamed back above is an entry to judge this run.
        names = bounded_names(root_fd, settings.max_inodes)
        fingerprints, foreign = _fingerprint_all(root_fd, names, settings)
        report = _same_directory(root_fd, facts.classify())
        entries = [
            (
                foreign[row.name]
                if row.name in foreign and report.complete and _actionable(row)
                else _apply_row(
                    root_fd, row, report, fingerprints, store, facts, settings, after_step
                )
            )
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


def acted_on_nothing(store: ArchiveStore, reason: str) -> ApplyResult:
    """An incomplete result for a root no step touched."""
    return ApplyResult(
        complete=False,
        incomplete_reasons=(reason,),
        reclaimed=(),
        resumed=(),
        entries=(),
        expired=(),
        unfinished_adoptions=(),
        audit=store.audit(),
        notes=(),
    )


def _same_directory(root_fd: int, report: SweepReport) -> SweepReport:
    """``report`` made incomplete when it listed a directory other than the one ``root_fd`` holds.

    A session sub-report records the identity it listed; the root opened here by
    path may have been swapped since, so nothing acts unless the two agree.
    """
    if report.identity is None:
        return report
    info = os.fstat(root_fd)
    if (info.st_dev, info.st_ino) == report.identity:
        return report
    reason = f"{Path(report.root).name} is not the directory that was listed: nothing acted on"
    return dataclasses.replace(
        report, complete=False, incomplete_reasons=(*report.incomplete_reasons, reason)
    )


def session_facts(
    parent: ApplyFacts,
    session: str,
    *,
    session_dir: Path,
    child_live: Callable[[str], bool],
    child_referenced: Callable[[str], bool],
    container_referenced: Callable[[], bool],
) -> ApplyFacts:
    """Fresh facts for one session directory's children, read through the parent's.

    The classification is the parent's fresh one, narrowed to ``session``'s
    sub-report; a session no longer listed gives an incomplete empty report, so
    nothing acts. A child is held as live when it, or the session directory in
    the parent root, is, or when ``session_dir`` holds a keep marker now
    (:func:`_session_kept`); referenced when it is, or when anything names the
    container (``container_referenced``: the parent's root sites or an unknown
    reference set).
    """

    def classify() -> SweepReport:
        report = parent.classify()
        found = [sub for sub in report.sessions if Path(sub.root).name == session]
        if len(found) == 1 and report.complete:
            return found[0]
        reason = f"session directory {session} is not listed by a complete fresh classification"
        return SweepReport(session, (), False, (reason,), ())

    return ApplyFacts(
        classify=classify,
        entry_live=lambda name: (
            _session_kept(session_dir) or child_live(name) or parent.entry_live(session)
        ),
        referenced=lambda name: container_referenced() or child_referenced(name),
    )


def _session_kept(session_dir: Path) -> bool:
    """True when the session holds a ``.scratch-keep`` now, or that cannot be read (fail closed).

    Read again at apply time: a marker added after the classification still
    holds every child. Any ``lstat`` failure but "absent" counts as kept, and a
    link counts like the file.
    """
    try:
        os.lstat(session_dir / KEEP_MARKER)
    except FileNotFoundError:
        return False
    except OSError as exc:
        _LOG.warning("%s: keep marker unreadable (%s), read as kept", session_dir, exc)
    return True


def apply_sessions(
    store: ArchiveStore,
    facts: ApplyFacts,
    settings: ApplySettings,
    for_session: Callable[[str], ApplyFacts],
    *,
    after_step: Callable[[str, str], None] = _no_step,
) -> tuple[tuple[str, ApplyResult], ...]:
    """One apply pass per session directory a fresh ``facts`` classification lists.

    Run after the root's own pass with the same lock held. Each session
    directory is a root of its own whose entries are its children; the
    directory itself is never an entry here. ``for_session(name)`` supplies
    the facts (normally :func:`session_facts`).
    """
    store.require_lock("apply")
    listed = [(Path(sub.root).name, sub.identity) for sub in facts.classify().sessions]
    results: list[tuple[str, ApplyResult]] = []
    for name, identity in listed:
        if not is_session_dir_name(name):
            continue
        if identity is None:
            results.append((name, acted_on_nothing(store, f"{name}: no identity was recorded")))
            continue
        sub_settings = dataclasses.replace(
            settings,
            root=settings.root / name,
            original_prefix=f"{settings.original_prefix}/{name}",
            expected_identity=identity,
        )
        try:
            result = apply_sweep(store, for_session(name), sub_settings, after_step=after_step)
        except OSError as exc:
            # One session that cannot be opened (gone, or a link) never stops the others.
            reason = f"{name} could not be opened: {type(exc).__name__}"
            results.append((name, acted_on_nothing(store, reason)))
            continue
        removal = _remove_if_empty(store, facts, settings, name) if result.complete else ""
        if removal:
            result = dataclasses.replace(result, notes=(*result.notes, removal))
        results.append((name, result))
    return tuple(results)


def _remove_if_empty(
    store: ArchiveStore, facts: ApplyFacts, settings: ApplySettings, name: str
) -> str:
    """Step 4: remove session directory ``name`` when it is empty and old; a note, or "".

    Held while the directory is live in the root, or while any live (not
    expired) archive record names a path inside it: its restore needs the
    directory to exist.
    """
    if settings.empty_session_hours is None:
        return ""
    inside = f"{settings.original_prefix}/{name}/"
    born_before = settings.clock().timestamp() - settings.empty_session_hours * 3600

    def held() -> bool:
        if facts.entry_live(name):
            return True
        gone = expired_ids(store.read_events())
        return any(
            record.original_path.startswith(inside) and record.archive_id not in gone
            for record in store.read_index().records
        )

    try:
        root_fd = open_dir(settings.root)
    except OSError as exc:
        return f"session directory {name} kept: root could not be opened ({type(exc).__name__})"
    try:
        reason = remove_empty_session_dir(root_fd, name, born_before=born_before, held=held)
    except (OSError, StoreRefused) as exc:
        reason = f"removal failed: {type(exc).__name__}"
    finally:
        os.close(root_fd)
    if not reason:
        return f"session directory {name} removed: empty and old"
    if reason in _ROUTINE_KEEPS:
        return ""
    return f"session directory {name} kept: {reason}"


#: Why a session directory normally stays; not worth a note on every run.
_ROUTINE_KEEPS = frozenset({"not empty", "a recent session or child birth"})


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
) -> tuple[dict[str, Fingerprint], dict[str, EntryOutcome]]:
    """Each unclaimed entry's fingerprint, and the entries refused before any claim.

    An entry that cannot be walked is left out. One holding an inode another
    user owns is refused here, so no claim is recorded and no rename is made
    for it run after run; pack refuses it again in case ownership changes later.
    """
    prints: dict[str, Fingerprint] = {}
    foreign: dict[str, EntryOutcome] = {}
    for name in names:
        if name.startswith(CLAIM_PREFIX):
            continue
        try:
            listing = walk_tree(
                root_fd, name, max_inodes=settings.max_inodes, max_depth=settings.max_depth
            )
            refuse_foreign_owner(listing, name)
            prints[name] = fingerprint_of(listing)
        except PackRefused as exc:
            foreign[name] = EntryOutcome(name, "refused", str(exc))
        except (WalkRefused, OSError) as exc:
            log_and_continue(
                _LOG,
                exc,
                reason=f"{name!r} cannot be walked, so it is left out and never claimed",
            )
    return prints, foreign


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
    archive_id = new_archive_id()
    try:
        # Recorded before the rename, so a leftover claim with no record is not ours.
        record_claim(
            store,
            expected,
            parent_fd=root_fd,
            name=name,
            archive_id=archive_id,
            original_path=str(PurePosixPath(settings.original_prefix) / name),
            checkout=settings.checkout,
            at=settings.clock(),
        )
    except (StoreRefused, OSError, ValueError) as exc:
        return EntryOutcome(name, "refused", f"claim not recorded: {exc}")
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
        return _archive_claimed(result, archive_id, row, store, settings, after_step)
    finally:
        result.close()


def _archive_claimed(
    handle: Claimed,
    archive_id: str,
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
            archive_id,
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
