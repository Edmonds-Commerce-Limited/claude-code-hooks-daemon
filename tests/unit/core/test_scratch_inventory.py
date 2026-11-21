"""Tests for the cached scratch inventory (Plan 00627 Task 5.1)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from claude_code_hooks_daemon.config.models import ScratchCapsConfig
from claude_code_hooks_daemon.core.scratch_archive_status import ArchiveStatus, StoreStatus
from claude_code_hooks_daemon.core.scratch_caps import CapLevel
from claude_code_hooks_daemon.core.scratch_inventory import (
    Inventory,
    InventoryEntry,
    inventory_caps,
    inventory_counts,
    inventory_from_report,
    read_inventory,
    refresh_in_background,
    refresh_inventory,
    write_inventory,
)
from claude_code_hooks_daemon.core.scratch_sweep import EntryRow, SweepReport
from claude_code_hooks_daemon.core.scratch_verdict import RepositoryMarker, Verdict
from claude_code_hooks_daemon.core.scratch_walk import NodeKind

NOW = 1_800_000_000.0


def _row(
    name: str,
    verdict: Verdict = Verdict.DISPOSABLE,
    *,
    dirs: int = 1,
    due: bool = False,
    filing: str = "",
) -> EntryRow:
    return EntryRow(
        name=name,
        kind=NodeKind.DIRECTORY,
        verdict=verdict,
        reasons=(),
        proofs=(),
        repository=RepositoryMarker.NONE,
        git_markers=(),
        walk_complete=True,
        directories=dirs,
        files=2,
        bytes=100,
        age_hours=2.0,
        due=due,
        uncovered=(),
        uncovered_count=0,
        filing_command=filing,
    )


def _report(
    *rows: EntryRow, complete: bool = True, sessions: tuple[SweepReport, ...] = ()
) -> SweepReport:
    return SweepReport(
        root="untracked/scratch",
        rows=rows,
        complete=complete,
        incomplete_reasons=() if complete else ("budget spent",),
        notes=(),
        sessions=sessions,
    )


def _caps(**figures: object) -> ScratchCapsConfig:
    return ScratchCapsConfig.model_validate(figures)


def test_entries_carry_counts_newest_mtime_and_verdict_hint() -> None:
    inv = inventory_from_report(
        _report(_row("a", dirs=3, due=True, filing="mv x y")), now=NOW, caps=_caps(), previous=None
    )
    (entry,) = inv.entries
    assert (entry.name, entry.verdict, entry.directories, entry.files, entry.bytes) == (
        "a",
        "DISPOSABLE",
        3,
        2,
        100,
    )
    assert entry.newest_mtime == NOW - 2 * 3600
    assert entry.due and entry.filing_command == "mv x y"
    assert not inv.incomplete and inv.generated_at == NOW


def test_session_children_are_named_under_their_session_directory() -> None:
    session = SweepReport(
        root="untracked/scratch/s-1",
        rows=(_row("kid"),),
        complete=False,
        incomplete_reasons=("x",),
        notes=(),
    )
    inv = inventory_from_report(
        _report(_row("s-1"), sessions=(session,)), now=NOW, caps=_caps(), previous=None
    )
    assert [e.name for e in inv.entries] == ["s-1", "s-1/kid"]
    assert inv.incomplete


def test_counts_sum_every_entry() -> None:
    inv = inventory_from_report(
        _report(_row("a", dirs=3), _row("b", dirs=4)), now=NOW, caps=_caps(), previous=None
    )
    counts = inventory_counts(inv)
    assert (counts.directories, counts.bytes, counts.entries) == (7, 200, 2)


def test_cap_level_recorded_and_incomplete_can_only_raise() -> None:
    caps = _caps(entries={"warn": 1, "block": 5})
    warned = inventory_from_report(_report(_row("a")), now=NOW, caps=caps, previous=None)
    assert warned.cap_level is CapLevel.WARN
    incomplete = inventory_from_report(
        _report(complete=False), now=NOW, caps=caps, previous=CapLevel.BLOCK
    )
    assert incomplete.cap_level is CapLevel.BLOCK
    assert inventory_caps(incomplete, caps).level is CapLevel.BLOCK


def test_archives_with_an_expiry_are_recorded() -> None:
    when = datetime.fromtimestamp(NOW + 3600, UTC)
    store = StoreStatus(
        archives=(
            ArchiveStatus("A1", ("untracked/scratch/x",), "DISPOSABLE", when, "", 0, "restore A1"),
            ArchiveStatus("A2", ("y",), "KEPT", None, "kept", 1, "restore A2"),
        ),
        torn=False,
    )
    inv = inventory_from_report(_report(), now=NOW, caps=_caps(), previous=None, store=store)
    assert [(a.archive_id, a.expires_at, a.restore_command) for a in inv.archives] == [
        ("A1", NOW + 3600, "restore A1")
    ]


def test_write_is_atomic_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "untracked" / "scratch-inventory.json"
    inv = inventory_from_report(_report(_row("a")), now=NOW, caps=_caps(), previous=None)
    write_inventory(path, inv)
    assert [p.name for p in path.parent.iterdir()] == ["scratch-inventory.json"]
    reading = read_inventory(path)
    assert reading.problem == "" and reading.inventory == inv


def test_missing_and_malformed_files_are_problems_not_errors(tmp_path: Path) -> None:
    path = tmp_path / "inv.json"
    assert read_inventory(path).problem == "missing"
    path.write_text("{not json", encoding="utf-8")
    assert read_inventory(path).inventory is None
    assert read_inventory(path).problem.startswith("unreadable")
    path.write_text(json.dumps({"schema": 999}), encoding="utf-8")
    assert read_inventory(path).problem.startswith("unreadable")


def test_refresh_feeds_the_previous_level_forward(tmp_path: Path) -> None:
    path = tmp_path / "inv.json"
    caps = _caps(entries={"warn": 1, "block": 2})
    refresh_inventory(path, lambda: _report(_row("a"), _row("b")), now=NOW, caps=caps)
    second = refresh_inventory(path, lambda: _report(complete=False), now=NOW + 1, caps=caps)
    assert second.cap_level is CapLevel.BLOCK


def test_background_refresh_writes_and_never_raises(tmp_path: Path) -> None:
    path = tmp_path / "inv.json"
    thread = refresh_in_background(path, lambda: _report(_row("a")), caps=_caps())
    assert thread is not None
    thread.join(5)
    assert read_inventory(path).inventory is not None

    def boom() -> SweepReport:
        raise OSError("gone")

    failing = refresh_in_background(tmp_path / "other.json", boom, caps=_caps())
    assert failing is not None
    failing.join(5)
    assert read_inventory(tmp_path / "other.json").problem == "missing"


def test_a_second_refresh_while_one_runs_is_skipped(tmp_path: Path) -> None:
    gate = threading.Event()

    def slow() -> SweepReport:
        gate.wait(5)
        return _report()

    first = refresh_in_background(tmp_path / "inv.json", slow, caps=_caps())
    assert refresh_in_background(tmp_path / "inv.json", slow, caps=_caps()) is None
    gate.set()
    assert first is not None
    first.join(5)


def test_entries_are_inventory_entries() -> None:
    inv = inventory_from_report(_report(_row("a")), now=NOW, caps=_caps(), previous=None)
    assert isinstance(inv, Inventory)
    assert all(isinstance(entry, InventoryEntry) for entry in inv.entries)
