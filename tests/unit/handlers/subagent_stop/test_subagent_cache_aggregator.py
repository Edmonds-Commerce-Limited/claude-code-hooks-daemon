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
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_cache_aggregator import (
    SubagentCacheAggregatorHandler,
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
