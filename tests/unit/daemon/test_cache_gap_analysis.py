"""Tests for the idle-gap / cache-cost analyser (Plan 00452 Phase 2).

The question this module exists to answer is whether warming a project's cache
would PAY, and that turns entirely on the shape of its idle gaps: a session
driven every few minutes never goes cold and has nothing to gain, while a
human-paced one may cross its TTL repeatedly a day. This repository cannot
answer that about itself — its crons keep it permanently warm, so measuring
here would measure the warming, not the need for it (Task 2.4). The analyser
therefore has to be something ANY project can run against its own transcript.

`TestTheGuardOnTheGuard` is Task 2.2 and is the most important class here. A
detector whose matcher is subtly wrong finds nothing and reports a PERFECT
score — no error, no failing assertion, just a confident wrong answer. So the
fixtures carry known writes and known gaps, and the tests assert those exact
values are recovered.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.cache_gap_analysis import (
    GAP_BUCKETS,
    analyse_transcript,
    parse_timestamp,
)


def _record(ts: str, read: int = 0, write: int = 0, ttl_1h: int | None = None) -> str:
    """One assistant record in the shape Claude Code actually writes."""
    usage: dict[str, Any] = {
        "input_tokens": 2,
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": write,
        "output_tokens": 10,
    }
    if ttl_1h is not None:
        usage["cache_creation"] = {
            "ephemeral_1h_input_tokens": ttl_1h,
            "ephemeral_5m_input_tokens": write - ttl_1h,
        }
    return json.dumps(
        {"type": "assistant", "timestamp": ts, "isSidechain": False, "message": {"usage": usage}}
    )


#: Three requests: a 30-second gap then a two-hour gap. Both are asserted on
#: by name below, so a change to either shows up as a test failure rather than
#: as a quietly different histogram.
_LINES = [
    _record("2026-09-16T12:00:00.000Z", read=1000, write=40_000, ttl_1h=40_000),
    _record("2026-09-16T12:00:30.000Z", read=41_000, write=0),
    _record("2026-09-16T14:00:30.000Z", read=0, write=50_000, ttl_1h=50_000),
]


class TestParseTimestamp:
    def test_it_parses_the_z_suffixed_iso_claude_code_writes(self):
        """Compared against an explicitly-UTC datetime, not a hand-computed epoch.

        A literal here would be asserting my own arithmetic; building the
        expected moment with an explicit `timezone.utc` asserts the thing that
        actually matters — that the `Z` suffix is read as UTC and not as local
        time, which is a whole-hours error that would survive most fixtures.
        """
        expected = dt.datetime(2026, 9, 16, 12, 5, 44, 202_000, tzinfo=dt.UTC)
        assert parse_timestamp("2026-09-16T12:05:44.202Z") == pytest.approx(expected.timestamp())

    @pytest.mark.parametrize("raw", [None, "", "yesterday", 12345, True, {}])
    def test_anything_else_is_none_not_a_guess(self, raw):
        """A mis-parsed timestamp produces a plausible, wrong gap histogram."""
        assert parse_timestamp(raw) is None


class TestTheGuardOnTheGuard:
    """Task 2.2: a detector that matches nothing reports a perfect score."""

    def test_the_fixture_actually_contains_cache_writes(self):
        """If this ever reads zero, every 'no writes found' result below is vacuous."""
        assert sum("cache_creation_input_tokens" in line for line in _LINES) == len(_LINES)

    def test_the_known_writes_are_recovered_exactly(self):
        report = analyse_transcript(_LINES)
        assert report["tokens"]["cache_write"] == 90_000

    def test_the_known_reads_are_recovered_exactly(self):
        report = analyse_transcript(_LINES)
        assert report["tokens"]["cache_read"] == 42_000

    def test_the_known_request_count_is_recovered(self):
        assert analyse_transcript(_LINES)["requests"] == 3

    def test_the_known_gaps_are_recovered_exactly(self):
        """Two gaps from three requests: 30s and 7200s."""
        report = analyse_transcript(_LINES)
        assert report["gaps"]["count"] == 2
        assert report["gaps"]["max_seconds"] == pytest.approx(7200, abs=1)


class TestTheGapHistogram:
    def test_every_gap_lands_in_exactly_one_bucket(self):
        """A histogram that drops or double-counts a gap misreports the profile."""
        report = analyse_transcript(_LINES)
        assert sum(report["gaps"]["histogram"].values()) == report["gaps"]["count"]

    def test_the_buckets_are_reported_even_when_empty(self):
        """An absent bucket is indistinguishable from a bucket nobody measured."""
        report = analyse_transcript(_LINES)
        assert set(report["gaps"]["histogram"]) == {label for label, _ in GAP_BUCKETS}

    def test_a_short_gap_and_a_long_gap_land_in_different_buckets(self):
        report = analyse_transcript(_LINES)
        occupied = [k for k, v in report["gaps"]["histogram"].items() if v]
        assert len(occupied) == 2

    def test_gaps_crossing_each_ttl_are_counted_separately(self):
        """The 5m and 1h TTLs give completely different answers on the same data.

        That difference IS the finding: a project whose gaps all sit between
        the two is one whose sub-agents go cold while its main thread never
        does.
        """
        report = analyse_transcript(_LINES)
        assert report["gaps"]["exceeding_5m"] == 1
        assert report["gaps"]["exceeding_1h"] == 1

    def test_a_gap_between_the_two_ttls_counts_for_the_shorter_only(self):
        lines = [
            _record("2026-09-16T12:00:00.000Z", read=100),
            _record("2026-09-16T12:30:00.000Z", read=100),
        ]
        report = analyse_transcript(lines)
        assert report["gaps"]["exceeding_5m"] == 1
        assert report["gaps"]["exceeding_1h"] == 0


class TestTolerance:
    """The transcript is external data appended to live."""

    def test_a_non_json_line_is_skipped_not_fatal(self):
        report = analyse_transcript(["not json at all", *_LINES])
        assert report["requests"] == 3

    def test_a_torn_final_line_is_skipped_not_fatal(self):
        """Claude Code appends live, so the last line is routinely half-written."""
        report = analyse_transcript([*_LINES, '{"type":"assis'])
        assert report["requests"] == 3

    def test_a_record_without_usage_is_not_a_request(self):
        report = analyse_transcript([json.dumps({"type": "user", "timestamp": "x"}), *_LINES])
        assert report["requests"] == 3

    def test_a_record_without_a_timestamp_still_counts_its_tokens(self):
        """Dropping the tokens would understate the cost over a malformed line."""
        line = json.dumps({"message": {"usage": {"cache_read_input_tokens": 500}}})
        report = analyse_transcript([line])
        assert report["tokens"]["cache_read"] == 500
        assert report["gaps"]["count"] == 0

    def test_an_empty_transcript_reports_zeroes_rather_than_raising(self):
        report = analyse_transcript([])
        assert report["requests"] == 0
        assert report["gaps"]["count"] == 0
        assert report["hit_ratio"] is None

    def test_out_of_order_timestamps_do_not_produce_a_negative_gap(self):
        """A negative gap would silently drag the median and the max downward."""
        lines = [
            _record("2026-09-16T12:30:00.000Z", read=100),
            _record("2026-09-16T12:00:00.000Z", read=100),
        ]
        report = analyse_transcript(lines)
        assert report["gaps"]["max_seconds"] >= 0


class TestSidechainSplit:
    def test_sub_agent_records_are_counted_separately(self):
        """Main and sub diverge sharply, so one blended number hides the expensive half."""
        lines = [
            _record("2026-09-16T12:00:00.000Z", read=1000, write=100),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-09-16T12:00:10.000Z",
                    "isSidechain": True,
                    "message": {"usage": {"cache_read_input_tokens": 7, "output_tokens": 1}},
                }
            ),
        ]
        report = analyse_transcript(lines)
        assert report["requests"] == 1
        assert report["sidechain_requests"] == 1
        assert report["tokens"]["cache_read"] == 1000


class TestTheHitRatio:
    def test_it_is_reads_over_reads_plus_writes(self):
        report = analyse_transcript(_LINES)
        assert report["hit_ratio"] == pytest.approx(42_000 / (42_000 + 90_000))

    def test_the_ttl_split_is_reported(self):
        report = analyse_transcript(_LINES)
        assert report["tokens"]["ttl_1h_write"] == 90_000
        assert report["tokens"]["ttl_5m_write"] == 0
