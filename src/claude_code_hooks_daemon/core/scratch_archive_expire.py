"""Completeness, keep and expiry of stored archives (Plan 00627 Task 3.6).

DESIGN.md section 5.2 step 7: a later sweep removes an archive whose retention
has passed, after re-checking that no keep record or new reference covers it.

**Complete** is defined once, in :func:`complete_records`, and used by expiry,
keep and restore: the index has no torn tail, the id has at least one record,
every record of the id agrees on SHA-256 and size, and no ``expired`` event
names the id. Keep and restore refuse an id that is not complete.

**Effective expiry** of an archive is the latest of, over every record of its
id, ``expires_at`` and ``packed_at`` plus the verdict's retention, and the
``until`` of every keep of the id. A null ``expires_at``, a verdict with no
retention, or an instant that does not parse with a zone means it never
expires: every doubt holds the archive. One keep on any entry of a batch holds
the whole archive, because the entries share one file.

**Expiry order**, under the store lock: decide (clock, retention, keeps, the
caller's reference check; any exception holds the id) → ``lstat`` the archive
(a regular file, not a link) → append the ``expired`` event → ``lstat`` again
(same inode) → unlink → fsync the store. A crash after the event leaves an id
a rerun finishes; a crash before it leaves nothing changed. The one deletion
here is :func:`_unlink_expired`.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from claude_code_hooks_daemon.core.scratch_archive import (
    ArchiveRecord,
    ArchiveStore,
    EventsRead,
    ExpiredEvent,
    IndexRead,
    KeepEvent,
    archive_file_name,
    fsync_dir,
    parse_instant,
)

#: The longest keep reason, after its whitespace is collapsed.
MAX_KEEP_REASON_CHARS = 500

ExpiryKind = Literal["expired", "finished", "held", "absent"]


class Incomplete(Exception):
    """The id is not complete; nothing may act on it."""


class KeepRefused(Exception):
    """The keep was not recorded."""


class ExpiryRefused(Exception):
    """The expiry run did not start; nothing was changed."""


class _Hold(Exception):
    """This archive does not expire now."""


@dataclass(frozen=True)
class ExpiryOutcome:
    """What one expiry run did with one archive id, and why."""

    archive_id: str
    outcome: ExpiryKind
    reason: str


def records_of(index: IndexRead, archive_id: str) -> tuple[ArchiveRecord, ...]:
    """Every record of ``archive_id`` (a batch has one per file), in index order."""
    return tuple(r for r in index.records if r.archive_id == archive_id)


def expired_ids(events: EventsRead) -> frozenset[str]:
    """The ids an ``expired`` event names."""
    return frozenset(e.archive_id for e in events.events if isinstance(e, ExpiredEvent))


def complete_records(
    index: IndexRead, events: EventsRead, archive_id: str
) -> tuple[ArchiveRecord, ...]:
    """Return every record of a complete ``archive_id``; raise :class:`Incomplete`."""
    if index.torn_tail:
        raise Incomplete("the index has a torn final line; completeness is unknown")
    records = records_of(index, archive_id)
    if not records:
        raise Incomplete(f"archive {archive_id} has no record")
    if len({(r.sha256, r.archive_size) for r in records}) != 1:
        raise Incomplete(f"the records of archive {archive_id} disagree on SHA-256 or size")
    if archive_id in expired_ids(events):
        raise Incomplete(f"archive {archive_id} is expired")
    return records


def normalise_reason(reason: str) -> str:
    """Collapse whitespace and case, so a reason cannot be repeated by respacing it."""
    return " ".join(reason.split()).casefold()


def _aware(value: datetime, what: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{what} has no zone")
    return value


def _keeps(events: EventsRead, archive_id: str) -> list[KeepEvent]:
    return [e for e in events.events if isinstance(e, KeepEvent) and e.archive_id == archive_id]


def effective_expiry(
    records: tuple[ArchiveRecord, ...],
    keeps: list[KeepEvent],
    retention_hours: Mapping[str, float],
) -> datetime:
    """The instant the archive may expire; raise :class:`_Hold` when it never does."""
    instants: list[datetime] = []
    for record in records:
        if record.expires_at is None:
            raise _Hold(f"{record.original_path!r} never expires (null expires_at)")
        hours = retention_hours.get(record.verdict)
        if hours is None:
            raise _Hold(f"verdict {record.verdict!r} has no retention; it never expires here")
        try:
            instants.append(parse_instant(record.expires_at))
            instants.append(parse_instant(record.packed_at) + timedelta(hours=hours))
        except ValueError as exc:
            raise _Hold(f"an instant of {record.original_path!r} does not parse: {exc}") from exc
    instants.extend(parse_instant(k.until) for k in keeps)
    return max(instants)


def keep(
    store: ArchiveStore,
    archive_id: str,
    *,
    reason: str,
    until: datetime,
    now: datetime,
    max_hours: float,
    max_keeps: int,
    retention_hours: Mapping[str, float],
    entry: str | None = None,
) -> KeepEvent:
    """Record a bounded, reasoned pause of ``archive_id``'s expiry; raise :class:`KeepRefused`.

    ``until`` must lie after ``now``, within ``max_hours`` of it, and after the
    archive's effective expiry, so every keep extends it. A reason repeated in
    another spacing or case, or a keep past ``max_keeps``, is refused. A batch
    archive's keep names its ``entry`` (an ``original_path``) and holds the
    whole archive. A torn events tail is cut by this keep's append.
    """
    store.require_lock("keep")
    try:
        _aware(now, "now")
        _aware(until, "until")
    except ValueError as exc:
        raise KeepRefused(str(exc)) from exc
    text = " ".join(reason.split())
    if not text or len(text) > MAX_KEEP_REASON_CHARS:
        raise KeepRefused(f"a keep reason must have 1 to {MAX_KEEP_REASON_CHARS} characters")
    events = store.read_events()
    try:
        records = complete_records(store.read_index(), events, archive_id)
    except Incomplete as exc:
        raise KeepRefused(str(exc)) from exc
    record = _select(records, entry)
    if until <= now:
        raise KeepRefused("a keep's until must lie in the future")
    if max_hours <= 0 or until > now + timedelta(hours=max_hours):
        raise KeepRefused(f"a keep's until is out of bound ({max_hours} hours from now)")
    keeps = _keeps(events, archive_id)
    if len(keeps) >= max_keeps:
        raise KeepRefused(f"archive {archive_id} is at its cap of {max_keeps} keeps")
    if normalise_reason(text) in {normalise_reason(k.reason) for k in keeps}:
        raise KeepRefused("that reason repeats an earlier keep of this archive")
    try:
        current = effective_expiry(records, keeps, retention_hours)
    except _Hold as exc:
        raise KeepRefused(f"cannot be extended: {exc}") from exc
    except ValueError as exc:
        raise KeepRefused(f"an earlier keep does not parse: {exc}") from exc
    if until <= current:
        raise KeepRefused(f"until does not extend the expiry ({current.isoformat()})")
    event = KeepEvent(
        archive_id=archive_id,
        original_path=record.original_path,
        reason=text,
        kept_at=now.isoformat(),
        until=until.isoformat(),
    )
    store.append_event(event)
    return event


def _select(records: tuple[ArchiveRecord, ...], entry: str | None) -> ArchiveRecord:
    if entry is None:
        if len(records) != 1:
            raise KeepRefused("this archive holds several entries; name the entry")
        return records[0]
    for record in records:
        if record.original_path == entry:
            return record
    raise KeepRefused(f"the archive holds no entry {entry!r}")


def _lstat_archive(store: ArchiveStore, archive_id: str) -> os.stat_result | None:
    try:
        return os.lstat(archive_file_name(archive_id), dir_fd=store.dir_fd)
    except FileNotFoundError:
        return None


def _unlink_expired(store: ArchiveStore, archive_id: str, expected: os.stat_result) -> bool:
    """Unlink the archive if it is still the regular file ``expected`` saw; return whether it was."""
    name = archive_file_name(archive_id)
    try:
        info = os.lstat(name, dir_fd=store.dir_fd)
    except FileNotFoundError:
        return False
    same = (info.st_ino, info.st_dev) == (expected.st_ino, expected.st_dev)
    if not same or not stat.S_ISREG(info.st_mode):
        return False
    os.unlink(name, dir_fd=store.dir_fd)
    fsync_dir(store.dir_fd)
    return True


def _decide(
    records: tuple[ArchiveRecord, ...],
    keeps: list[KeepEvent],
    *,
    clock: Callable[[], datetime],
    retention_hours: Mapping[str, float],
    still_referenced: Callable[[tuple[ArchiveRecord, ...]], bool],
) -> datetime:
    """Return ``now`` when the archive is due; raise on any doubt."""
    now = _aware(clock(), "the clock's instant")
    due = effective_expiry(records, keeps, retention_hours)
    if now < due:
        raise _Hold(f"not due until {due.isoformat()}")
    if still_referenced(records):
        raise _Hold("referenced")
    return now


def expire_due(
    store: ArchiveStore,
    *,
    clock: Callable[[], datetime],
    retention_hours: Mapping[str, float],
    still_referenced: Callable[[tuple[ArchiveRecord, ...]], bool],
) -> tuple[ExpiryOutcome, ...]:
    """Delete every complete archive past its effective expiry; one outcome per id.

    ``still_referenced`` is the caller's fresh reference check (a tracked file
    naming the entry); ``True`` or an exception holds the id, as does an
    exception or a zone-less instant from ``clock``. A torn index or events
    tail raises :class:`ExpiryRefused` before anything changes. An id with an
    ``expired`` event whose archive is still present is finished.
    """
    store.require_lock("expire")
    index = store.read_index()
    events = store.read_events()
    if index.torn_tail or events.torn_tail:
        raise ExpiryRefused("the index or events file has a torn final line; nothing expires")
    done = expired_ids(events)
    outcomes: list[ExpiryOutcome] = []
    for archive_id in dict.fromkeys(r.archive_id for r in index.records):
        outcomes.append(
            _expire_one(
                store,
                index,
                events,
                archive_id,
                finishing=archive_id in done,
                clock=clock,
                retention_hours=retention_hours,
                still_referenced=still_referenced,
            )
        )
    return tuple(outcomes)


def _expire_one(
    store: ArchiveStore,
    index: IndexRead,
    events: EventsRead,
    archive_id: str,
    *,
    finishing: bool,
    clock: Callable[[], datetime],
    retention_hours: Mapping[str, float],
    still_referenced: Callable[[tuple[ArchiveRecord, ...]], bool],
) -> ExpiryOutcome:
    now: datetime | None = None
    if not finishing:
        try:
            records = complete_records(index, events, archive_id)
            now = _decide(
                records,
                _keeps(events, archive_id),
                clock=clock,
                retention_hours=retention_hours,
                still_referenced=still_referenced,
            )
        except Exception as exc:  # every doubt, the caller's included, holds the archive
            return ExpiryOutcome(archive_id, "held", str(exc))
    info = _lstat_archive(store, archive_id)
    if info is None:
        return ExpiryOutcome(archive_id, "absent", "no archive file")
    if not stat.S_ISREG(info.st_mode):
        return ExpiryOutcome(archive_id, "held", "the archive name is not a regular file")
    if now is not None:
        store.append_event(ExpiredEvent(archive_id=archive_id, at=now.isoformat()))
    if not _unlink_expired(store, archive_id, info):
        return ExpiryOutcome(archive_id, "held", "the archive changed; a rerun finishes it")
    return ExpiryOutcome(archive_id, "finished" if finishing else "expired", "")
