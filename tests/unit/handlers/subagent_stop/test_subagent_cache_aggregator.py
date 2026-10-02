"""Tests for SubagentCacheAggregatorHandler (Plan 00452).

Sub-agents get no status line of their own, so the coordinator's single bar is
the ONLY place their cache cost can ever appear. Their usage is also not in the
main transcript — every record there is `isSidechain: false` — so something has
to collect it as each agent finishes. This handler is that collector.

It matters because the two halves diverge sharply. Measured in this project:
the main thread ran 98.87% on a 1-hour TTL while a short sub-agent ran 62.17%
on a 5-minute one. A bar showing only the main figure would report a healthy
session while the expensive half stayed invisible.

**One file per agent, deliberately.** A single cumulative file would need a
read-modify-write, and two sub-agents finishing at the same moment would lose
one of the updates — the unlocked select-then-delete class Plan 00449 exists
for. Per-agent files make concurrent writers structurally incapable of
clobbering each other, with no lock to get wrong.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    MANUAL_PROBE,
    PROBE_AGENT_ID,
    SYNTHETIC_SOURCE_FIELD,
)
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_cache_aggregator import (
    _MAX_MEMOISED_SESSIONS,
    SubagentCacheAggregatorHandler,
    _scans,
    read_subagent_cache_totals,
)

_AGENT_RECORDS = [
    {"message": {"usage": {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 40}}},
    {
        "message": {
            "usage": {
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 10,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 10,
                    "ephemeral_1h_input_tokens": 0,
                },
            }
        }
    },
]


def _write_agent_transcript(path: Path, records: list[dict]) -> None:
    """Write a JSONL transcript, with a non-JSON line among the records.

    The real task directory interleaves agent transcripts with plain-text bash
    output, and a naive slurp exits non-zero on the first one. The reader has
    to survive that, so every fixture here contains such a line.
    """
    lines = [json.dumps(r) for r in records]
    lines.insert(1, "this line is not JSON at all")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestSubagentCacheAggregatorHandler:
    @pytest.fixture
    def handler(self):
        return SubagentCacheAggregatorHandler()

    @pytest.fixture
    def transcript(self, tmp_path: Path) -> Path:
        target = tmp_path / "agent.jsonl"
        _write_agent_transcript(target, _AGENT_RECORDS)
        return target

    def test_it_is_not_terminal(self, handler):
        """Collecting a number must never end a stop that would otherwise continue."""
        assert handler.terminal is False

    def test_it_matches_a_stop_carrying_an_agent_transcript(self, handler, transcript):
        assert handler.matches({"agent_transcript_path": str(transcript), "agent_id": "a1"}) is True

    def test_it_does_not_match_without_an_agent_transcript(self, handler):
        assert handler.matches({"agent_id": "a1"}) is False

    def test_it_does_not_count_a_probe_as_an_agent(self, handler, transcript):
        """Plan 00466 N12: a probe's totals would join the status line's real ones."""
        hook_input = {
            "agent_transcript_path": str(transcript),
            "agent_id": PROBE_AGENT_ID,
            SYNTHETIC_SOURCE_FIELD: MANUAL_PROBE,
        }
        assert handler.matches(hook_input) is False

    # --- parsing ---

    def test_it_sums_reads_and_writes_across_records(self, handler, transcript):
        totals = handler.totals_for(transcript)
        assert totals["cache_read_tokens"] == 300
        assert totals["cache_write_tokens"] == 50

    def test_it_survives_a_non_json_line(self, handler, transcript):
        """The fixture embeds one; a strict reader would raise instead of skipping."""
        assert handler.totals_for(transcript)["requests"] == 2

    def test_it_splits_the_ttl_buckets(self, handler, transcript):
        totals = handler.totals_for(transcript)
        assert totals["ttl_5m_write_tokens"] == 10
        assert totals["ttl_1h_write_tokens"] == 0

    # --- one API request, several transcript records ---
    #
    # Claude Code writes one transcript record per CONTENT BLOCK (thinking,
    # text, each tool_use), and every one of them carries the whole request's
    # usage. Measured over this project's sub-agents: 4,276 usage records for
    # 2,119 requests, every duplicate byte-identical. Summing records therefore
    # counted each request about twice, inflating writes 1.5-2.3x per agent.

    def test_records_sharing_a_message_id_are_one_request(self, handler, tmp_path):
        usage = {"cache_read_input_tokens": 100, "cache_creation_input_tokens": 40}
        target = tmp_path / "agent.jsonl"
        _write_agent_transcript(
            target,
            [
                {"message": {"id": "msg_1", "usage": usage}},
                {"message": {"id": "msg_1", "usage": usage}},
                {"message": {"id": "msg_1", "usage": usage}},
            ],
        )
        totals = handler.totals_for(target)
        assert totals["requests"] == 1
        assert totals["cache_read_tokens"] == 100
        assert totals["cache_write_tokens"] == 40

    def test_distinct_message_ids_are_all_counted(self, handler, tmp_path):
        target = tmp_path / "agent.jsonl"
        _write_agent_transcript(
            target,
            [
                {"message": {"id": "msg_1", "usage": {"cache_read_input_tokens": 100}}},
                {"message": {"id": "msg_1", "usage": {"cache_read_input_tokens": 100}}},
                {"message": {"id": "msg_2", "usage": {"cache_read_input_tokens": 7}}},
            ],
        )
        totals = handler.totals_for(target)
        assert totals["requests"] == 2
        assert totals["cache_read_tokens"] == 107

    def test_the_ttl_buckets_are_not_double_counted_either(self, handler, tmp_path):
        usage = {
            "cache_creation_input_tokens": 30,
            "cache_creation": {"ephemeral_5m_input_tokens": 30, "ephemeral_1h_input_tokens": 0},
        }
        target = tmp_path / "agent.jsonl"
        _write_agent_transcript(
            target,
            [
                {"message": {"id": "msg_1", "usage": usage}},
                {"message": {"id": "msg_1", "usage": usage}},
            ],
        )
        assert handler.totals_for(target)["ttl_5m_write_tokens"] == 30

    def test_a_record_without_a_message_id_is_still_counted(self, handler, transcript):
        """With no id there is nothing to dedupe on; dropping it would lose real usage.

        The shared fixture carries no ids, so this is also what keeps every
        older assertion in this file meaningful.
        """
        assert handler.totals_for(transcript)["requests"] == 2

    def test_a_missing_transcript_yields_zeroes_not_an_exception(self, handler, tmp_path):
        totals = handler.totals_for(tmp_path / "does-not-exist.jsonl")
        assert totals["requests"] == 0

    # --- the round trip, which is what the status line consumes ---

    def test_totals_written_for_one_agent_are_read_back(self, handler, transcript, tmp_path):
        handler.record(
            session_id="sess", agent_id="agent-one", transcript=transcript, root=tmp_path
        )
        combined = read_subagent_cache_totals("sess", root=tmp_path)
        assert combined["cache_read_tokens"] == 300
        assert combined["agents_seen"] == 1

    def test_two_agents_both_survive(self, handler, transcript, tmp_path):
        """The reason for one file per agent: neither writer may clobber the other."""
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        handler.record(session_id="sess", agent_id="two", transcript=transcript, root=tmp_path)
        combined = read_subagent_cache_totals("sess", root=tmp_path)
        assert combined["agents_seen"] == 2
        assert combined["cache_read_tokens"] == 600

    def test_the_same_agent_recorded_twice_is_not_double_counted(
        self, handler, transcript, tmp_path
    ):
        """Keyed by agent id, so a re-fired stop overwrites rather than accumulates."""
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        combined = read_subagent_cache_totals("sess", root=tmp_path)
        assert combined["agents_seen"] == 1
        assert combined["cache_read_tokens"] == 300

    def test_sessions_do_not_bleed_into_each_other(self, handler, transcript, tmp_path):
        handler.record(session_id="sess-a", agent_id="one", transcript=transcript, root=tmp_path)
        handler.record(session_id="sess-b", agent_id="one", transcript=transcript, root=tmp_path)
        assert read_subagent_cache_totals("sess-a", root=tmp_path)["agents_seen"] == 1

    def test_an_unknown_session_reads_back_empty_rather_than_raising(self, tmp_path):
        combined = read_subagent_cache_totals("never-seen", root=tmp_path)
        assert combined["agents_seen"] == 0
        assert combined["cache_read_tokens"] == 0

    def test_a_corrupt_sidecar_file_is_skipped_not_fatal(self, handler, transcript, tmp_path):
        """A half-written or hand-mangled file must not take the status line down."""
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        bad = tmp_path / "cache-sidecar" / "sess" / "corrupt.json"
        bad.write_text("{not json", encoding="utf-8")
        combined = read_subagent_cache_totals("sess", root=tmp_path)
        assert combined["agents_seen"] == 1

    # --- the write is best-effort, and that has to be provable ---

    def test_a_missing_project_context_does_not_raise(self, handler, transcript, monkeypatch):
        """A daemon with no project context has nowhere to write, and must still allow."""

        def _no_context():
            raise RuntimeError("ProjectContext not initialised")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.subagent_stop."
            "subagent_cache_aggregator.ProjectContext.daemon_untracked_dir",
            staticmethod(_no_context),
        )
        handler.record(session_id="sess", agent_id="one", transcript=transcript)

    def test_an_unwritable_root_does_not_raise(self, handler, transcript, tmp_path):
        """An OSError from the sidecar write costs a number, never the stop.

        The root is placed UNDER a regular file, so `mkdir` raises
        NotADirectoryError. chmod would not do here: this container runs as
        root, which is denied nothing.
        """
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("", encoding="utf-8")
        handler.record(
            session_id="sess", agent_id="one", transcript=transcript, root=blocker / "under"
        )

    # --- the guard on the guard ---

    def test_the_fixture_actually_carries_cache_numbers(self, handler, transcript):
        """A fixture of all zeroes would make every assertion above vacuous."""
        assert handler.totals_for(transcript)["cache_read_tokens"] > 0

    def test_handle_allows_the_stop(self, handler, transcript):
        """A sensor on a blocking event: collecting a number must never strand an agent."""
        result = handler.handle({"agent_transcript_path": str(transcript), "agent_id": "a1"})
        assert result.decision == Decision.ALLOW

    def test_handle_allows_even_when_the_transcript_is_missing(self, handler, tmp_path):
        """The ALLOW is unconditional — an uncollectable number is not a reason to block."""
        result = handler.handle(
            {"agent_transcript_path": str(tmp_path / "gone.jsonl"), "agent_id": "a1"}
        )
        assert result.decision == Decision.ALLOW


def _age_session(root: Path, session: str, seconds: int = 60) -> None:
    """Back-date a session directory and its files so the memo may trust them."""
    directory = root / "cache-sidecar" / session
    old = time.time() - seconds
    for entry in directory.iterdir():
        os.utime(entry, (old, old))
    os.utime(directory, (old, old))


class TestReadCostDoesNotScaleWithAgentCount:
    """N295: a render re-parsed every agent's file; it must cost one stat instead."""

    @pytest.fixture
    def handler(self) -> SubagentCacheAggregatorHandler:
        return SubagentCacheAggregatorHandler()

    @pytest.fixture
    def transcript(self, tmp_path: Path) -> Path:
        target = tmp_path / "agent.jsonl"
        _write_agent_transcript(target, _AGENT_RECORDS)
        return target

    @pytest.fixture
    def json_loads_spy(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []
        real = json.loads

        def _counting(text, *args, **kwargs):
            calls.append(text)
            return real(text, *args, **kwargs)

        monkeypatch.setattr(json, "loads", _counting)
        return calls

    def _record_many(self, handler, transcript: Path, root: Path, count: int) -> None:
        for index in range(count):
            handler.record(
                session_id="sess", agent_id=f"agent-{index}", transcript=transcript, root=root
            )

    def test_repeated_reads_parse_nothing_after_the_first(
        self, handler, transcript, tmp_path, json_loads_spy
    ):
        self._record_many(handler, transcript, tmp_path, 40)
        _age_session(tmp_path, "sess")
        first = read_subagent_cache_totals("sess", root=tmp_path)
        json_loads_spy.clear()
        for _ in range(25):
            assert read_subagent_cache_totals("sess", root=tmp_path) == first
        assert json_loads_spy == []
        assert first["agents_seen"] == 40
        assert first["cache_read_tokens"] == 40 * 300

    def test_the_cold_read_parses_each_file_once(
        self, handler, transcript, tmp_path, json_loads_spy
    ):
        self._record_many(handler, transcript, tmp_path, 10)
        json_loads_spy.clear()
        read_subagent_cache_totals("sess", root=tmp_path)
        assert len(json_loads_spy) == 10

    def test_a_newly_stopped_agent_shows_on_the_very_next_read(
        self, handler, transcript, tmp_path, json_loads_spy
    ):
        self._record_many(handler, transcript, tmp_path, 5)
        _age_session(tmp_path, "sess")
        assert read_subagent_cache_totals("sess", root=tmp_path)["agents_seen"] == 5
        handler.record(session_id="sess", agent_id="late", transcript=transcript, root=tmp_path)
        json_loads_spy.clear()
        after = read_subagent_cache_totals("sess", root=tmp_path)
        assert after["agents_seen"] == 6
        assert after["cache_read_tokens"] == 6 * 300
        assert len(json_loads_spy) == 1, "only the new file may be parsed"

    def test_a_rewritten_agent_is_replaced_not_double_counted(self, handler, transcript, tmp_path):
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        _age_session(tmp_path, "sess")
        assert read_subagent_cache_totals("sess", root=tmp_path)["cache_read_tokens"] == 300
        _write_agent_transcript(transcript, _AGENT_RECORDS + _AGENT_RECORDS)
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        after = read_subagent_cache_totals("sess", root=tmp_path)
        assert after["agents_seen"] == 1
        assert after["requests"] == 4
        assert after["cache_read_tokens"] == 600

    def test_writes_inside_one_timestamp_tick_are_never_missed(self, handler, transcript, tmp_path):
        """Fresh stamps are untrusted, so same-tick writes between reads still land."""
        for index in range(30):
            handler.record(
                session_id="sess", agent_id=f"a{index}", transcript=transcript, root=tmp_path
            )
            seen = read_subagent_cache_totals("sess", root=tmp_path)
            assert seen["agents_seen"] == index + 1
            assert seen["cache_read_tokens"] == (index + 1) * 300

    def test_an_in_place_edit_inside_one_tick_is_picked_up(self, handler, transcript, tmp_path):
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        target = tmp_path / "cache-sidecar" / "sess" / "one.json"
        assert read_subagent_cache_totals("sess", root=tmp_path)["cache_read_tokens"] == 300
        target.write_text(json.dumps({"cache_read_tokens": 7}), encoding="utf-8")
        assert read_subagent_cache_totals("sess", root=tmp_path)["cache_read_tokens"] == 7

    def test_a_removed_agent_file_stops_counting(self, handler, transcript, tmp_path):
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        handler.record(session_id="sess", agent_id="two", transcript=transcript, root=tmp_path)
        _age_session(tmp_path, "sess")
        assert read_subagent_cache_totals("sess", root=tmp_path)["agents_seen"] == 2
        (tmp_path / "cache-sidecar" / "sess" / "two.json").unlink()
        assert read_subagent_cache_totals("sess", root=tmp_path)["agents_seen"] == 1

    def test_a_vanished_session_directory_reads_empty_after_being_memoised(
        self, handler, transcript, tmp_path
    ):
        handler.record(session_id="sess", agent_id="one", transcript=transcript, root=tmp_path)
        _age_session(tmp_path, "sess")
        read_subagent_cache_totals("sess", root=tmp_path)
        shutil.rmtree(tmp_path / "cache-sidecar" / "sess")
        assert read_subagent_cache_totals("sess", root=tmp_path)["agents_seen"] == 0

    def test_the_memo_is_bounded(self, handler, transcript, tmp_path):
        for index in range(_MAX_MEMOISED_SESSIONS + 5):
            handler.record(
                session_id=f"s{index}", agent_id="one", transcript=transcript, root=tmp_path
            )
            read_subagent_cache_totals(f"s{index}", root=tmp_path)
        assert len(_scans) <= _MAX_MEMOISED_SESSIONS

    def test_concurrent_readers_and_a_writer_stay_consistent(self, handler, transcript, tmp_path):
        """Every read sees a whole number of agents, and the last read sees them all."""
        errors: list[str] = []
        stop = threading.Event()

        def _reader() -> None:
            while not stop.is_set():
                seen = read_subagent_cache_totals("sess", root=tmp_path)
                if seen["cache_read_tokens"] != seen["agents_seen"] * 300:
                    errors.append(f"torn read: {seen}")

        readers = [threading.Thread(target=_reader) for _ in range(4)]
        for thread in readers:
            thread.start()
        try:
            for index in range(40):
                handler.record(
                    session_id="sess", agent_id=f"a{index}", transcript=transcript, root=tmp_path
                )
        finally:
            stop.set()
            for thread in readers:
                thread.join()
        assert errors == []
        assert read_subagent_cache_totals("sess", root=tmp_path)["agents_seen"] == 40
