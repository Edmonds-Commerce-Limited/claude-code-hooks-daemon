"""Tests for the live-agent count and the five-hour reading (Plan 00471 Task 2.4)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.session_load import (
    LiveAgent,
    finished_agents,
    live_agents,
    model_family,
    read_live_snapshot,
    record_background_tasks,
    refresh_live_snapshot,
    write_live_snapshot,
)

NOW = 1_800_000_000.0


def agent(
    directory: Path, agent_id: str, name: str, *, context: int, stopped: bool, age: float
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-5-5",
            "stop_reason": "end_turn" if stopped else "tool_use",
            "usage": {"cache_read_input_tokens": context},
        },
    }
    path = directory / f"agent-{agent_id}.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    if name:
        (directory / f"agent-{agent_id}.meta.json").write_text(json.dumps({"name": name}))
    os.utime(path, (NOW - age, NOW - age))


@pytest.fixture
def subagents(tmp_path: Path) -> Path:
    directory = tmp_path / "subagents"
    agent(
        directory, "aworker-1-0000000000000001", "worker-1", context=200_000, stopped=False, age=10
    )
    agent(
        directory, "aworker-2-0000000000000002", "worker-2", context=90_000, stopped=False, age=100
    )
    agent(directory, "adone-0000000000000003", "done", context=300_000, stopped=True, age=5)
    agent(directory, "aidle-0000000000000004", "idle", context=50_000, stopped=False, age=600)
    return directory


class TestLiveAgents:
    def test_counts_recent_and_unfinished_only(self, subagents: Path) -> None:
        live = live_agents(subagents, liveness_seconds=120, now=NOW)
        assert [entry.label for entry in live] == ["worker-1", "worker-2"]
        assert live[0] == LiveAgent(
            agent_id="aworker-1-0000000000000001",
            name="worker-1",
            context_tokens=200_000,
            idle_seconds=10,
            model="claude-opus-5-5",
        )

    def test_reconciled_against_finished_background_tasks(self, subagents: Path) -> None:
        live = live_agents(
            subagents, liveness_seconds=120, now=NOW, finished=frozenset({"worker-2"})
        )
        assert [entry.label for entry in live] == ["worker-1"]

    def test_missing_directory_is_empty(self, tmp_path: Path) -> None:
        assert live_agents(tmp_path / "absent", liveness_seconds=120, now=NOW) == []

    def test_unreadable_recent_transcript_counts_live_with_unknown_context(
        self, subagents: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(path: Path, **_: object) -> object:
            raise PermissionError(13, "Permission denied", str(path))

        monkeypatch.setattr("claude_code_hooks_daemon.utils.session_load.read_tail", refuse)
        live = live_agents(subagents, liveness_seconds=120, now=NOW)
        assert [entry.label for entry in live] == ["done", "worker-1", "worker-2"]
        assert all(entry.context_tokens == 0 and entry.model == "" for entry in live)

    def test_usage_free_recent_transcript_counts_live_with_unknown_context(
        self, subagents: Path
    ) -> None:
        """Review B2: a large transcript with no usage in its tail is unknown, not dropped."""
        path = subagents / "agent-adone-0000000000000003.jsonl"
        line = json.dumps({"type": "user", "message": {"content": "x" * 1000}}) + "\n"
        path.write_text(line * 1000, encoding="utf-8")
        os.utime(path, (NOW - 5, NOW - 5))
        live = live_agents(subagents, liveness_seconds=120, now=NOW)
        assert [entry.label for entry in live] == ["done", "worker-1", "worker-2"]
        assert live[0].context_tokens == 0


class TestBackgroundTasks:
    def test_finished_subagent_and_teammate_tasks(self, tmp_path: Path) -> None:
        record_background_tasks(
            tmp_path,
            "s1",
            [
                {"id": "a1", "type": "teammate", "status": "completed", "description": "worker-2"},
                {"id": "a2", "type": "subagent", "status": "running", "description": "worker-1"},
                {"id": "t1", "type": "shell", "status": "completed", "description": "tail"},
                "junk",
            ],
        )
        assert finished_agents(tmp_path, "s1") == frozenset({"a1", "worker-2"})

    def test_absent_list_is_unknown_and_records_nothing(self, tmp_path: Path) -> None:
        record_background_tasks(tmp_path, "s1", None)
        assert finished_agents(tmp_path, "s1") == frozenset()


class TestLiveSnapshot:
    def test_round_trip(self, tmp_path: Path, subagents: Path) -> None:
        live = live_agents(subagents, liveness_seconds=120, now=NOW)
        path = write_live_snapshot(tmp_path, "s1", live)
        snapshot = read_live_snapshot(path)
        assert snapshot["count"] == 2
        assert snapshot["largest_context"] == 200_000
        assert snapshot["agents"] == ["worker-1", "worker-2"]
        assert snapshot["families"] == {"opus": 2}
        assert snapshot["unmeasured"] == 0

    def test_refresh_from_either_transcript_shape(self, tmp_path: Path) -> None:
        subagents = tmp_path / "projects" / "s1" / "subagents"
        agent(subagents, "aw-0000000000000009", "w", context=10, stopped=False, age=0)
        os.utime(subagents / "agent-aw-0000000000000009.jsonl")
        main = str(tmp_path / "projects" / "s1.jsonl")
        own = str(subagents / "agent-aw-0000000000000009.jsonl")
        for transcript_path in (main, own):
            path = refresh_live_snapshot(tmp_path, "s1", transcript_path)
            assert path is not None
            assert read_live_snapshot(path)["count"] == 1
        assert refresh_live_snapshot(tmp_path, "s1", "") is None

    @pytest.mark.parametrize(
        ("model", "family"),
        [
            ("claude-opus-5-5", "opus"),
            ("claude-sonnet-5-5", "sonnet"),
            ("claude-haiku-5-5", "haiku"),
            ("claude-fable-5-1", "fable"),
            # Plan 00472 Task 3.7: the shared rank table, so an alias counts too.
            ("claude-mythos-1-0", "fable"),
            ("gpt", "other"),
            ("", "other"),
        ],
    )
    def test_model_family(self, model: str, family: str) -> None:
        assert model_family(model) == family
