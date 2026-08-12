"""Tests for verdict log reporting (Plan 00209 Task 2.5).

Pure aggregation over parsed verdicts.jsonl records: per-handler fire
counts, verdict mix, override rate, and (when the caller supplies the full
registered-handler set) which handlers never fired at all.
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.daemon.verdict_report import (
    aggregate_verdicts,
    format_report,
    read_verdict_records,
)


class TestReadVerdictRecords:
    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        assert read_verdict_records(tmp_path / "does-not-exist.jsonl") == []

    def test_reads_valid_jsonl_lines(self, tmp_path: Path) -> None:
        target = tmp_path / "verdicts.jsonl"
        target.write_text(
            json.dumps({"handler": "h1", "verdict": "deny"})
            + "\n"
            + json.dumps({"handler": "h2", "verdict": "allow"})
            + "\n"
        )
        records = read_verdict_records(target)
        assert len(records) == 2
        assert records[0]["handler"] == "h1"
        assert records[1]["handler"] == "h2"

    def test_skips_malformed_lines_without_crashing(self, tmp_path: Path) -> None:
        target = tmp_path / "verdicts.jsonl"
        target.write_text(
            json.dumps({"handler": "h1", "verdict": "deny"})
            + "\n"
            + "not json at all\n"
            + json.dumps({"handler": "h2", "verdict": "allow"})
            + "\n"
        )
        records = read_verdict_records(target)
        assert len(records) == 2

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        target = tmp_path / "verdicts.jsonl"
        target.write_text(json.dumps({"handler": "h1", "verdict": "deny"}) + "\n\n")
        records = read_verdict_records(target)
        assert len(records) == 1


class TestAggregateVerdicts:
    def _record(
        self,
        handler: str | None,
        verdict: str,
        overridden: bool = False,
    ) -> dict[str, object]:
        return {
            "ts": "2026-08-12T00:00:00+00:00",
            "session": "s",
            "event": "PreToolUse",
            "tool": "Bash",
            "handler": handler,
            "verdict": verdict,
            "rule": None,
            "mode": "block" if verdict in ("deny", "ask") else "advisory",
            "overridden": overridden,
        }

    def test_empty_records_yields_zeroed_aggregate(self) -> None:
        agg = aggregate_verdicts([])
        assert agg["total_records"] == 0
        assert agg["handler_counts"] == {}
        assert agg["verdict_mix"] == {}
        assert agg["override_count"] == 0
        assert agg["override_rate"] == 0.0

    def test_handler_counts_exclude_synthetic_override_lines(self) -> None:
        records = [
            self._record("pipe_blocker", "deny"),
            self._record("pipe_blocker", "deny"),
            self._record(None, "override", overridden=True),
        ]
        agg = aggregate_verdicts(records)
        assert agg["handler_counts"] == {"pipe_blocker": 2}
        assert agg["total_records"] == 3

    def test_verdict_mix_counts_every_record_including_override(self) -> None:
        records = [
            self._record("h1", "deny"),
            self._record("h2", "allow"),
            self._record(None, "override", overridden=True),
        ]
        agg = aggregate_verdicts(records)
        assert agg["verdict_mix"] == {"deny": 1, "allow": 1, "override": 1}

    def test_override_count_and_rate(self) -> None:
        records = [
            self._record("h1", "deny"),
            self._record("h2", "allow"),
            self._record(None, "override", overridden=True),
            self._record(None, "override", overridden=True),
        ]
        agg = aggregate_verdicts(records)
        assert agg["override_count"] == 2
        assert agg["override_rate"] == 0.5

    def test_never_fired_is_none_when_no_handler_universe_given(self) -> None:
        agg = aggregate_verdicts([self._record("h1", "deny")])
        assert agg["never_fired"] is None

    def test_never_fired_lists_handlers_absent_from_the_log(self) -> None:
        records = [self._record("h1", "deny"), self._record("h2", "allow")]
        agg = aggregate_verdicts(records, all_handlers=["h1", "h2", "h3"])
        assert agg["never_fired"] == ["h3"]

    def test_never_fired_is_empty_when_everything_fired(self) -> None:
        records = [self._record("h1", "deny")]
        agg = aggregate_verdicts(records, all_handlers=["h1"])
        assert agg["never_fired"] == []

    def test_per_handler_verdict_breakdown(self) -> None:
        """Per-handler verdict mix (not just overall) lets the report show
        e.g. pipe_blocker: deny x5, absolute_path: deny x1, allow x2."""
        records = [
            self._record("pipe_blocker", "deny"),
            self._record("pipe_blocker", "deny"),
            self._record("absolute_path", "allow"),
        ]
        agg = aggregate_verdicts(records)
        assert agg["handler_verdict_mix"]["pipe_blocker"] == {"deny": 2}
        assert agg["handler_verdict_mix"]["absolute_path"] == {"allow": 1}


class TestFormatReport:
    def test_report_states_it_is_a_window_not_lifetime_totals(self) -> None:
        """Plan 00209 Task 2.4: verdicts.jsonl is a bounded rolling sample.
        The report must never present its numbers as lifetime totals."""
        agg = aggregate_verdicts([])
        text = format_report(agg)
        assert "window" in text.lower()
        assert "not" in text.lower()

    def test_report_lists_handler_counts(self) -> None:
        records = [
            {
                "handler": "pipe_blocker",
                "verdict": "deny",
                "overridden": False,
            },
            {
                "handler": "pipe_blocker",
                "verdict": "deny",
                "overridden": False,
            },
        ]
        agg = aggregate_verdicts(records)
        text = format_report(agg)
        assert "pipe_blocker" in text
        assert "2" in text

    def test_report_lists_never_fired_handlers(self) -> None:
        agg = aggregate_verdicts(
            [{"handler": "h1", "verdict": "deny", "overridden": False}],
            all_handlers=["h1", "h2"],
        )
        text = format_report(agg)
        assert "h2" in text

    def test_report_handles_no_data_gracefully(self) -> None:
        agg = aggregate_verdicts([])
        text = format_report(agg)
        assert isinstance(text, str)
        assert text
