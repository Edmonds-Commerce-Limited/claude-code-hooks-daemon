"""Tests for the shared spend-ledger store (Plan 00471 Task 2.1)."""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.daemon.verdict_log import VERDICT_LOG_FILENAME
from claude_code_hooks_daemon.utils.spend_ledger import (
    AgentMeta,
    append_event,
    note_unmeasured,
    read_agent_meta,
    read_events,
    session_dir,
    spend_cache,
    unmeasured_count,
)


class TestSessionDir:
    def test_session_id_is_sanitised(self, tmp_path: Path) -> None:
        assert session_dir(tmp_path, "../x").parent == tmp_path / "spend-ledger"
        assert session_dir(tmp_path, "").name == "unknown"


class TestUnmeasured:
    def test_one_record_per_agent_and_reason(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        first = note_unmeasured(
            tmp_path,
            session_id="s1",
            agent_id="a1",
            reason="transcript-missing",
            handler="subagent-context-budget",
            tool_name="Bash",
            log_dir=log_dir,
        )
        again = [
            note_unmeasured(
                tmp_path,
                session_id="s1",
                agent_id="a1",
                reason="transcript-missing",
                handler="subagent-context-budget",
                tool_name="Bash",
                log_dir=log_dir,
            )
            for _ in range(5)
        ]
        other_reason = note_unmeasured(
            tmp_path,
            session_id="s1",
            agent_id="a1",
            reason="transcript-unreadable",
            handler="subagent-context-budget",
            tool_name="Bash",
            log_dir=log_dir,
        )
        assert first is True
        assert again == [False] * 5
        assert other_reason is True
        assert unmeasured_count(tmp_path, "s1") == 2
        lines = [
            json.loads(line) for line in (log_dir / VERDICT_LOG_FILENAME).read_text().splitlines()
        ]
        assert [line["verdict"] for line in lines] == ["unmeasured", "unmeasured"]
        assert lines[0]["handler"] == "subagent-context-budget"
        assert lines[0]["detail"] == {"agent_id": "a1", "reason": "transcript-missing"}
        assert lines[0]["session"] == "s1"

    def test_count_of_unknown_session_is_zero(self, tmp_path: Path) -> None:
        assert unmeasured_count(tmp_path, "nobody") == 0


class TestEvents:
    def test_append_and_read(self, tmp_path: Path) -> None:
        append_event(tmp_path, "s1", {"kind": "budget-override", "agent": "x", "tokens": 400000})
        append_event(tmp_path, "s1", {"kind": "resume-override", "agent": "y"})
        events = read_events(tmp_path, "s1")
        assert [event["kind"] for event in events] == ["budget-override", "resume-override"]
        assert all("ts" in event for event in events)

    def test_corrupt_lines_are_skipped(self, tmp_path: Path) -> None:
        append_event(tmp_path, "s1", {"kind": "a"})
        with (session_dir(tmp_path, "s1") / "events.jsonl").open("a") as handle:
            handle.write("{broken\n[1]\n")
        assert len(read_events(tmp_path, "s1")) == 1

    def test_missing_is_empty(self, tmp_path: Path) -> None:
        assert read_events(tmp_path, "s1") == []


class TestAgentMeta:
    def test_reads_the_sibling_meta_file(self, tmp_path: Path) -> None:
        transcript = tmp_path / "agent-ax-1.jsonl"
        (tmp_path / "agent-ax-1.meta.json").write_text(
            json.dumps({"name": "p471-x", "spawnedAgentType": "python-developer", "model": "opus"})
        )
        assert read_agent_meta(transcript) == AgentMeta(
            name="p471-x", agent_type="python-developer", model="opus"
        )

    def test_missing_or_corrupt_is_empty(self, tmp_path: Path) -> None:
        assert read_agent_meta(tmp_path / "agent-a.jsonl") == AgentMeta()
        (tmp_path / "agent-b.meta.json").write_text("{bad")
        assert read_agent_meta(tmp_path / "agent-b.jsonl") == AgentMeta()


class TestSpendCache:
    def test_one_cache_per_directory(self, tmp_path: Path) -> None:
        assert spend_cache(tmp_path) is spend_cache(tmp_path)
        assert spend_cache(None) is spend_cache(None)
        assert spend_cache(tmp_path) is not spend_cache(tmp_path / "other")
