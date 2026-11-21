"""Tests for scratch_cap_guard (Plan 00627 Task 5.4, R-SCRATCH-CAP)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pytest

from claude_code_hooks_daemon.config.models import ScratchCapsConfig, ScratchThresholdConfig
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.scratch_caps import CapLevel
from claude_code_hooks_daemon.core.scratch_inventory import (
    INVENTORY_FILE,
    Inventory,
    InventoryEntry,
    write_inventory,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.scratch_cap_guard import (
    ScratchCapGuardHandler,
)


def _entry(name: str, verdict: str, directories: int, *, due: bool = False) -> InventoryEntry:
    return InventoryEntry(
        name=name,
        verdict=verdict,
        directories=directories,
        files=0,
        bytes=0,
        newest_mtime=0.0,
        due=due,
        filing_command="",
    )


def _write(root: Path, *entries: InventoryEntry) -> None:
    (root / "untracked" / "scratch").mkdir(parents=True, exist_ok=True)
    write_inventory(
        root / "untracked" / INVENTORY_FILE,
        Inventory(
            generated_at=0.0,
            incomplete=False,
            incomplete_reasons=(),
            entries=tuple(entries),
            archives=(),
            cap_level=CapLevel.OK,
        ),
    )


def _handler(
    root: Path, mode: Literal["block", "advise", "off"] = "block"
) -> ScratchCapGuardHandler:
    handler = ScratchCapGuardHandler()
    handler.project_root_override = root
    handler.caps_override = ScratchCapsConfig(
        directories=ScratchThresholdConfig(warn=50, block=100), mode=mode
    )
    return handler


def _bash(command: str, root: Path) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(root),
    }


MKDIR = "mkdir -p untracked/scratch/new-entry/deep"


def test_denies_directory_creation_at_block(tmp_path: Path) -> None:
    _write(tmp_path, _entry("big-clone", "EXPIRED", 90, due=True), _entry("b", "OPEN", 20))
    handler = _handler(tmp_path)
    assert handler.matches(_bash(MKDIR, tmp_path))
    result = handler.handle(_bash(MKDIR, tmp_path))
    assert result.decision == Decision.DENY
    assert result.reason is not None
    assert f"[{RuleID.SCRATCH_CAP}]" in result.reason
    assert "big-clone" in result.reason
    assert "scratch-sweep --apply" in result.reason


@pytest.mark.parametrize(
    "command",
    [
        "git clone https://example.invalid/r.git untracked/scratch/r",
        "tar -xf a.tar -C untracked/scratch/x",
        "cp -r src untracked/scratch/copy",
    ],
)
def test_other_directory_creators_denied(tmp_path: Path, command: str) -> None:
    _write(tmp_path, _entry("a", "EXPIRED", 200, due=True))
    assert _handler(tmp_path).handle(_bash(command, tmp_path)).decision == Decision.DENY


@pytest.mark.parametrize(
    "command",
    [
        "echo body > untracked/scratch/notes.txt",
        "cat > untracked/scratch/journal.md <<'EOF'\nmkdir untracked/scratch/x\nEOF",
        "mkdir -p untracked/elsewhere/x",
    ],
)
def test_file_writes_and_other_paths_never_match(tmp_path: Path, command: str) -> None:
    _write(tmp_path, _entry("a", "EXPIRED", 200, due=True))
    assert not _handler(tmp_path).matches(_bash(command, tmp_path))


def test_write_tool_never_matches(tmp_path: Path) -> None:
    _write(tmp_path, _entry("a", "EXPIRED", 200, due=True))
    hook_input = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "untracked/scratch/f.md"), "content": "x"},
    }
    assert not _handler(tmp_path).matches(hook_input)


def test_below_block_allows_silently(tmp_path: Path) -> None:
    _write(tmp_path, _entry("a", "EXPIRED", 60, due=True))
    result = _handler(tmp_path).handle(_bash(MKDIR, tmp_path))
    assert result.decision == Decision.ALLOW
    assert not result.context


def test_missing_inventory_allows(tmp_path: Path) -> None:
    result = _handler(tmp_path).handle(_bash(MKDIR, tmp_path))
    assert result.decision == Decision.ALLOW


def test_advise_mode_allows_with_advisory(tmp_path: Path) -> None:
    _write(tmp_path, _entry("a", "EXPIRED", 200, due=True))
    result = _handler(tmp_path, mode="advise").handle(_bash(MKDIR, tmp_path))
    assert result.decision == Decision.ALLOW
    assert any(RuleID.SCRATCH_CAP in line for line in result.context)


def test_never_stranded_downgrades_to_advisory(tmp_path: Path) -> None:
    _write(
        tmp_path,
        _entry("pinned", "KEPT", 60),
        _entry("running", "LIVE", 30),
        _entry("held", "PROTECTED", 15),
        _entry("small", "OPEN", 5),
    )
    result = _handler(tmp_path).handle(_bash(MKDIR, tmp_path))
    assert result.decision == Decision.ALLOW
    text = "\n".join(result.context)
    assert "pinned" in text and "running" in text and "held" in text


def test_sweepable_entries_still_over_block_deny(tmp_path: Path) -> None:
    _write(tmp_path, _entry("pinned", "KEPT", 60), _entry("old", "OPEN", 100))
    assert _handler(tmp_path).handle(_bash(MKDIR, tmp_path)).decision == Decision.DENY


def test_rule_and_guidance(tmp_path: Path) -> None:
    handler = _handler(tmp_path)
    assert [rule.rule_id for rule in handler.get_rules()] == [RuleID.SCRATCH_CAP]
    assert "R-SCRATCH-CAP" in (handler.get_claude_md() or "")
    assert handler.get_acceptance_tests()
