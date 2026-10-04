"""The durable work queue: one record per dispatched agent (Plan 00470 Task 3.3)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.work_queue import (
    MAX_BRIEF_CHARS,
    SCHEMA_VERSION,
    STATUS_ABANDONED,
    STATUS_DONE,
    STATUS_RUNNING,
    WORK_QUEUE_FILENAME,
    WorkQueueError,
    active_records,
    add_record,
    default_queue_path,
    queue_briefing,
    read_queue,
    render_rebrief,
    update_record,
)

_NOW = 1_000_000.0


@pytest.fixture
def queue(tmp_path: Path) -> Path:
    return tmp_path / WORK_QUEUE_FILENAME


def _add(
    queue: Path,
    name: str = "p470-queue",
    *,
    worktree: str = "/repo/worktrees/p470-queue",
    brief: str = "Build the queue.",
    brief_file: str | None = None,
    last_sha: str = "abc1234",
    now: float = _NOW,
) -> None:
    add_record(
        queue,
        name,
        worktree=worktree,
        branch="worktree-p470-queue",
        brief=brief,
        brief_file=brief_file,
        last_sha=last_sha,
        now=now,
    )


class TestPath:
    def test_no_project_context_means_no_path(self) -> None:
        ProjectContext.reset()
        assert default_queue_path() is None

    def test_the_file_sits_in_the_daemon_untracked_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(ProjectContext, "is_initialized", staticmethod(lambda: True))
        monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", staticmethod(lambda: tmp_path))
        assert default_queue_path() == tmp_path / WORK_QUEUE_FILENAME


class TestAdd:
    def test_a_record_holds_what_a_respawn_needs(self, queue: Path) -> None:
        _add(queue)
        (record,) = read_queue(queue)
        assert record.name == "p470-queue"
        assert record.worktree == "/repo/worktrees/p470-queue"
        assert record.branch == "worktree-p470-queue"
        assert record.brief == "Build the queue."
        assert record.last_sha == "abc1234"
        assert record.status == STATUS_RUNNING
        assert record.created_at == _NOW
        assert record.updated_at == _NOW

    def test_the_file_carries_a_schema_version(self, queue: Path) -> None:
        _add(queue)
        assert json.loads(queue.read_text(encoding="utf-8"))["version"] == SCHEMA_VERSION

    def test_the_file_is_owner_only(self, queue: Path) -> None:
        _add(queue)
        assert queue.stat().st_mode & 0o077 == 0

    def test_adding_a_name_again_re_dispatches_it(self, queue: Path) -> None:
        _add(queue)
        update_record(queue, "p470-queue", now=_NOW + 5, status=STATUS_DONE)
        _add(queue, brief="Second attempt.", now=_NOW + 10)
        (record,) = read_queue(queue)
        assert record.status == STATUS_RUNNING
        assert record.brief == "Second attempt."
        assert record.created_at == _NOW
        assert record.updated_at == _NOW + 10

    @pytest.mark.parametrize("name", ["", "   "])
    def test_a_blank_name_is_refused(self, queue: Path, name: str) -> None:
        with pytest.raises(WorkQueueError, match="name"):
            _add(queue, name=name)

    def test_a_blank_worktree_is_refused(self, queue: Path) -> None:
        with pytest.raises(WorkQueueError, match="worktree"):
            _add(queue, worktree=" ")

    def test_a_brief_is_required_inline_or_by_file(self, queue: Path) -> None:
        with pytest.raises(WorkQueueError, match="brief"):
            _add(queue, brief="", brief_file=None)

    def test_a_brief_file_alone_is_enough(self, queue: Path) -> None:
        _add(queue, brief="", brief_file="/repo/untracked/briefs/p470.md")
        (record,) = read_queue(queue)
        assert record.brief_file == "/repo/untracked/briefs/p470.md"

    def test_an_oversized_inline_brief_is_refused_not_cut(self, queue: Path) -> None:
        with pytest.raises(WorkQueueError, match="brief-file"):
            _add(queue, brief="x" * (MAX_BRIEF_CHARS + 1))
        assert not queue.exists()


class TestUpdate:
    def test_the_last_sha_and_status_move(self, queue: Path) -> None:
        _add(queue)
        update_record(queue, "p470-queue", now=_NOW + 60, last_sha="def5678")
        update_record(queue, "p470-queue", now=_NOW + 120, status=STATUS_ABANDONED)
        (record,) = read_queue(queue)
        assert record.last_sha == "def5678"
        assert record.status == STATUS_ABANDONED
        assert record.updated_at == _NOW + 120
        assert record.created_at == _NOW

    def test_a_field_left_out_is_left_alone(self, queue: Path) -> None:
        _add(queue)
        update_record(queue, "p470-queue", now=_NOW + 1)
        (record,) = read_queue(queue)
        assert (record.last_sha, record.status, record.brief) == (
            "abc1234",
            STATUS_RUNNING,
            "Build the queue.",
        )

    def test_an_unknown_name_is_refused(self, queue: Path) -> None:
        _add(queue)
        with pytest.raises(WorkQueueError, match="no-such"):
            update_record(queue, "no-such", now=_NOW, status=STATUS_DONE)

    def test_an_unknown_status_is_refused(self, queue: Path) -> None:
        _add(queue)
        with pytest.raises(WorkQueueError, match="status"):
            update_record(queue, "p470-queue", now=_NOW, status="finished")

    def test_concurrent_writers_lose_no_record(self, queue: Path) -> None:
        threads = [threading.Thread(target=_add, args=(queue, f"agent-{n}")) for n in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert {r.name for r in read_queue(queue)} == {f"agent-{n}" for n in range(12)}


class TestRead:
    def test_a_missing_file_is_an_empty_queue(self, queue: Path) -> None:
        assert read_queue(queue) == []

    def test_a_corrupt_file_is_an_error_not_an_empty_queue(self, queue: Path) -> None:
        queue.write_text("{not json", encoding="utf-8")
        with pytest.raises(WorkQueueError, match="unreadable"):
            read_queue(queue)

    def test_a_writer_never_overwrites_a_corrupt_file(self, queue: Path) -> None:
        queue.write_text("{not json", encoding="utf-8")
        with pytest.raises(WorkQueueError):
            _add(queue)
        assert queue.read_text(encoding="utf-8") == "{not json"

    def test_a_newer_schema_is_refused(self, queue: Path) -> None:
        queue.write_text(json.dumps({"version": SCHEMA_VERSION + 1, "records": []}))
        with pytest.raises(WorkQueueError, match="version"):
            read_queue(queue)

    def test_a_malformed_record_is_an_error(self, queue: Path) -> None:
        queue.write_text(json.dumps({"version": SCHEMA_VERSION, "records": [{"name": "x"}]}))
        with pytest.raises(WorkQueueError, match="record"):
            read_queue(queue)

    def test_only_running_records_are_active(self, queue: Path) -> None:
        _add(queue, "a")
        _add(queue, "b")
        _add(queue, "c")
        update_record(queue, "b", now=_NOW, status=STATUS_DONE)
        update_record(queue, "c", now=_NOW, status=STATUS_ABANDONED)
        assert [r.name for r in active_records(read_queue(queue))] == ["a"]


def _rendered(queue: Path, *, now: float = _NOW) -> str:
    return "\n".join(render_rebrief(active_records(read_queue(queue)), now=now))


class TestRender:
    def test_each_running_agent_gets_the_exact_respawn_facts(
        self, queue: Path, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "wt"
        worktree.mkdir()
        _add(queue, worktree=str(worktree))
        text = _rendered(queue, now=_NOW + 3600)
        assert "p470-queue" in text
        assert str(worktree) in text
        assert "worktree-p470-queue" in text
        assert "abc1234" in text
        assert "Build the queue." in text
        assert "1h" in text
        assert "MISSING" not in text

    def test_it_says_it_is_advisory(self, queue: Path) -> None:
        _add(queue)
        assert "not respawned" in _rendered(queue)

    def test_a_vanished_worktree_is_flagged(self, queue: Path, tmp_path: Path) -> None:
        _add(queue, worktree=str(tmp_path / "gone"))
        assert "MISSING" in _rendered(queue)

    def test_a_brief_file_is_named_not_inlined(self, queue: Path) -> None:
        _add(queue, brief="", brief_file="/repo/untracked/briefs/p470.md")
        assert "/repo/untracked/briefs/p470.md" in _rendered(queue)

    def test_a_long_brief_is_clipped_in_the_listing(self, queue: Path) -> None:
        _add(queue, brief="y" * 3000)
        text = _rendered(queue)
        assert "y" * 3000 not in text
        assert "work-queue list --json" in text

    def test_no_active_record_renders_nothing(self) -> None:
        assert render_rebrief([], now=_NOW) == []


class TestQueueBriefing:
    def test_no_path_and_no_file_are_silent(self, queue: Path) -> None:
        assert queue_briefing(None, now=_NOW) == []
        assert queue_briefing(queue, now=_NOW) == []

    def test_running_records_are_briefed(self, queue: Path) -> None:
        _add(queue)
        assert "p470-queue" in "\n".join(queue_briefing(queue, now=_NOW))

    def test_an_all_closed_queue_is_silent(self, queue: Path) -> None:
        _add(queue)
        update_record(queue, "p470-queue", now=_NOW, status=STATUS_DONE)
        assert queue_briefing(queue, now=_NOW) == []

    def test_an_unreadable_queue_says_so(self, queue: Path) -> None:
        queue.write_text("{oops", encoding="utf-8")
        lines = queue_briefing(queue, now=_NOW)
        assert lines[0] == "WORK QUEUE UNREADABLE"
        assert "unreadable" in "\n".join(lines)
