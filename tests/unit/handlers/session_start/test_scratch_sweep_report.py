"""Tests for the scratch_sweep SessionStart report from the cached inventory (Plan 00627 Task 5.2)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import ScratchCapsConfig
from claude_code_hooks_daemon.core.scratch_caps import CapLevel
from claude_code_hooks_daemon.core.scratch_inventory import (
    Inventory,
    InventoryArchive,
    InventoryEntry,
    InventoryReading,
    write_inventory,
)
from claude_code_hooks_daemon.handlers.session_start import scratch_sweep as module
from claude_code_hooks_daemon.handlers.session_start.scratch_sweep import (
    ScratchSweepHandler,
    render_inventory_report,
)

NOW = 1_800_000_000.0


def _entry(
    name: str, verdict: str = "LIVE", *, due: bool = False, filing: str = ""
) -> InventoryEntry:
    return InventoryEntry(name, verdict, 1, 1, 10, NOW - 60, due, filing)


def _inv(
    *entries: InventoryEntry,
    incomplete: bool = False,
    archives: tuple[InventoryArchive, ...] = (),
    age: float = 60.0,
) -> Inventory:
    return Inventory(
        generated_at=NOW - age,
        incomplete=incomplete,
        incomplete_reasons=("budget spent",) if incomplete else (),
        entries=entries,
        archives=archives,
        cap_level=CapLevel.OK,
    )


def _render(reading: InventoryReading, **caps: object) -> list[str]:
    return render_inventory_report(reading, ScratchCapsConfig.model_validate(caps), now=NOW)


def test_clean_inventory_is_silent() -> None:
    assert _render(InventoryReading(_inv(_entry("a"), _entry("b", "KEPT")), "")) == []


def test_missing_inventory_is_never_silent() -> None:
    lines = _render(InventoryReading(None, "missing"))
    assert lines and "inventory" in lines[0].lower() and "missing" in lines[0]


def test_incomplete_inventory_is_never_silent() -> None:
    text = "\n".join(_render(InventoryReading(_inv(_entry("a"), incomplete=True), "")))
    assert "incomplete" in text and "budget spent" in text


def test_stale_inventory_says_so() -> None:
    text = "\n".join(_render(InventoryReading(_inv(age=3 * 86400.0), "")))
    assert "stale" in text


def test_counts_and_overdue_to_file_list() -> None:
    reading = InventoryReading(
        _inv(_entry("a", "DISPOSABLE", due=True, filing="mv a plan/x"), _entry("b", "LIVE")), ""
    )
    text = "\n".join(_render(reading))
    assert "DISPOSABLE 1" in text and "LIVE 1" in text
    assert "a" in text and "mv a plan/x" in text


def test_expiring_archive_names_its_restore_command() -> None:
    soon = InventoryArchive(
        "A1", ("untracked/scratch/x",), NOW + 3600, "hooks-daemon scratch-sweep restore A1"
    )
    later = InventoryArchive("A2", ("y",), NOW + 30 * 86400, "restore A2")
    text = "\n".join(_render(InventoryReading(_inv(archives=(soon, later)), "")))
    assert "restore A1" in text and "A2" not in text


def test_caps_at_warn_are_reported() -> None:
    text = "\n".join(
        _render(
            InventoryReading(_inv(_entry("a"), _entry("b")), ""), entries={"warn": 2, "block": 5}
        )
    )
    assert "entries" in text and "WARN" in text


def test_handler_starts_a_refresh_and_appends_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[Path] = []
    monkeypatch.setattr(module, "_start_refresh", lambda root: started.append(root))
    handler = ScratchSweepHandler()
    monkeypatch.setattr(handler, "_get_project_root", lambda: tmp_path)
    write_inventory(
        tmp_path / "untracked" / "scratch-inventory.json",
        _inv(_entry("a", "DISPOSABLE", due=True, filing="mv a b"), age=1.0),
    )
    monkeypatch.setattr(time, "time", lambda: NOW)
    hook: dict[str, Any] = {"session_id": "0123456789abcdef", "cwd": str(tmp_path)}
    context = handler.handle(hook).context
    assert started == [tmp_path]
    assert any("mv a b" in line for line in context)
