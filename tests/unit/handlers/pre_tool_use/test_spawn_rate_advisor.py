"""Tests for SpawnRateAdvisorHandler (Plan 00471 Task 2.4, levers L4 and L5, advisory only)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.handlers.pre_tool_use.spawn_rate_advisor import (
    SpawnRateAdvisorHandler,
)
from claude_code_hooks_daemon.utils.session_load import live_snapshot_path, record_background_tasks
from claude_code_hooks_daemon.utils.spend_ledger import read_events

SESSION = "s1"


def agent(
    directory: Path, name: str, *, stopped: bool = False, age: float = 5, context: int = 100_000
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    agent_id = f"a{name}-0123456789abcdef"
    record = {
        "type": "assistant",
        "message": {
            "model": "m",
            "stop_reason": "end_turn" if stopped else "tool_use",
            "usage": {"cache_read_input_tokens": context},
        },
    }
    path = directory / f"agent-{agent_id}.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    (directory / f"agent-{agent_id}.meta.json").write_text(json.dumps({"name": name}))
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))


@pytest.fixture
def subagents(tmp_path: Path) -> Path:
    return tmp_path / "projects" / SESSION / "subagents"


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    return tmp_path / "untracked"


@pytest.fixture
def handler(untracked: Path) -> SpawnRateAdvisorHandler:
    instance = SpawnRateAdvisorHandler()
    instance._untracked_override = untracked
    instance._max_concurrent = 4
    instance._advise_pct = 70
    return instance


def call(
    tmp_path: Path, tool: str = "Agent", tool_input: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "session_id": SESSION,
        "transcript_path": str(tmp_path / "projects" / f"{SESSION}.jsonl"),
        "tool_name": tool,
        "tool_input": tool_input if tool_input is not None else {"prompt": "x", "name": "new"},
    }


_LATEST_USAGE = "claude_code_hooks_daemon.handlers.pre_tool_use.spawn_rate_advisor.latest_usage"


@pytest.fixture(autouse=True)
def no_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """No usage reading unless a test sets one: never the host's real snapshot."""
    monkeypatch.setattr(_LATEST_USAGE, lambda **_: None)


def usage(monkeypatch: pytest.MonkeyPatch, pct: float, *, age: float = 10) -> None:
    """The daemon's shared usage snapshot, as the controller fills it from rate_limits."""
    now = time.time()
    window = UsageWindow(used_percentage=pct, resets_at=int(now + 3600), observed_at=now - age)
    snapshot = UsageSnapshot(five_hour=window, seven_day=None)
    monkeypatch.setattr(_LATEST_USAGE, lambda **_: snapshot)


class TestShape:
    def test_shipped_defaults(self) -> None:
        instance = SpawnRateAdvisorHandler()
        assert instance._max_concurrent is None
        assert instance._advise_pct == 80
        assert instance._liveness_seconds == 120

    def test_matches_spawns_and_messages(self, handler, tmp_path) -> None:
        assert handler.matches(call(tmp_path))
        assert handler.matches(call(tmp_path, "Task"))
        assert handler.matches(call(tmp_path, "SendMessage", {"to": "x", "message": "y"}))
        assert not handler.matches(call(tmp_path, "Bash", {"command": "ls"}))

    def test_off_when_both_levers_are_off(self, handler, tmp_path) -> None:
        handler._max_concurrent = None
        handler._advise_pct = None
        assert not handler.matches(call(tmp_path))


class TestConcurrency:
    def test_silent_below_the_cap(self, handler, tmp_path, subagents) -> None:
        for name in ("w1", "w2", "w3"):
            agent(subagents, name)
        result = handler.handle(call(tmp_path))
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_names_the_live_agents_at_the_cap(
        self, handler, tmp_path, subagents, untracked
    ) -> None:
        for name in ("w1", "w2", "w3", "w4"):
            agent(subagents, name)
        agent(subagents, "finished", stopped=True)
        agent(subagents, "quiet", age=600)
        result = handler.handle(call(tmp_path))
        assert result.decision == Decision.ALLOW
        advice = "\n".join(result.context)
        assert "4 agents are live" in advice
        assert all(name in advice for name in ("w1", "w2", "w3", "w4"))
        assert "finished" not in advice and "quiet" not in advice
        assert read_events(untracked, SESSION)[-1]["kind"] == "concurrency-advisory"

    def test_reconciled_by_a_stop_payload(self, handler, tmp_path, subagents, untracked) -> None:
        for name in ("w1", "w2", "w3", "w4"):
            agent(subagents, name)
        record_background_tasks(
            untracked,
            SESSION,
            [{"id": "t", "type": "teammate", "status": "completed", "description": "w4"}],
        )
        assert not handler.handle(call(tmp_path)).context

    def test_writes_the_live_snapshot(self, handler, tmp_path, subagents, untracked) -> None:
        agent(subagents, "w1", context=321_000)
        handler.handle(call(tmp_path))
        snapshot = json.loads(live_snapshot_path(untracked, SESSION).read_text())
        assert snapshot["count"] == 1
        assert snapshot["largest_context"] == 321_000

    def test_message_to_a_running_agent_is_not_judged(self, handler, tmp_path, subagents) -> None:
        for name in ("w1", "w2", "w3", "w4"):
            agent(subagents, name)
        result = handler.handle(call(tmp_path, "SendMessage", {"to": "w1", "message": "hi"}))
        assert not result.context

    def test_cold_resume_counts_as_a_spawn(self, handler, tmp_path, subagents) -> None:
        for name in ("w1", "w2", "w3", "w4"):
            agent(subagents, name)
        agent(subagents, "old", stopped=True, age=3600)
        result = handler.handle(call(tmp_path, "SendMessage", {"to": "old", "message": "NEW TASK"}))
        assert "4 agents are live" in "\n".join(result.context)

    def test_a_usage_free_target_is_not_a_cold_resume(self, handler, tmp_path, subagents) -> None:
        """Review B2: a target with no usage in its tail cap is unknown, not a crash."""
        for name in ("w1", "w2", "w3", "w4"):
            agent(subagents, name)
        agent(subagents, "old", stopped=True, age=3600)
        transcript = subagents / "agent-aold-0123456789abcdef.jsonl"
        line = json.dumps({"type": "user", "message": {"content": "x" * 1000}}) + "\n"
        transcript.write_text(line * 1000, encoding="utf-8")
        result = handler.handle(call(tmp_path, "SendMessage", {"to": "old", "message": "NEW TASK"}))
        assert result.decision == Decision.ALLOW
        assert not result.context


class TestFiveHour:
    """Review S5: read from the daemon's shared usage snapshot, not the context sidecar."""

    def test_advises_at_the_threshold_with_the_reset_time(
        self, handler, tmp_path, monkeypatch
    ) -> None:
        usage(monkeypatch, 72.0)
        advice = "\n".join(handler.handle(call(tmp_path)).context)
        assert "72%" in advice
        assert "serialise" in advice.lower()
        assert "UTC" in advice

    def test_silent_below(self, handler, tmp_path, monkeypatch) -> None:
        usage(monkeypatch, 50.0)
        assert not handler.handle(call(tmp_path)).context

    def test_stale_reading_draws_nothing(self, handler, tmp_path, monkeypatch) -> None:
        usage(monkeypatch, 95.0, age=3600)
        assert not handler.handle(call(tmp_path)).context

    def test_no_reading_draws_nothing(self, handler, tmp_path) -> None:
        assert not handler.handle(call(tmp_path)).context

    def test_the_context_sidecar_is_not_read(self, handler, tmp_path, untracked) -> None:
        directory = untracked / "context-sidecar"
        directory.mkdir(parents=True)
        payload = {"ts": time.time(), "five_hour_pct": 95, "resets_at": time.time() + 3600}
        (directory / f"{SESSION}.json").write_text(json.dumps(payload), encoding="utf-8")
        assert not handler.handle(call(tmp_path)).context

    def test_never_denies(self, handler, tmp_path, subagents, monkeypatch) -> None:
        usage(monkeypatch, 99.0)
        for name in ("w1", "w2", "w3", "w4", "w5", "w6"):
            agent(subagents, name)
        assert handler.handle(call(tmp_path)).decision == Decision.ALLOW


def test_docs() -> None:
    instance = SpawnRateAdvisorHandler()
    assert instance.get_claude_md() is None
    assert instance.get_acceptance_tests()
