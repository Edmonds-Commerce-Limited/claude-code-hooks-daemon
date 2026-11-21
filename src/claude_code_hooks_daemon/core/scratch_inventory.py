"""The cached scratch inventory (Plan 00627 DESIGN.md section 8, Task 5.1).

One file, ``untracked/scratch-inventory.json``: per entry its directories,
files, bytes, newest mtime and verdict hint, plus whether the walk was
incomplete, when it was generated, the last cap level (which feeds
``previous`` so an incomplete inventory can only raise a cap verdict) and the
archives that carry an expiry. It is built from a ``scratch_sweep`` report,
never from a second walk, and written atomically. A hook only ever reads it;
the refresh runs in a background thread.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import ScratchCapsConfig
from claude_code_hooks_daemon.core.scratch_caps import CapCounts, CapLevel, CapReport, evaluate_caps
from claude_code_hooks_daemon.core.scratch_store_view import StoreStatus
from claude_code_hooks_daemon.core.scratch_sweep import SweepReport
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

INVENTORY_FILE = "scratch-inventory.json"
SCHEMA = 1

_REFRESH_LOCK = threading.Lock()


@dataclass(frozen=True)
class InventoryEntry:
    """One entry as the sweep last saw it; session children are ``<session>/<name>``."""

    name: str
    verdict: str
    directories: int
    files: int
    bytes: int
    newest_mtime: float
    due: bool
    filing_command: str


@dataclass(frozen=True)
class InventoryArchive:
    """One archive that will expire, and the command that restores it."""

    archive_id: str
    original_paths: tuple[str, ...]
    expires_at: float
    restore_command: str


@dataclass(frozen=True)
class Inventory:
    """The whole cached inventory."""

    generated_at: float
    incomplete: bool
    incomplete_reasons: tuple[str, ...]
    entries: tuple[InventoryEntry, ...]
    archives: tuple[InventoryArchive, ...]
    cap_level: CapLevel


@dataclass(frozen=True)
class InventoryReading:
    """A read of the file: ``problem`` is "" when ``inventory`` is usable."""

    inventory: Inventory | None
    problem: str


def _entries(report: SweepReport, now: float, prefix: str = "") -> list[InventoryEntry]:
    return [
        InventoryEntry(
            name=f"{prefix}{row.name}",
            verdict=row.verdict.value,
            directories=row.directories,
            files=row.files,
            bytes=row.bytes,
            newest_mtime=now - row.age_hours * 3600.0,
            due=row.due,
            filing_command=row.filing_command,
        )
        for row in report.rows
    ]


def _counts(entries: tuple[InventoryEntry, ...]) -> CapCounts:
    return CapCounts(
        directories=sum(entry.directories for entry in entries),
        bytes=sum(entry.bytes for entry in entries),
        entries=len(entries),
    )


def inventory_from_report(
    report: SweepReport,
    *,
    now: float,
    caps: ScratchCapsConfig,
    previous: CapLevel | None,
    store: StoreStatus | None = None,
) -> Inventory:
    """Build the inventory from one sweep report (and the store's status, when read)."""
    entries = _entries(report, now)
    reasons = list(report.incomplete_reasons)
    incomplete = not report.complete
    for session in report.sessions:
        entries.extend(_entries(session, now, prefix=f"{Path(session.root).name}/"))
        incomplete = incomplete or not session.complete
        reasons.extend(session.incomplete_reasons)
    archives = tuple(
        InventoryArchive(
            archive_id=status.archive_id,
            original_paths=status.original_paths,
            expires_at=status.expires.timestamp(),
            restore_command=status.restore_command,
        )
        for status in (store.archives if store is not None else ())
        if status.expires is not None
    )
    if store is not None and store.torn:
        incomplete = True
        reasons.append("the archive store's index or events file has a torn tail")
    frozen = tuple(entries)
    level = evaluate_caps(_counts(frozen), caps, incomplete=incomplete, previous=previous).level
    return Inventory(
        generated_at=now,
        incomplete=incomplete,
        incomplete_reasons=tuple(reasons),
        entries=frozen,
        archives=archives,
        cap_level=level,
    )


def inventory_counts(inventory: Inventory) -> CapCounts:
    """The totals the caps are evaluated against."""
    return _counts(inventory.entries)


def inventory_caps(inventory: Inventory, caps: ScratchCapsConfig) -> CapReport:
    """Evaluate the caps from the cached file, the recorded level as ``previous``."""
    return evaluate_caps(
        inventory_counts(inventory),
        caps,
        incomplete=inventory.incomplete,
        previous=inventory.cap_level,
    )


def write_inventory(path: Path, inventory: Inventory) -> None:
    """Write atomically: a temp file in the same directory, then ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = asdict(inventory)
    body["cap_level"] = int(inventory.cap_level)
    body["schema"] = SCHEMA
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle, sort_keys=True)
        Path(temp).replace(path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _parse(body: Any) -> Inventory:
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        raise ValueError("unknown schema")
    return Inventory(
        generated_at=float(body["generated_at"]),
        incomplete=bool(body["incomplete"]),
        incomplete_reasons=tuple(str(reason) for reason in body["incomplete_reasons"]),
        entries=tuple(InventoryEntry(**entry) for entry in body["entries"]),
        archives=tuple(
            InventoryArchive(**{**item, "original_paths": tuple(item["original_paths"])})
            for item in body["archives"]
        ),
        cap_level=CapLevel(int(body["cap_level"])),
    )


def read_inventory(path: Path) -> InventoryReading:
    """Read the cached file; a missing or malformed one is a problem, never an error."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return InventoryReading(None, "missing")
    except OSError as exc:
        return InventoryReading(None, f"unreadable: {type(exc).__name__}")
    try:
        return InventoryReading(_parse(json.loads(text)), "")
    except (ValueError, KeyError, TypeError) as exc:
        return InventoryReading(None, f"unreadable: {type(exc).__name__}: {exc}")


def refresh_inventory(
    path: Path,
    classify: Callable[[], SweepReport],
    *,
    now: float,
    caps: ScratchCapsConfig,
    store: Callable[[], StoreStatus] | None = None,
) -> Inventory:
    """Classify, build and write; the file's own last level is fed forward as ``previous``."""
    prior = read_inventory(path).inventory
    inventory = inventory_from_report(
        classify(),
        now=now,
        caps=caps,
        previous=prior.cap_level if prior is not None else None,
        store=store() if store is not None else None,
    )
    write_inventory(path, inventory)
    return inventory


def refresh_in_background(
    path: Path,
    classify: Callable[[], SweepReport],
    *,
    caps: ScratchCapsConfig,
    store: Callable[[], StoreStatus] | None = None,
    clock: Callable[[], float] = time.time,
) -> threading.Thread | None:
    """Start one refresh in a daemon thread; ``None`` when a refresh is already running."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        return None

    def run() -> None:
        try:
            refresh_inventory(path, classify, now=clock(), caps=caps, store=store)
        except Exception as exc:
            log_and_continue(
                logger,
                exc,
                reason="scratch inventory refresh failed in its background thread; "
                "the cached file is unchanged",
                level=logging.ERROR,
            )
        finally:
            _REFRESH_LOCK.release()

    thread = threading.Thread(target=run, name="scratch-inventory-refresh", daemon=True)
    try:
        thread.start()
    except RuntimeError:
        _REFRESH_LOCK.release()
        raise
    return thread
