"""Unit tests for the downgrade-indicator per-session high-water state (Plan 00278).

Pure helpers split out from the handler for the same reason `thread_registry.py`
was: the family-resolution and high-water read/write/evaluate logic is
unit-testable without a Handler or a live daemon.
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.handlers.status_line.downgrade_state import (
    evaluate_downgrade,
    read_downgrade_counts,
    read_high_water,
    resolve_model_family,
    state_dir,
    write_high_water,
)


class TestResolveModelFamily:
    def test_haiku_model_id(self) -> None:
        assert resolve_model_family("claude-haiku-4-5-20251001") == ("haiku", 0)

    def test_sonnet_model_id(self) -> None:
        assert resolve_model_family("claude-sonnet-4-6") == ("sonnet", 1)

    def test_opus_model_id(self) -> None:
        assert resolve_model_family("claude-opus-4-6") == ("opus", 2)

    def test_fable_model_id(self) -> None:
        assert resolve_model_family("claude-fable-1-0") == ("fable", 3)

    def test_mythos_canonicalises_to_fable(self) -> None:
        assert resolve_model_family("claude-mythos-1-0") == ("fable", 3)

    def test_case_insensitive(self) -> None:
        assert resolve_model_family("CLAUDE-OPUS-4-6") == ("opus", 2)

    def test_unknown_model_id_returns_none(self) -> None:
        assert resolve_model_family("some-future-model-9-9") is None

    def test_empty_model_id_returns_none(self) -> None:
        assert resolve_model_family("") is None


class TestReadHighWater:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert read_high_water(tmp_path, "sess-a") is None

    def test_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "sess-a.json"
        path.write_text("not json", encoding="utf-8")
        assert read_high_water(tmp_path, "sess-a") is None

    def test_malformed_schema_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "sess-a.json"
        path.write_text(json.dumps({"high_water_family": "opus"}), encoding="utf-8")
        assert read_high_water(tmp_path, "sess-a") is None

    def test_valid_file_round_trips(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "sess-a", "fable", 3)
        assert read_high_water(tmp_path, "sess-a") == ("fable", 3)


class TestWriteHighWater:
    def test_write_creates_directory(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "nested"
        write_high_water(target_dir, "sess-a", "opus", 2)
        assert (target_dir / "sess-a.json").exists()

    def test_write_leaves_no_stray_tmp_file(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "sess-a", "opus", 2)
        leftovers = list(tmp_path.glob(".*.tmp"))
        assert leftovers == []

    def test_write_is_readable_back(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "sess-a", "opus", 2)
        entry = json.loads((tmp_path / "sess-a.json").read_text(encoding="utf-8"))
        assert entry["high_water_family"] == "opus"
        assert entry["high_water_rank"] == 2


class TestStateDir:
    def test_returns_subdirectory_of_daemon_untracked_dir(self, tmp_path: Path) -> None:
        result = state_dir(tmp_path)
        assert result.parent == tmp_path
        assert result.name == "downgrade-indicator"


class TestEvaluateDowngrade:
    def test_first_render_sets_high_water_and_reports_no_downgrade(self, tmp_path: Path) -> None:
        result = evaluate_downgrade(tmp_path, "sess-a", "fable", 3)
        assert result is None
        assert read_high_water(tmp_path, "sess-a") == ("fable", 3)

    def test_render_on_lower_rank_than_high_water_reports_downgrade(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "sess-a", "fable", 3)
        result = evaluate_downgrade(tmp_path, "sess-a", "opus", 2)
        assert result == ("fable", "opus")
        # A downgrade render must NOT clobber the recorded high-water.
        assert read_high_water(tmp_path, "sess-a") == ("fable", 3)

    def test_render_back_on_high_water_family_reports_recovery_not_downgrade(
        self, tmp_path: Path
    ) -> None:
        write_high_water(tmp_path, "sess-a", "fable", 3)
        evaluate_downgrade(tmp_path, "sess-a", "opus", 2)
        result = evaluate_downgrade(tmp_path, "sess-a", "fable", 3)
        assert result is None
        assert read_high_water(tmp_path, "sess-a") == ("fable", 3)

    def test_render_at_session_start_on_the_high_water_model_is_never_a_downgrade(
        self, tmp_path: Path
    ) -> None:
        # A session that STARTS on opus (nothing stored yet) must never be
        # mislabelled a downgrade just because opus outranks haiku/sonnet.
        result = evaluate_downgrade(tmp_path, "sess-a", "opus", 2)
        assert result is None

    def test_equal_rank_reports_no_downgrade(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "sess-a", "opus", 2)
        result = evaluate_downgrade(tmp_path, "sess-a", "opus", 2)
        assert result is None

    def test_sessions_are_isolated(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "sess-a", "fable", 3)
        # A DIFFERENT session starting fresh on opus must not see sess-a's
        # high-water and must not be flagged as downgraded.
        result = evaluate_downgrade(tmp_path, "sess-b", "opus", 2)
        assert result is None
        assert read_high_water(tmp_path, "sess-b") == ("opus", 2)


class TestDowngradeCounts:
    """Per-session tally of downgrade EPISODES and recoveries (Plan 00278).

    Counts transitions, not renders: a sustained downgrade increments the
    downgrade count exactly once, and a return to (or above) the high-water
    increments the recovery count exactly once. A stuck session then shows
    downgrades > recoveries, which is the signal the status line surfaces.
    """

    def test_counts_start_at_zero(self, tmp_path: Path) -> None:
        evaluate_downgrade(tmp_path, "s", "fable", 3)
        assert read_downgrade_counts(tmp_path, "s") == (0, 0)

    def test_missing_state_reports_zero_counts(self, tmp_path: Path) -> None:
        assert read_downgrade_counts(tmp_path, "s") == (0, 0)

    def test_downgrade_increments_once_per_episode(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "s", "fable", 3)
        assert evaluate_downgrade(tmp_path, "s", "opus", 2) == ("fable", "opus")
        # A SUSTAINED downgrade (another render on the same lower family) must
        # not double-count the same episode.
        evaluate_downgrade(tmp_path, "s", "opus", 2)
        assert read_downgrade_counts(tmp_path, "s") == (1, 0)

    def test_recovery_increments_recovery_count(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "s", "fable", 3)
        evaluate_downgrade(tmp_path, "s", "opus", 2)
        evaluate_downgrade(tmp_path, "s", "fable", 3)
        assert read_downgrade_counts(tmp_path, "s") == (1, 1)

    def test_flapping_counts_each_episode_and_shows_stuck(self, tmp_path: Path) -> None:
        write_high_water(tmp_path, "s", "fable", 3)
        evaluate_downgrade(tmp_path, "s", "opus", 2)  # down 1
        evaluate_downgrade(tmp_path, "s", "fable", 3)  # up 1
        evaluate_downgrade(tmp_path, "s", "opus", 2)  # down 2 — and stays there
        # down (2) > up (1): the session is currently stranded on the lower model.
        assert read_downgrade_counts(tmp_path, "s") == (2, 1)

    def test_climbing_above_prior_high_while_downgraded_counts_recovery(
        self, tmp_path: Path
    ) -> None:
        write_high_water(tmp_path, "s", "opus", 2)
        evaluate_downgrade(tmp_path, "s", "sonnet", 1)  # down 1
        # Jump straight to a NEW high (fable outranks the opus high-water):
        # still a recovery from the open episode.
        evaluate_downgrade(tmp_path, "s", "fable", 3)
        assert read_downgrade_counts(tmp_path, "s") == (1, 1)
        assert read_high_water(tmp_path, "s") == ("fable", 3)

    def test_legacy_state_without_count_fields_reads_zero(self, tmp_path: Path) -> None:
        # A state file written before this feature (only family/rank) must read
        # back as zero counts, never raise.
        write_high_water(tmp_path, "s", "fable", 3)
        raw = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
        assert "downgrade_count" not in raw  # write_high_water stays minimal
        assert read_downgrade_counts(tmp_path, "s") == (0, 0)
