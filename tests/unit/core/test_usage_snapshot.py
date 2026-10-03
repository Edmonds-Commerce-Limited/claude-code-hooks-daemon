"""Tests for the subscription-usage snapshot (Plan 00479 Task 2.1)."""

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.data_layer import get_data_layer, latest_usage, reset_data_layer
from claude_code_hooks_daemon.core.usage_snapshot import (
    UsageSnapshot,
    UsageTracker,
    UsageWindow,
    usage_state_file,
)
from tests.support.status_usage import (
    FIVE_HOUR_RESETS_AT,
    NOW,
    SEVEN_DAY_RESETS_AT,
    load_status_payload,
)


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    """A state file path in a not-yet-created directory."""
    return tmp_path / "state" / "usage-snapshot.json"


class TestUpdate:
    """What a Status event contributes to the snapshot."""

    def test_integer_percentages_are_kept_per_window(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("main_thread_integer.json"), now=NOW)
        snap = tracker.latest(now=NOW)
        assert snap == UsageSnapshot(
            five_hour=UsageWindow(13.0, FIVE_HOUR_RESETS_AT, NOW),
            seven_day=UsageWindow(3.0, SEVEN_DAY_RESETS_AT, NOW),
        )

    def test_fractional_percentages_are_kept(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(
            load_status_payload("main_thread_fractional.json"), now=NOW
        )
        snap = tracker.latest(now=NOW)
        assert snap is not None
        assert snap.five_hour is not None and snap.five_hour.used_percentage == 67.4
        assert snap.seven_day is not None and snap.seven_day.used_percentage == 81.9

    def test_agent_thread_payload_is_read_like_the_main_thread(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("agent_thread.json"), now=NOW)
        snap = tracker.latest(now=NOW)
        assert snap is not None and snap.five_hour is not None
        assert snap.five_hour.used_percentage == 13.0

    def test_payload_before_first_response_leaves_no_snapshot(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("before_first_response.json"), now=NOW)
        assert tracker.latest(now=NOW) is None

    def test_payload_without_rate_limits_keeps_the_previous_snapshot(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("main_thread_integer.json"), now=NOW)
        tracker.update_from_status_event(
            load_status_payload("before_first_response.json"), now=NOW + 5
        )
        snap = tracker.latest(now=NOW + 5)
        assert snap is not None and snap.five_hour is not None
        assert snap.five_hour.observed_at == NOW

    def test_one_window_absent_updates_only_the_other(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("main_thread_integer.json"), now=NOW)
        tracker.update_from_status_event(load_status_payload("seven_day_only.json"), now=NOW + 5)
        snap = tracker.latest(now=NOW + 5)
        assert snap is not None
        assert snap.five_hour == UsageWindow(13.0, FIVE_HOUR_RESETS_AT, NOW)
        assert snap.seven_day == UsageWindow(42.0, SEVEN_DAY_RESETS_AT, NOW + 5)

    def test_newer_event_replaces_older_values(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("main_thread_integer.json"), now=NOW)
        tracker.update_from_status_event(
            load_status_payload("main_thread_fractional.json"), now=NOW + 9
        )
        snap = tracker.latest(now=NOW + 9)
        assert snap is not None and snap.five_hour is not None
        assert snap.five_hour.used_percentage == 67.4
        assert snap.five_hour.observed_at == NOW + 9

    @pytest.mark.parametrize(
        "window",
        [
            {"used_percentage": "13", "resets_at": 1800010800},
            {"used_percentage": True, "resets_at": 1800010800},
            {"used_percentage": -1, "resets_at": 1800010800},
            {"used_percentage": 101, "resets_at": 1800010800},
            {"used_percentage": float("nan"), "resets_at": 1800010800},
            {"used_percentage": 13, "resets_at": "soon"},
            {"used_percentage": 13, "resets_at": 0},
            {"used_percentage": 13},
            {"resets_at": 1800010800},
            "not-a-dict",
            None,
        ],
    )
    def test_malformed_window_is_ignored(self, window: Any) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event({"rate_limits": {"five_hour": window}}, now=NOW)
        assert tracker.latest(now=NOW) is None

    def test_non_dict_rate_limits_is_ignored(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event({"rate_limits": "x"}, now=NOW)
        assert tracker.latest(now=NOW) is None

    def test_spend_limit_and_unknown_keys_are_ignored(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(
            {"rate_limits": {"spend_limit": {"used_percentage": 140, "resets_at": 1800010800}}},
            now=NOW,
        )
        assert tracker.latest(now=NOW) is None

    def test_reset_clears_memory(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("main_thread_integer.json"), now=NOW)
        tracker.reset()
        assert tracker.latest(now=NOW) is None


class TestExpiry:
    """A window past its ``resets_at`` reads as absent."""

    def test_expired_window_is_absent_and_the_other_survives(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("five_hour_expired.json"), now=NOW)
        snap = tracker.latest(now=NOW)
        assert snap is not None
        assert snap.five_hour is None
        assert snap.seven_day is not None

    def test_window_expires_when_time_passes(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("main_thread_integer.json"), now=NOW)
        later = FIVE_HOUR_RESETS_AT + 1
        snap = tracker.latest(now=later)
        assert snap is not None
        assert snap.five_hour is None
        assert snap.seven_day is not None

    def test_reset_instant_itself_counts_as_expired(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("main_thread_integer.json"), now=NOW)
        snap = tracker.latest(now=float(FIVE_HOUR_RESETS_AT))
        assert snap is not None and snap.five_hour is None

    def test_all_windows_expired_gives_none(self) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(load_status_payload("main_thread_integer.json"), now=NOW)
        assert tracker.latest(now=SEVEN_DAY_RESETS_AT + 1.0) is None


class TestWindowHelpers:
    """Small accessors a later handler relies on."""

    def test_seconds_until_reset(self) -> None:
        window = UsageWindow(13.0, FIVE_HOUR_RESETS_AT, NOW)
        assert window.seconds_until_reset(NOW) == 10_800

    def test_seconds_until_reset_never_negative(self) -> None:
        window = UsageWindow(13.0, FIVE_HOUR_RESETS_AT, NOW)
        assert window.seconds_until_reset(FIVE_HOUR_RESETS_AT + 50.0) == 0

    def test_highest_used_percentage(self) -> None:
        snap = UsageSnapshot(UsageWindow(10.0, 5, 0.0), UsageWindow(80.0, 5, 0.0))
        assert snap.highest_used_percentage() == 80.0

    def test_highest_used_percentage_with_one_window(self) -> None:
        assert UsageSnapshot(None, UsageWindow(7.0, 5, 0.0)).highest_used_percentage() == 7.0


class TestPersistence:
    """The snapshot is persisted host-wide, atomically, and fails open."""

    def test_update_writes_the_file(self, state_file: Path) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(
            load_status_payload("main_thread_integer.json"), now=NOW, state_file=state_file
        )
        data = json.loads(state_file.read_text("utf-8"))
        assert data["five_hour"] == {
            "used_percentage": 13.0,
            "resets_at": FIVE_HOUR_RESETS_AT,
            "observed_at": NOW,
        }
        assert data["seven_day"]["used_percentage"] == 3.0

    def test_no_temp_files_left_behind(self, state_file: Path) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(
            load_status_payload("main_thread_integer.json"), now=NOW, state_file=state_file
        )
        assert [p.name for p in state_file.parent.iterdir()] == [state_file.name]

    def test_failed_rename_leaves_no_temp_file_behind(
        self, state_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A non-empty directory where the snapshot belongs makes the rename fail.
        state_file.mkdir(parents=True)
        (state_file / "occupant").write_text("x", "utf-8")
        tracker = UsageTracker()
        with caplog.at_level("WARNING"):
            tracker.update_from_status_event(
                load_status_payload("main_thread_integer.json"), now=NOW, state_file=state_file
            )
        assert "usage snapshot" in caplog.text.lower()
        assert [p.name for p in state_file.parent.iterdir()] == [state_file.name]

    def test_fresh_tracker_reads_the_file(self, state_file: Path) -> None:
        UsageTracker().update_from_status_event(
            load_status_payload("main_thread_integer.json"), now=NOW, state_file=state_file
        )
        snap = UsageTracker().latest(now=NOW + 1, state_file=state_file)
        assert snap is not None and snap.five_hour is not None
        assert snap.five_hour.used_percentage == 13.0
        assert snap.five_hour.observed_at == NOW

    def test_file_window_past_its_reset_is_absent(self, state_file: Path) -> None:
        UsageTracker().update_from_status_event(
            load_status_payload("main_thread_integer.json"), now=NOW, state_file=state_file
        )
        snap = UsageTracker().latest(now=FIVE_HOUR_RESETS_AT + 1.0, state_file=state_file)
        assert snap is not None and snap.five_hour is None

    def test_memory_wins_over_the_file(self, state_file: Path) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(
            load_status_payload("main_thread_integer.json"), now=NOW, state_file=state_file
        )
        state_file.write_text(json.dumps({"five_hour": {"used_percentage": 99}}), "utf-8")
        snap = tracker.latest(now=NOW, state_file=state_file)
        assert snap is not None and snap.five_hour is not None
        assert snap.five_hour.used_percentage == 13.0

    def test_unchanged_snapshot_is_not_rewritten_within_the_heartbeat(
        self, state_file: Path
    ) -> None:
        tracker = UsageTracker()
        payload = load_status_payload("main_thread_integer.json")
        tracker.update_from_status_event(payload, now=NOW, state_file=state_file)
        state_file.write_text("sentinel", "utf-8")
        tracker.update_from_status_event(payload, now=NOW + 1, state_file=state_file)
        assert state_file.read_text("utf-8") == "sentinel"

    def test_unchanged_snapshot_is_rewritten_after_the_heartbeat(self, state_file: Path) -> None:
        tracker = UsageTracker()
        payload = load_status_payload("main_thread_integer.json")
        tracker.update_from_status_event(payload, now=NOW, state_file=state_file)
        state_file.write_text("sentinel", "utf-8")
        tracker.update_from_status_event(payload, now=NOW + 61, state_file=state_file)
        data = json.loads(state_file.read_text("utf-8"))
        assert data["five_hour"]["observed_at"] == NOW + 61

    def test_changed_snapshot_is_rewritten_at_once(self, state_file: Path) -> None:
        tracker = UsageTracker()
        tracker.update_from_status_event(
            load_status_payload("main_thread_integer.json"), now=NOW, state_file=state_file
        )
        tracker.update_from_status_event(
            load_status_payload("main_thread_fractional.json"), now=NOW + 1, state_file=state_file
        )
        data = json.loads(state_file.read_text("utf-8"))
        assert data["five_hour"]["used_percentage"] == 67.4

    def test_event_without_usage_writes_nothing(self, state_file: Path) -> None:
        UsageTracker().update_from_status_event(
            load_status_payload("before_first_response.json"), now=NOW, state_file=state_file
        )
        assert not state_file.exists()

    @pytest.mark.parametrize(
        "text",
        ["", "not json", "[]", '{"five_hour": "x"}', '{"five_hour": {"used_percentage": 5}}'],
    )
    def test_unreadable_file_reads_as_no_data(self, state_file: Path, text: str) -> None:
        state_file.parent.mkdir(parents=True)
        state_file.write_text(text, "utf-8")
        assert UsageTracker().latest(now=NOW, state_file=state_file) is None

    def test_missing_file_reads_as_no_data(self, state_file: Path) -> None:
        assert UsageTracker().latest(now=NOW, state_file=state_file) is None

    def test_write_failure_fails_open_and_keeps_memory(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where a directory is needed", "utf-8")
        tracker = UsageTracker()
        with caplog.at_level("WARNING"):
            tracker.update_from_status_event(
                load_status_payload("main_thread_integer.json"),
                now=NOW,
                state_file=blocker / "usage-snapshot.json",
            )
        assert "usage snapshot" in caplog.text.lower()
        assert tracker.latest(now=NOW) is not None

    def test_write_failure_is_not_retried_every_event(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("x", "utf-8")
        tracker = UsageTracker()
        payload = load_status_payload("main_thread_integer.json")
        with caplog.at_level("WARNING"):
            for offset in range(5):
                tracker.update_from_status_event(
                    payload, now=NOW + offset, state_file=blocker / "u.json"
                )
        assert caplog.text.lower().count("usage snapshot") == 1

    def test_concurrent_updates_do_not_corrupt_the_file(self, state_file: Path) -> None:
        tracker = UsageTracker()
        payloads = [
            load_status_payload("main_thread_integer.json"),
            load_status_payload("agent_thread.json"),
        ]

        def worker(index: int) -> None:
            for step in range(20):
                tracker.update_from_status_event(
                    payloads[index], now=NOW + step * 100, state_file=state_file
                )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert json.loads(state_file.read_text("utf-8"))["five_hour"]["used_percentage"] == 13.0


class TestStateFile:
    """Where the host-wide file lives."""

    def test_lives_directly_in_the_daemon_untracked_dir(self, tmp_path: Path) -> None:
        assert usage_state_file(tmp_path) == tmp_path / "usage-snapshot.json"


class TestDataLayerAccessor:
    """``latest_usage()`` is the accessor later handlers call."""

    @pytest.fixture(autouse=True)
    def _fresh_layer(self) -> Any:
        reset_data_layer()
        yield
        reset_data_layer()

    def test_returns_none_before_any_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.core.data_layer.resolve_usage_state_file", lambda: None
        )
        assert latest_usage(now=NOW) is None

    def test_returns_what_the_data_layer_tracker_holds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.core.data_layer.resolve_usage_state_file", lambda: None
        )
        get_data_layer().usage.update_from_status_event(
            load_status_payload("main_thread_integer.json"), now=NOW
        )
        snap = latest_usage(now=NOW)
        assert snap is not None and snap.five_hour is not None
        assert snap.five_hour.used_percentage == 13.0

    def test_falls_back_to_the_host_wide_file(
        self, monkeypatch: pytest.MonkeyPatch, state_file: Path
    ) -> None:
        UsageTracker().update_from_status_event(
            load_status_payload("main_thread_integer.json"), now=NOW, state_file=state_file
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.core.data_layer.resolve_usage_state_file",
            lambda: state_file,
        )
        snap = latest_usage(now=NOW + 1)
        assert snap is not None and snap.seven_day is not None
        assert snap.seven_day.used_percentage == 3.0
