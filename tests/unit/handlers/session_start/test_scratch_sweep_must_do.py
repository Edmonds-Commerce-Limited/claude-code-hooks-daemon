"""The scratch sweep's must-do item (Plan 00627 Task 5.6, DESIGN section 10).

The item reaches the must-do list through ``session_actions_directive``, which
lists every SessionStart handler whose verifier is failing. It fails when an
entry is due or a cap is at warn or worse, and nowhere else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import ScratchCapsConfig
from claude_code_hooks_daemon.core.scratch_caps import CapLevel
from claude_code_hooks_daemon.core.scratch_inventory import (
    INVENTORY_FILE,
    Inventory,
    InventoryEntry,
    InventoryReading,
    write_inventory,
)
from claude_code_hooks_daemon.core.session_start_tiers import SessionTier, compute_tier
from claude_code_hooks_daemon.handlers.session_start import scratch_sweep as module
from claude_code_hooks_daemon.handlers.session_start.scratch_sweep import (
    ScratchSweepHandler,
    sweep_action_required,
)

NOW = 1_800_000_000.0


def _entry(name: str, verdict: str = "LIVE", *, due: bool = False) -> InventoryEntry:
    return InventoryEntry(name, verdict, 1, 1, 10, NOW - 60, due, "")


def _inv(*entries: InventoryEntry) -> Inventory:
    return Inventory(
        generated_at=NOW - 60,
        incomplete=False,
        incomplete_reasons=(),
        entries=entries,
        archives=(),
        cap_level=CapLevel.OK,
    )


def _caps(**values: object) -> ScratchCapsConfig:
    return ScratchCapsConfig.model_validate(values)


class TestPredicate:
    def test_clean_inventory_needs_nothing(self) -> None:
        reading = InventoryReading(_inv(_entry("a"), _entry("b", "KEPT")), "")
        assert sweep_action_required(reading, _caps()) is False

    def test_a_due_entry_needs_the_sweep(self) -> None:
        reading = InventoryReading(_inv(_entry("a", "THROWAWAY", due=True)), "")
        assert sweep_action_required(reading, _caps()) is True

    def test_a_cap_at_warn_needs_the_sweep(self) -> None:
        entries = tuple(_entry(f"e{i}") for i in range(5))
        caps = _caps(entries={"warn": 3, "block": 10})
        assert sweep_action_required(InventoryReading(_inv(*entries), ""), caps) is True

    def test_a_missing_inventory_is_not_a_must_do(self) -> None:
        assert sweep_action_required(InventoryReading(None, "missing"), _caps()) is False


class TestVerifier:
    @pytest.fixture
    def handler(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScratchSweepHandler:
        monkeypatch.setattr(ScratchSweepHandler, "_get_project_root", lambda self: tmp_path)
        monkeypatch.setattr(module, "_caps_config", lambda root: _caps())
        return ScratchSweepHandler()

    def test_due_entry_raises_the_handler_to_action_required(
        self, handler: ScratchSweepHandler, tmp_path: Path
    ) -> None:
        (tmp_path / "untracked").mkdir()
        write_inventory(
            tmp_path / "untracked" / INVENTORY_FILE, _inv(_entry("a", "THROWAWAY", due=True))
        )
        assert handler.verify_still_needed() is True
        assert compute_tier(handler) is SessionTier.ACTION_REQUIRED

    def test_no_inventory_leaves_the_handler_below_action_required(
        self, handler: ScratchSweepHandler
    ) -> None:
        assert handler.verify_still_needed() is False
        assert compute_tier(handler) is not SessionTier.ACTION_REQUIRED

    def test_the_verifier_writes_nothing(
        self, handler: ScratchSweepHandler, tmp_path: Path
    ) -> None:
        handler.verify_still_needed()
        assert list(tmp_path.iterdir()) == []
