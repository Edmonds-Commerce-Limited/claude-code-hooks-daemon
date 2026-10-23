"""Tests for the human-input blockage marker (Plan 00298).

Nothing writes the marker any more: the awaiting-human state lives in the
session-modes registry, and the marker survives only as a file an older
daemon may have left on disk, which ``read_marker`` reads so it can be
imported. ``read_marker`` fails OPEN -- a missing or corrupt marker must
never raise, only degrade to "no marker". ``write_json_atomically`` is the
shared owner-only atomic write other record files use.
"""

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.blockage_marker import (
    MARKER_FILENAME,
    BlockageMarker,
    marker_is_valid,
    read_marker,
    write_json_atomically,
)


def _legacy_marker(path: Path, session_id: str, recorded_at: float) -> None:
    """Write a marker in the on-disk shape an older daemon recorded."""
    write_json_atomically(path, {"session_id": session_id, "recorded_at": recorded_at})


class TestReadMarker:
    def test_a_legacy_marker_reads_back(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        _legacy_marker(path, "session-1", 100.0)

        assert read_marker(path) == BlockageMarker(session_id="session-1", recorded_at=100.0)

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


class TestWriteJsonAtomically:
    def test_creates_missing_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / MARKER_FILENAME
        write_json_atomically(path, {"k": 1})

        assert json.loads(path.read_text(encoding="utf-8")) == {"k": 1}

    def test_is_owner_only(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        write_json_atomically(path, {"k": 1})

        assert path.stat().st_mode & 0o777 == 0o600

    def test_overwrites_an_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / MARKER_FILENAME
        _legacy_marker(path, "session-1", 1.0)
        _legacy_marker(path, "session-2", 2.0)

        assert read_marker(path) == BlockageMarker(session_id="session-2", recorded_at=2.0)

    def test_a_failed_write_raises(self, tmp_path: Path) -> None:
        # Parent is a FILE, not a directory: mkdir fails, and the caller is
        # told -- swallowing is the caller's decision, not this helper's.
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")

        with pytest.raises(OSError):
            write_json_atomically(blocker / MARKER_FILENAME, {"k": 1})


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
