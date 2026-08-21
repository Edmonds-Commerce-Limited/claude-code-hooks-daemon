"""Tests for verdict log reporting (Plan 00209 Task 2.5).

Pure aggregation over parsed verdicts.jsonl records: per-handler fire
counts, verdict mix, override rate, and (when the caller supplies the full
registered-handler set) which handlers never fired at all.
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.core.event import EventType
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


class TestLegacyStatusRecordsInTheRetainedWindow:
    """The report must not assert an omission its own roster contradicts.

    Found by dogfooding, not by a test: on this project's live log the report
    printed "status handlers are omitted from the roster below" and then listed
    thirteen of them at the top of that very roster. Nothing pinned that
    sentence, which is how it drifted into being false.

    The cause is two enumeration surfaces disagreeing — the same class Plan
    00237 closed in the registry and Plan 00234 closed in the writer.
    ``cli.py``'s ``_behavioural_handler_names`` drops Status renderers from the
    REGISTERED side so they cannot land in never-fired; the aggregate kept them
    on the FIRED side. Status records stopped being written when Plan 00234
    landed, but the log is a rolling window, so records predating that change
    stay visible until they are trimmed.

    Separating them is not narrowing: a renderer can only ever return 'allow',
    so it can carry neither a deny nor an override. Leaving it in the
    denominator understates the override rate, and leaving it in the roster
    contradicts the never-fired side. Dropping it SILENTLY would be the real
    narrowing, which is why the report has to name what it set aside.
    """

    def _status(self, handler: str, ts: str) -> dict[str, object]:
        return {
            "ts": ts,
            "event": EventType.STATUS_LINE.value,
            "handler": handler,
            "verdict": "allow",
            "overridden": False,
        }

    def _behavioural(
        self, handler: str, verdict: str, overridden: bool = False
    ) -> dict[str, object]:
        return {
            "ts": "2026-08-21T12:00:00+00:00",
            "event": "PreToolUse",
            "handler": handler,
            "verdict": verdict,
            "overridden": overridden,
        }

    def _mixed(self) -> list[dict[str, object]]:
        return [
            self._status("status-git-branch", "2026-08-13T17:36:25+00:00"),
            self._status("status-daemon-stats", "2026-08-13T17:40:00+00:00"),
            self._status("status-git-branch", "2026-08-13T18:06:21+00:00"),
            self._behavioural("pipe-blocker", "deny"),
            self._behavioural("git-stash", "allow", overridden=True),
        ]

    def test_status_renders_are_kept_out_of_the_handler_roster(self) -> None:
        agg = aggregate_verdicts(self._mixed())

        assert "status-git-branch" not in agg["handler_counts"]
        assert "status-daemon-stats" not in agg["handler_counts"]
        assert agg["handler_counts"]["pipe-blocker"] == 1

    def test_legacy_status_renders_are_counted_and_dated_not_discarded(self) -> None:
        agg = aggregate_verdicts(self._mixed())

        assert agg["legacy_status_records"] == 3
        assert agg["behavioural_records"] == 2
        assert agg["total_records"] == 5
        assert agg["legacy_status_window"] == (
            "2026-08-13T17:36:25+00:00",
            "2026-08-13T18:06:21+00:00",
        )

    def test_override_rate_excludes_status_renders_from_its_denominator(self) -> None:
        agg = aggregate_verdicts(self._mixed())

        # One override in two behavioural records. Against the retained total
        # of five it would read 20%, understating a real signal by 2.5x — on
        # the live log the same error understated it roughly fourfold.
        assert agg["override_count"] == 1
        assert agg["override_rate"] == 0.5

    def test_the_report_names_the_records_it_set_aside(self) -> None:
        text = format_report(aggregate_verdicts(self._mixed()))

        assert "3" in text
        assert "2026-08-13T17:36:25+00:00" in text
        assert "2026-08-13T18:06:21+00:00" in text

    def test_no_roster_line_names_a_handler_the_report_calls_omitted(self) -> None:
        """The property, not just the shape that bit us.

        Whatever the record mix, a handler the report says it excluded must
        not then appear in the roster it says it excluded them from.
        """
        text = format_report(aggregate_verdicts(self._mixed()))
        roster = text.split("Per-handler fire counts:")[1].split("Verdict mix")[0]

        assert "status-git-branch" not in roster
        assert "status-daemon-stats" not in roster
        assert "pipe-blocker" in roster

    def test_the_verdict_mix_heading_does_not_claim_a_population_it_excludes(self) -> None:
        """The same drift, one heading further down.

        The caveat became false by claiming an omission the roster contradicted.
        The verdict-mix heading said "all handlers" over a tally that now
        excludes renderers — unpinned prose describing a filtered population is
        exactly what went wrong the first time.
        """
        text = format_report(aggregate_verdicts(self._mixed()))

        assert "Verdict mix (all handlers" not in text
        assert "behavioural" in text.split("Verdict mix")[1].split(":")[0]

    def test_a_window_with_no_status_renders_says_nothing_about_them(self) -> None:
        """No legacy block when there is no legacy — silence is the clean case."""
        agg = aggregate_verdicts([self._behavioural("pipe-blocker", "deny")])
        text = format_report(agg)

        assert agg["legacy_status_records"] == 0
        assert agg["legacy_status_window"] is None
        assert "LEGACY STATUS RECORDS" not in text
