"""Tests for skill_scan.constants (Plan 00274)."""

from __future__ import annotations

from claude_code_hooks_daemon.skill_scan import constants


class TestConstants:
    def test_exclude_flags_frozen_contract(self) -> None:
        assert "isMeta" in constants.EXCLUDE_FLAGS
        assert "isSidechain" in constants.EXCLUDE_FLAGS
        assert "isCompactSummary" in constants.EXCLUDE_FLAGS
        assert "isVisibleInTranscriptOnly" in constants.EXCLUDE_FLAGS

    def test_content_markers_cover_known_machine_traffic(self) -> None:
        markers = constants.EXCLUDE_CONTENT_MARKERS
        assert "<teammate-message" in markers
        assert "FAILSAFE RECOVERY CHECK" in markers
        assert "🤖 [ccy-supervisor" in markers

    def test_budgets_positive(self) -> None:
        assert constants.DEFAULT_MAX_CLUSTERS > 0
        assert constants.MAX_PAYLOAD_CHARS > 0
        assert constants.REPRESENTATIVE_MAX_CHARS > 0

    def test_jaccard_threshold_is_decision_4_value(self) -> None:
        assert constants.JACCARD_THRESHOLD == 0.5

    def test_defaults_match_config_surface(self) -> None:
        assert constants.DEFAULT_CHECK_INTERVAL_DAYS == 7
        assert constants.DEFAULT_TRANSCRIPT_WINDOW_DAYS == 14
