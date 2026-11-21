"""Plan 00627 Task 5.1: a Bash command that creates a directory under scratch refreshes the inventory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use import scratch_inventory_refresher as module
from claude_code_hooks_daemon.handlers.post_tool_use.scratch_inventory_refresher import (
    ScratchInventoryRefresherHandler,
)


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    monkeypatch.setattr(module, "_start_refresh", calls.append)
    return calls


def _bash(command: str, cwd: Path) -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }


def _handler(root: Path) -> ScratchInventoryRefresherHandler:
    handler = ScratchInventoryRefresherHandler()
    handler.project_root_override = root
    return handler


def test_priority_and_non_terminal() -> None:
    handler = ScratchInventoryRefresherHandler()
    assert handler.priority == Priority.SCRATCH_INVENTORY_REFRESHER
    assert handler.terminal is False


def test_directory_under_scratch_refreshes(tmp_path: Path, started: list[Path]) -> None:
    handler = _handler(tmp_path)
    hook_input = _bash("mkdir -p untracked/scratch/probe", tmp_path)
    assert handler.matches(hook_input)
    result = handler.handle(hook_input)
    assert result.decision == Decision.ALLOW
    assert not result.context
    assert started == [tmp_path]


@pytest.mark.parametrize(
    "command",
    ["mkdir untracked/other", "echo x > untracked/scratch/f.txt", "cp a untracked/scratch/b"],
)
def test_other_commands_do_not_match(tmp_path: Path, command: str) -> None:
    assert not _handler(tmp_path).matches(_bash(command, tmp_path))


def test_file_tools_do_not_match(tmp_path: Path) -> None:
    hook_input = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "untracked/scratch/x/y.md")},
        "cwd": str(tmp_path),
    }
    assert not _handler(tmp_path).matches(hook_input)


def test_refresh_failure_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_root: Path) -> None:
        raise OSError("disk")

    monkeypatch.setattr("claude_code_hooks_daemon.daemon.cli.start_scratch_inventory_refresh", boom)
    handler = _handler(tmp_path)
    result = handler.handle(_bash("mkdir untracked/scratch/x", tmp_path))
    assert result.decision == Decision.ALLOW
