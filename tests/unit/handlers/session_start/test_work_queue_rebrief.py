"""WorkQueueRebriefHandler: re-brief the durable work queue on resume/compact (Plan 00470 Task 3.3).

A resumed or compacted session has lost the in-context record of which agents it
dispatched. The queue file is the durable record; this lists what is still running,
with the exact respawn facts, and says plainly that nothing is respawned for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.work_queue_rebrief import (
    WorkQueueRebriefHandler,
)
from claude_code_hooks_daemon.utils.work_queue import STATUS_DONE, add_record, update_record

_NOW = 7_000_000.0


class _Handler(WorkQueueRebriefHandler):
    """The handler with a fixed clock and a queue file under ``tmp_path``."""

    def __init__(self, queue: Path | None) -> None:
        super().__init__()
        self.queue = queue

    def _queue_path(self) -> Path | None:
        return self.queue

    def _now(self) -> float:
        return _NOW


def _start(source: str | None = "resume") -> dict[str, Any]:
    event: dict[str, Any] = {"hook_event_name": "SessionStart", "session_id": "s2"}
    if source is not None:
        event["source"] = source
    return event


def _queue_one(queue: Path, worktree: Path, name: str = "builder") -> None:
    add_record(
        queue,
        name,
        worktree=str(worktree),
        branch="worktree-builder",
        brief="Implement the thing.",
        brief_file=None,
        last_sha="abc1234",
        now=_NOW - 7200,
    )


def _context(result: Any) -> str:
    return "\n".join(result.context or [])


class TestIdentity:
    def test_it_is_wired_to_the_constants(self) -> None:
        handler = WorkQueueRebriefHandler()
        assert handler.name == HandlerID.WORK_QUEUE_REBRIEF.display_name
        assert handler.priority == Priority.WORK_QUEUE_REBRIEF
        assert handler.config_key == "work_queue_rebrief"

    def test_it_is_a_non_terminal_advisory_on_by_default(self) -> None:
        handler = WorkQueueRebriefHandler()
        assert handler.terminal is False
        assert handler.get_default_enabled() is True


class TestMatching:
    @pytest.mark.parametrize("source", ["resume", "compact"])
    def test_a_resumed_or_compacted_session_with_running_work_matches(
        self, tmp_path: Path, source: str
    ) -> None:
        queue = tmp_path / "q.json"
        _queue_one(queue, tmp_path)
        assert _Handler(queue).matches(_start(source)) is True

    @pytest.mark.parametrize("source", ["startup", "clear", None])
    def test_other_sources_do_not_match(self, tmp_path: Path, source: str | None) -> None:
        queue = tmp_path / "q.json"
        _queue_one(queue, tmp_path)
        assert _Handler(queue).matches(_start(source)) is False

    def test_an_empty_or_missing_queue_does_not_match(self, tmp_path: Path) -> None:
        assert _Handler(tmp_path / "none.json").matches(_start()) is False
        assert _Handler(None).matches(_start()) is False

    def test_a_queue_with_only_closed_records_does_not_match(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.json"
        _queue_one(queue, tmp_path)
        update_record(queue, "builder", now=_NOW, status=STATUS_DONE)
        assert _Handler(queue).matches(_start()) is False

    def test_an_unreadable_queue_matches_so_it_can_be_reported(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.json"
        queue.write_text("{oops", encoding="utf-8")
        assert _Handler(queue).matches(_start()) is True


class TestHandle:
    def test_it_lists_each_running_agent_with_its_respawn_facts(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.json"
        _queue_one(queue, tmp_path, "builder")
        _queue_one(queue, tmp_path, "reviewer")
        result = _Handler(queue).handle(_start())
        assert result.decision == Decision.ALLOW
        text = _context(result)
        assert "builder" in text
        assert "reviewer" in text
        assert "worktree-builder" in text
        assert "abc1234" in text
        assert "Implement the thing." in text

    def test_it_says_nothing_is_respawned(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.json"
        _queue_one(queue, tmp_path)
        assert "not respawned" in _context(_Handler(queue).handle(_start()))

    def test_an_unreadable_queue_is_reported(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.json"
        queue.write_text("{oops", encoding="utf-8")
        assert "WORK QUEUE UNREADABLE" in _context(_Handler(queue).handle(_start()))

    def test_it_never_denies(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.json"
        _queue_one(queue, tmp_path)
        assert _Handler(queue).handle(_start()).decision == Decision.ALLOW


class TestDocumentation:
    def test_it_has_no_resident_guidance(self) -> None:
        assert WorkQueueRebriefHandler().get_claude_md() is None

    def test_it_declares_an_acceptance_test(self) -> None:
        assert WorkQueueRebriefHandler().get_acceptance_tests()
