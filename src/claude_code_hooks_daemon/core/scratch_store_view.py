"""The read-only view of an archive store's status (Plan 00627 Task 3.10).

Pure value types with no behaviour and no daemon imports. They live apart from
the archive modules so the cached scratch inventory, which handlers import,
can carry a store's status without importing anything that can delete; only
the ``scratch-sweep`` CLI builds one, by reading the store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
    #: The checkout(s) each record was packed from: a reaped worktree's for an evacuation.
    checkouts: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoreStatus:
    """Every live archive, and whether the index or events file had a torn tail."""

    archives: tuple[ArchiveStatus, ...]
    torn: bool
