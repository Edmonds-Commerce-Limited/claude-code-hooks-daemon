"""Tests for the block-report ranked table + promotion recommendation
(Plan 00116 Task 2b.1).

The report ranks handlers by real block frequency and recommends which
should be PROMOTED (full guidance resident) per the configured
``min_blocks``/``min_sessions`` thresholds, plus drift notes when the
committed ``promoted_handlers`` list disagrees with the measured evidence.
The report itself never enforces anything — the injector reads the
committed config list, not this recommendation.
"""

from __future__ import annotations

from claude_code_hooks_daemon.block_report.analyser import BlockSummary, BlockUsage
from claude_code_hooks_daemon.block_report.report import (
    Drift,
    build_report,
    render_markdown,
    report_to_json,
)


def _summary(
    blocks: dict[str, BlockUsage],
    *,
    transcripts_scanned: int = 3,
    sessions_scanned: int = 3,
    malformed_lines: int = 0,
    unattributed_denies: int = 0,
) -> BlockSummary:
    return BlockSummary(
        transcripts_scanned=transcripts_scanned,
        sessions_scanned=sessions_scanned,
        malformed_lines=malformed_lines,
        unattributed_denies=unattributed_denies,
        blocks=blocks,
    )


def _usage(
    handler: str, total: int, sessions: set[str], last_seen: str | None = None
) -> BlockUsage:
    return BlockUsage(
        handler=handler, total=total, sessions=frozenset(sessions), last_seen=last_seen
    )


class TestBuildReport:
    def test_ranks_by_total_blocks_descending(self) -> None:
        summary = _summary(
            {
                "sed_blocker": _usage("sed_blocker", 10, {"s1", "s2"}),
                "git_stash": _usage("git_stash", 3, {"s1"}),
            }
        )
        report = build_report(summary, promoted_handlers=[], min_blocks=5, min_sessions=2)
        assert [row.handler for row in report.rows] == ["sed_blocker", "git_stash"]

    def test_recommends_promotion_above_both_thresholds(self) -> None:
        summary = _summary({"sed_blocker": _usage("sed_blocker", 10, {"s1", "s2"})})
        report = build_report(summary, promoted_handlers=[], min_blocks=5, min_sessions=2)
        row = report.rows[0]
        assert row.recommended_promote is True

    def test_does_not_recommend_promotion_below_session_threshold(self) -> None:
        summary = _summary({"sed_blocker": _usage("sed_blocker", 10, {"s1"})})
        report = build_report(summary, promoted_handlers=[], min_blocks=5, min_sessions=2)
        row = report.rows[0]
        assert row.recommended_promote is False

    def test_does_not_recommend_promotion_below_block_threshold(self) -> None:
        summary = _summary({"sed_blocker": _usage("sed_blocker", 4, {"s1", "s2"})})
        report = build_report(summary, promoted_handlers=[], min_blocks=5, min_sessions=2)
        row = report.rows[0]
        assert row.recommended_promote is False

    def test_currently_promoted_flag_reflects_config(self) -> None:
        summary = _summary({"sed_blocker": _usage("sed_blocker", 10, {"s1", "s2"})})
        report = build_report(
            summary, promoted_handlers=["sed_blocker"], min_blocks=5, min_sessions=2
        )
        assert report.rows[0].currently_promoted is True

    def test_drift_promoted_but_cold(self) -> None:
        """A handler in promoted_handlers with too few real blocks."""
        summary = _summary({"pipe_blocker": _usage("pipe_blocker", 1, {"s1"})})
        report = build_report(
            summary, promoted_handlers=["pipe_blocker"], min_blocks=5, min_sessions=2
        )
        assert report.rows[0].drift == Drift.PROMOTED_BUT_COLD

    def test_drift_hot_but_unpromoted(self) -> None:
        summary = _summary({"sed_blocker": _usage("sed_blocker", 10, {"s1", "s2"})})
        report = build_report(summary, promoted_handlers=[], min_blocks=5, min_sessions=2)
        assert report.rows[0].drift == Drift.HOT_BUT_UNPROMOTED

    def test_no_drift_when_promotion_matches_evidence(self) -> None:
        summary = _summary({"sed_blocker": _usage("sed_blocker", 10, {"s1", "s2"})})
        report = build_report(
            summary, promoted_handlers=["sed_blocker"], min_blocks=5, min_sessions=2
        )
        assert report.rows[0].drift is None

    def test_a_promoted_handler_with_zero_observed_blocks_still_appears(self) -> None:
        """Promoted-but-zero-evidence is the strongest form of drift, and the
        handler never appears in summary.blocks at all (no denies observed)."""
        summary = _summary({})
        report = build_report(
            summary, promoted_handlers=["never_fired"], min_blocks=5, min_sessions=2
        )
        row = next(r for r in report.rows if r.handler == "never_fired")
        assert row.total_blocks == 0
        assert row.drift == Drift.PROMOTED_BUT_COLD

    def test_provenance_fields_carried_through(self) -> None:
        summary = _summary({}, transcripts_scanned=7, sessions_scanned=4, unattributed_denies=2)
        report = build_report(summary, promoted_handlers=[], min_blocks=5, min_sessions=2)
        assert report.transcripts_scanned == 7
        assert report.sessions_scanned == 4
        assert report.unattributed_denies == 2


class TestRenderMarkdown:
    def test_contains_handler_and_counts(self) -> None:
        summary = _summary({"sed_blocker": _usage("sed_blocker", 10, {"s1", "s2"}, "2026-08-30")})
        report = build_report(summary, promoted_handlers=[], min_blocks=5, min_sessions=2)
        markdown = render_markdown(report)
        assert "sed_blocker" in markdown
        assert "10" in markdown
        assert "2026-08-30" in markdown

    def test_never_leaks_command_text(self) -> None:
        """Only handler names/counts are inputs to the renderer at all — this
        guards the privacy contract even if a caller misuses the report."""
        summary = _summary({"sed_blocker": _usage("sed_blocker", 1, {"s1"})})
        report = build_report(summary, promoted_handlers=[], min_blocks=5, min_sessions=2)
        markdown = render_markdown(report)
        assert "rm -rf" not in markdown


class TestReportToJson:
    def test_round_trips_handler_and_counts(self) -> None:
        summary = _summary({"sed_blocker": _usage("sed_blocker", 10, {"s1", "s2"}, "2026-08-30")})
        report = build_report(
            summary, promoted_handlers=["sed_blocker"], min_blocks=5, min_sessions=2
        )
        payload = report_to_json(report)
        row = next(r for r in payload["rows"] if r["handler"] == "sed_blocker")
        assert row["total_blocks"] == 10
        assert row["distinct_sessions"] == 2
        assert row["last_seen"] == "2026-08-30"
        assert row["currently_promoted"] is True
        assert row["recommended_promote"] is True
        assert row["drift"] is None
