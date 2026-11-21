"""``scratch-sweep status``: the live archives and when each expires (Plan 00627 Task 3.10).

Read-only by construction: the store is opened with ``create=False`` (an absent
store raises :class:`StoreAbsent` and nothing is made), no lock is taken (the
index and events are append-only and a torn final line is dropped by the
reader), and nothing is written. The expiry shown is the expiry module's own
:func:`expiry_or_hold`, so a keep extends it here exactly as it does for expiry.

An archive is **live** when no ``expired`` event names it. A live id whose
records fail :func:`complete_records` is still listed, with the reason and no
expiry, because expiry holds it too.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from claude_code_hooks_daemon.core.scratch_archive import ArchiveStore
from claude_code_hooks_daemon.core.scratch_archive_expire import (
    Incomplete,
    complete_records,
    expired_ids,
    expiry_or_hold,
    keeps_of,
    records_of,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveStatus:
    """One live archive: its paths, verdict, effective expiry and why it is held."""

    archive_id: str
    original_paths: tuple[str, ...]
    verdict: str
    expires: datetime | None
    note: str
    keeps: int
    restore_command: str


@dataclass(frozen=True)
class StoreStatus:
    """Every live archive, and whether the index or events file had a torn tail."""

    archives: tuple[ArchiveStatus, ...]
    torn: bool


def read_status(path: Path, retention_hours: Mapping[str, float]) -> StoreStatus:
    """Read the store at ``path`` without creating or locking it."""
    with ArchiveStore.open(path, create=False) as store:
        index = store.read_index()
        events = store.read_events()
    gone = expired_ids(events)
    order: list[str] = []
    for record in index.records:
        if record.archive_id not in gone and record.archive_id not in order:
            order.append(record.archive_id)
    rows = []
    for archive_id in order:
        records = records_of(index, archive_id)
        keeps = keeps_of(events, archive_id)
        try:
            complete_records(index, events, archive_id)
        except Incomplete as exc:
            log_and_continue(
                logger,
                exc,
                reason="an incomplete archive is listed with its reason and no expiry; expiry holds it too",
                level=logging.INFO,
            )
            expires, note = None, str(exc)
        else:
            expires, note = expiry_or_hold(records, keeps, retention_hours)
        rows.append(
            ArchiveStatus(
                archive_id=archive_id,
                original_paths=tuple(r.original_path for r in records),
                verdict="/".join(sorted({r.verdict for r in records})),
                expires=expires,
                note=note,
                keeps=len(keeps),
                restore_command=records[0].restore_command,
            )
        )
    return StoreStatus(archives=tuple(rows), torn=index.torn_tail or events.torn_tail)


def render_status(status: StoreStatus, *, now: datetime) -> list[str]:
    """The human table: one block per archive, expiry with keeps applied."""
    lines: list[str] = []
    if status.torn:
        lines.append(
            "scratch-sweep status: the index or events file has a torn final line; "
            "nothing expires until a locked sweep repairs it"
        )
    if not status.archives:
        lines.append("scratch-sweep status: no live archives")
        return lines
    lines.append(f"scratch-sweep status: {len(status.archives)} live archive(s)")
    for row in status.archives:
        if row.expires is None:
            when = f"held: {row.note}"
        elif row.expires <= now:
            when = f"expires {row.expires.isoformat()} (due now)"
        else:
            when = f"expires {row.expires.isoformat()}"
        kept = f", {row.keeps} keep(s)" if row.keeps else ""
        lines.append(f"  {row.archive_id}  {row.verdict}  {when}{kept}")
        lines.extend(f"      {path}" for path in row.original_paths)
        lines.append(f"      restore: {row.restore_command}")
    return lines
