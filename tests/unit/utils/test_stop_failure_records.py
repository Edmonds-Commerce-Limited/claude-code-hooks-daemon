"""The daemon's record of StopFailure events (Plan 00470 Task 3.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.stop_failure_records import (
    MAX_RECORDS,
    RECORDED_ERRORS,
    StopFailureRecord,
    default_records_path,
    latest_unresolved,
    read_records,
    record_failure,
    resolve_session,
)

_NOW = 1_000_000.0


def _record(
    session_id: str = "s1",
    error: str = "rate_limit",
    recorded_at: float = _NOW,
    resolved_at: float | None = None,
) -> StopFailureRecord:
    return StopFailureRecord(
        session_id=session_id, error=error, recorded_at=recorded_at, resolved_at=resolved_at
    )


class TestRecordedErrors:
    def test_exactly_the_three_errors_the_plan_names(self) -> None:
        assert RECORDED_ERRORS == {
            "rate_limit",
            "authentication_failed",
            "cloud_credential_error",
        }


class TestRecording:
    def test_a_failure_is_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        assert record_failure(path, _record()) is True
        assert read_records(path) == [_record()]

    def test_records_accumulate_in_order(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _record(recorded_at=1.0))
        record_failure(path, _record(session_id="s2", recorded_at=2.0))
        assert [r.recorded_at for r in read_records(path)] == [1.0, 2.0]

    def test_history_is_bounded_to_the_newest_records(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        for index in range(MAX_RECORDS + 5):
            record_failure(path, _record(recorded_at=float(index)))
        kept = read_records(path)
        assert len(kept) == MAX_RECORDS
        assert kept[0].recorded_at == 5.0
        assert kept[-1].recorded_at == float(MAX_RECORDS + 4)

    def test_an_unwritable_location_reports_false(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        assert record_failure(blocker / "stop-failures.json", _record()) is False


class TestReading:
    def test_a_missing_file_reads_as_empty(self, tmp_path: Path) -> None:
        assert read_records(tmp_path / "absent.json") == []

    def test_a_corrupt_file_reads_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        path.write_text("{not json", encoding="utf-8")
        assert read_records(path) == []

    def test_a_non_object_document_reads_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        path.write_text("[1, 2]", encoding="utf-8")
        assert read_records(path) == []

    def test_malformed_entries_are_skipped_and_good_ones_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        good = {"session_id": "s1", "error": "rate_limit", "recorded_at": 5.0}
        path.write_text(
            json.dumps(
                {
                    "records": [
                        "nope",
                        {"session_id": 1, "error": "rate_limit", "recorded_at": 5.0},
                        {"session_id": "s1", "error": "rate_limit", "recorded_at": True},
                        {**good, "resolved_at": "later"},
                        good,
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert read_records(path) == [_record(recorded_at=5.0)]


class TestNonFiniteTimestamps:
    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    @pytest.mark.parametrize("field", ["recorded_at", "resolved_at"])
    def test_a_non_finite_timestamp_reads_as_no_record(
        self, tmp_path: Path, literal: str, field: str
    ) -> None:
        path = tmp_path / "records.json"
        recorded = literal if field == "recorded_at" else "1.0"
        resolved = literal if field == "resolved_at" else "null"
        path.write_text(
            '{"records": [{"session_id": "s1", "error": "rate_limit", '
            f'"recorded_at": {recorded}, "resolved_at": {resolved}}}]}}',
            encoding="utf-8",
        )
        assert read_records(path) == []


class TestResolving:
    def test_a_resolved_failure_is_no_longer_unresolved(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _record())
        assert resolve_session(path, "s1", now=_NOW + 10) is True
        assert latest_unresolved(path, "s1") is None
        assert read_records(path)[0].resolved_at == _NOW + 10

    def test_only_the_named_session_is_resolved(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _record(session_id="s1"))
        record_failure(path, _record(session_id="s2"))
        resolve_session(path, "s1", now=_NOW + 10)
        assert latest_unresolved(path, "s2") is not None

    def test_nothing_to_resolve_writes_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        assert resolve_session(path, "s1", now=_NOW) is True
        assert not path.exists()

    def test_an_already_resolved_failure_keeps_its_first_resolution_time(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _record())
        resolve_session(path, "s1", now=_NOW + 10)
        resolve_session(path, "s1", now=_NOW + 99)
        assert read_records(path)[0].resolved_at == _NOW + 10

    def test_a_new_failure_after_resolution_is_unresolved_again(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _record(recorded_at=1.0))
        resolve_session(path, "s1", now=2.0)
        record_failure(path, _record(error="authentication_failed", recorded_at=3.0))
        latest = latest_unresolved(path, "s1")
        assert latest is not None
        assert latest.error == "authentication_failed"


class TestLatestUnresolved:
    def test_the_newest_unresolved_failure_of_the_session_wins(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _record(recorded_at=1.0))
        record_failure(path, _record(error="cloud_credential_error", recorded_at=2.0))
        record_failure(path, _record(session_id="other", recorded_at=3.0))
        latest = latest_unresolved(path, "s1")
        assert latest is not None
        assert latest.error == "cloud_credential_error"

    def test_none_when_the_session_has_no_failures(self, tmp_path: Path) -> None:
        assert latest_unresolved(tmp_path / "absent.json", "s1") is None


class TestDefaultPath:
    def test_none_without_a_project_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ProjectContext, "is_initialized", classmethod(lambda cls: False))
        assert default_records_path() is None

    def test_under_the_daemon_untracked_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(ProjectContext, "is_initialized", classmethod(lambda cls: True))
        monkeypatch.setattr(
            ProjectContext, "daemon_untracked_dir", classmethod(lambda cls: tmp_path)
        )
        assert default_records_path() == tmp_path / "stop-failures.json"
