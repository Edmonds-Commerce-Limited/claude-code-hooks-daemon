"""Tests for the shared spend-ledger store (Plan 00471 Task 2.1)."""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.daemon.verdict_log import VERDICT_LOG_FILENAME
from claude_code_hooks_daemon.utils.spend_ledger import (
    AgentMeta,
    append_event,
    merge_dispatch_row,
    note_unmeasured,
    read_agent_meta,
    read_dispatch_rows,
    read_events,
    session_dir,
    spend_cache,
    unmeasured_count,
    write_dispatch_row,
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


class TestOffsetStore:
    def test_offsets_live_outside_the_per_session_ledger(self, tmp_path: Path) -> None:
        """Review S6: the session directories are pruned whole, so the offsets are not one."""
        from claude_code_hooks_daemon.utils.spend_ledger import spend_cache

        transcript = tmp_path / "agent-ax.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")
        spend_cache(tmp_path).totals(transcript)
        assert [path.parent.name for path in tmp_path.rglob("*.json")] == ["spend-offsets"]


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


class TestDispatchRows:
    """Plan 00472 Task 3.3: one row per dispatch, keyed by tool_use_id."""

    def test_write_then_merge_the_post_tool_use_fields(self, tmp_path: Path) -> None:
        write_dispatch_row(tmp_path, "s1", "toolu_1", {"source": "inherited", "name": "w"})
        merge_dispatch_row(tmp_path, "s1", "toolu_1", {"resolved_model": "claude-opus-5-5"})
        assert read_dispatch_rows(tmp_path, "s1") == [
            {
                "tool_use_id": "toolu_1",
                "source": "inherited",
                "name": "w",
                "pre_recorded": True,
                "resolved_model": "claude-opus-5-5",
            }
        ]

    def test_a_post_without_a_pre_row_is_kept_and_marked_unjoined(self, tmp_path: Path) -> None:
        merge_dispatch_row(tmp_path, "s1", "toolu_2", {"resolved_model": "claude-opus-5-5"})
        (row,) = read_dispatch_rows(tmp_path, "s1")
        assert row["tool_use_id"] == "toolu_2"
        assert row["pre_recorded"] is False

    def test_rows_live_in_the_session_ledger(self, tmp_path: Path) -> None:
        write_dispatch_row(tmp_path, "s1", "toolu_1", {"source": "fork"})
        assert next((session_dir(tmp_path, "s1") / "dispatches").iterdir()).suffix == ".json"

    def test_unknown_session_has_no_rows(self, tmp_path: Path) -> None:
        assert read_dispatch_rows(tmp_path, "nobody") == []

    def test_a_corrupt_row_is_skipped(self, tmp_path: Path) -> None:
        write_dispatch_row(tmp_path, "s1", "toolu_1", {"source": "fork"})
        (session_dir(tmp_path, "s1") / "dispatches" / "junk.json").write_text("{bad")
        assert [row["tool_use_id"] for row in read_dispatch_rows(tmp_path, "s1")] == ["toolu_1"]


class TestAgentMeta:
    def test_reads_the_sibling_meta_file(self, tmp_path: Path) -> None:
        transcript = tmp_path / "agent-ax-1.jsonl"
        (tmp_path / "agent-ax-1.meta.json").write_text(
            json.dumps({"name": "p471-x", "spawnedAgentType": "python-developer", "model": "opus"})
        )
        assert read_agent_meta(transcript) == AgentMeta(
            name="p471-x", agent_type="python-developer", model="opus"
        )

    def test_reads_the_tool_use_id_the_dispatch_rows_join_on(self, tmp_path: Path) -> None:
        """Plan 00472 Task 3.3: meta.json's toolUseId is the join key to the dispatch row."""
        transcript = tmp_path / "agent-ax-2.jsonl"
        (tmp_path / "agent-ax-2.meta.json").write_text(json.dumps({"toolUseId": "toolu_1"}))
        assert read_agent_meta(transcript).tool_use_id == "toolu_1"

    def test_missing_or_corrupt_is_empty(self, tmp_path: Path) -> None:
        assert read_agent_meta(tmp_path / "agent-a.jsonl") == AgentMeta()
        (tmp_path / "agent-b.meta.json").write_text("{bad")
        assert read_agent_meta(tmp_path / "agent-b.jsonl") == AgentMeta()


class TestSpendCache:
    def test_one_cache_per_directory(self, tmp_path: Path) -> None:
        assert spend_cache(tmp_path) is spend_cache(tmp_path)
        assert spend_cache(None) is spend_cache(None)
        assert spend_cache(tmp_path) is not spend_cache(tmp_path / "other")
