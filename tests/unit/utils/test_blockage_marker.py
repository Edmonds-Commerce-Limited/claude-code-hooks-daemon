"""Tests for the human-input blockage marker (Plan 00298).

The marker is the shared primitive between ``auto_continue_stop`` (writer)
and ``failsafe_cron_blockage_suppressor`` (reader): a small JSON file
recording that a session stopped because it is blocked only on human input.
Every public function fails OPEN -- a missing/corrupt/unwritable marker must
never raise, only degrade to "no marker".
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.utils.blockage_marker import (
    MARKER_FILENAME,
    BlockageMarker,
    clear_marker,
    marker_is_valid,
    read_marker,
    write_marker,
)


class TestWriteAndReadMarker:
    def test_write_then_read_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        write_marker(path, "session-1", now=100.0)

        marker = read_marker(path)

        assert marker == BlockageMarker(session_id="session-1", recorded_at=100.0)

    def test_write_creates_missing_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / MARKER_FILENAME
        write_marker(path, "session-1", now=1.0)

        assert path.exists()

    def test_write_is_owner_only(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        write_marker(path, "session-1", now=1.0)

        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_write_overwrites_existing_marker(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        write_marker(path, "session-1", now=1.0)
        write_marker(path, "session-2", now=2.0)

        marker = read_marker(path)

        assert marker == BlockageMarker(session_id="session-2", recorded_at=2.0)

    def test_read_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert read_marker(tmp_path / MARKER_FILENAME) is None

    def test_read_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        path.write_text("{not json", encoding="utf-8")

        assert read_marker(path) is None

    def test_read_non_dict_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        assert read_marker(path) is None

    def test_read_missing_fields_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        path.write_text(json.dumps({"session_id": "x"}), encoding="utf-8")

        assert read_marker(path) is None

    def test_read_wrong_field_types_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        path.write_text(
            json.dumps({"session_id": 123, "recorded_at": "not-a-number"}), encoding="utf-8"
        )

        assert read_marker(path) is None

    def test_write_failure_does_not_raise(self, tmp_path: Path) -> None:
        # Parent is a FILE, not a directory: mkdir must fail, and write_marker
        # must swallow it (fail-open logging only), never raise.
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        path = blocker / MARKER_FILENAME

        write_marker(path, "session-1", now=1.0)  # must not raise

        assert not path.exists()


class TestClearMarker:
    def test_clear_removes_existing_marker(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        write_marker(path, "session-1", now=1.0)

        clear_marker(path)

        assert not path.exists()

    def test_clear_missing_marker_does_not_raise(self, tmp_path: Path) -> None:
        clear_marker(tmp_path / MARKER_FILENAME)  # must not raise

    def test_clear_unwritable_path_does_not_raise(self, tmp_path: Path) -> None:
        clear_marker(tmp_path)  # a directory, not a file -- unlink() fails


class TestMarkerIsValid:
    def test_none_marker_is_invalid(self) -> None:
        assert marker_is_valid(None, "session-1", now=100.0, expiry_seconds=3600.0) is False

    def test_same_session_within_expiry_is_valid(self) -> None:
        marker = BlockageMarker(session_id="session-1", recorded_at=100.0)
        assert marker_is_valid(marker, "session-1", now=200.0, expiry_seconds=3600.0) is True

    def test_different_session_is_invalid(self) -> None:
        marker = BlockageMarker(session_id="session-1", recorded_at=100.0)
        assert marker_is_valid(marker, "session-2", now=200.0, expiry_seconds=3600.0) is False

    def test_expired_marker_is_invalid(self) -> None:
        marker = BlockageMarker(session_id="session-1", recorded_at=0.0)
        assert marker_is_valid(marker, "session-1", now=4000.0, expiry_seconds=3600.0) is False

    def test_exactly_at_expiry_boundary_is_valid(self) -> None:
        marker = BlockageMarker(session_id="session-1", recorded_at=0.0)
        assert marker_is_valid(marker, "session-1", now=3600.0, expiry_seconds=3600.0) is True

    def test_future_recorded_at_is_invalid(self) -> None:
        # Clock skew / corrupt future timestamp -- fail open (never suppress).
        marker = BlockageMarker(session_id="session-1", recorded_at=500.0)
        assert marker_is_valid(marker, "session-1", now=100.0, expiry_seconds=3600.0) is False
