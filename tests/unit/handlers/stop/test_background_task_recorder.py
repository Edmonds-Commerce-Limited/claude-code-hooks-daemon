"""Tests for BackgroundTaskRecorderHandler (Plan 00471 Task 2.4: the live count's Stop reconciliation)."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.daemon.synthetic_traffic import MANUAL_PROBE, SYNTHETIC_SOURCE_FIELD
from claude_code_hooks_daemon.handlers.stop.background_task_recorder import (
    BackgroundTaskRecorderHandler,
)
from claude_code_hooks_daemon.utils.session_load import finished_agents


def make(tmp_path: Path) -> BackgroundTaskRecorderHandler:
    instance = BackgroundTaskRecorderHandler()
    instance._untracked_override = tmp_path
    return instance


def test_records_finished_agent_tasks_and_allows(tmp_path: Path) -> None:
    handler = make(tmp_path)
    stop = {
        "session_id": "s1",
        "background_tasks": [
            {"id": "t1", "type": "teammate", "status": "completed", "description": "w1"},
            {"id": "t2", "type": "teammate", "status": "running", "description": "w2"},
        ],
    }
    assert handler.matches(stop)
    assert handler.handle(stop).decision == Decision.ALLOW
    assert finished_agents(tmp_path, "s1") == frozenset({"t1", "w1"})


def test_absent_list_is_not_matched(tmp_path: Path) -> None:
    assert not make(tmp_path).matches({"session_id": "s1"})


def test_a_probe_is_not_recorded(tmp_path: Path) -> None:
    stop = {"session_id": "s1", "background_tasks": [], SYNTHETIC_SOURCE_FIELD: MANUAL_PROBE}
    assert not make(tmp_path).matches(stop)


def test_unwritable_store_still_allows(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    handler = make(blocker)
    stop = {
        "session_id": "s1",
        "background_tasks": [{"type": "teammate", "status": "completed", "id": "a"}],
    }
    assert handler.handle(stop).decision == Decision.ALLOW


def test_docs(tmp_path: Path) -> None:
    handler = make(tmp_path)
    assert handler.get_claude_md() is None
    assert handler.get_acceptance_tests()
