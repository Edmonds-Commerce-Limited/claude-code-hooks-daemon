"""The daemon's record of usage-limit resumes and limit-killed agents (Plan 00470 Task 3.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.limit_events import (
    KIND_AGENT_KILLED,
    MAX_DETAIL_CHARS,
    MAX_EVENTS,
    RESUME_KINDS,
    LimitEvent,
    default_events_path,
    mark_delivered,
    pending_events,
    read_events,
    record_event,
)

_NOW = 1_000_000.0


def _event(
    session_id: str = "s1",
    kind: str = "quota_auto_resume_fired",
    recorded_at: float = _NOW,
    detail: str = "",
    delivered_at: float | None = None,
) -> LimitEvent:
    return LimitEvent(
        session_id=session_id,
        kind=kind,
        recorded_at=recorded_at,
        detail=detail,
        delivered_at=delivered_at,
    )


class TestKinds:
    def test_the_resume_kinds_are_the_three_documented_notification_types(self) -> None:
        assert RESUME_KINDS == {
            "quota_auto_resume_fired",
            "quota_auto_resume_stale",
            "quota_auto_resume_disabled",
        }

    def test_an_agent_killed_event_is_not_a_resume_event(self) -> None:
        assert KIND_AGENT_KILLED not in RESUME_KINDS


class TestRecording:
    def test_an_event_is_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        assert record_event(path, _event()) is True
        assert read_events(path) == [_event()]

    def test_events_accumulate_in_order(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        record_event(path, _event(recorded_at=1.0))
        record_event(path, _event(session_id="s2", recorded_at=2.0))
        assert [e.recorded_at for e in read_events(path)] == [1.0, 2.0]

    def test_history_is_bounded_to_the_newest_events(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        for index in range(MAX_EVENTS + 5):
            record_event(path, _event(session_id=f"s{index}", recorded_at=float(index)))
        events = read_events(path)
        assert len(events) == MAX_EVENTS
        assert events[0].recorded_at == 5.0

    def test_an_undelivered_duplicate_is_not_recorded_twice(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        agent = _event(kind=KIND_AGENT_KILLED, detail="reviewer")
        record_event(path, agent)
        record_event(path, _event(kind=KIND_AGENT_KILLED, detail="reviewer", recorded_at=_NOW + 9))
        assert len(read_events(path)) == 1

    def test_a_delivered_duplicate_is_recorded_again(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        record_event(path, _event(kind=KIND_AGENT_KILLED, detail="reviewer"))
        mark_delivered(path, "s1", now=_NOW + 1)
        record_event(path, _event(kind=KIND_AGENT_KILLED, detail="reviewer", recorded_at=_NOW + 2))
        assert len(read_events(path)) == 2

    def test_the_same_detail_in_another_session_is_a_different_event(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        record_event(path, _event(kind=KIND_AGENT_KILLED, detail="reviewer"))
        record_event(path, _event(session_id="s2", kind=KIND_AGENT_KILLED, detail="reviewer"))
        assert len(read_events(path)) == 2

    def test_detail_is_truncated_on_write(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        record_event(path, _event(kind=KIND_AGENT_KILLED, detail="x" * (MAX_DETAIL_CHARS + 50)))
        assert len(read_events(path)[0].detail) == MAX_DETAIL_CHARS

    def test_an_unwritable_path_returns_false(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        assert record_event(blocker / "limit-events.json", _event()) is False


class TestReading:
    def test_a_missing_file_reads_as_empty(self, tmp_path: Path) -> None:
        assert read_events(tmp_path / "nope.json") == []

    def test_a_corrupt_file_reads_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        path.write_text("{not json", encoding="utf-8")
        assert read_events(path) == []

    def test_a_file_of_the_wrong_shape_reads_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        path.write_text(json.dumps(["x"]), encoding="utf-8")
        assert read_events(path) == []

    def test_malformed_entries_are_skipped_and_good_ones_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        good = {"session_id": "s1", "kind": "quota_auto_resume_fired", "recorded_at": 5.0}
        path.write_text(
            json.dumps(
                {
                    "events": [
                        "junk",
                        {"session_id": 7, "kind": "k", "recorded_at": 1.0},
                        {"session_id": "s1", "kind": "k", "recorded_at": "soon"},
                        {"session_id": "s1", "kind": "k", "recorded_at": True},
                        {"session_id": "s1", "kind": "k", "recorded_at": 1.0, "detail": 3},
                        {"session_id": "s1", "kind": "k", "recorded_at": 1.0, "delivered_at": "x"},
                        good,
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert read_events(path) == [_event(recorded_at=5.0)]

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e999"])
    def test_a_non_finite_or_unrepresentable_time_is_rejected(
        self, tmp_path: Path, bad: str
    ) -> None:
        path = tmp_path / "limit-events.json"
        path.write_text(
            '{"events": [{"session_id": "s1", "kind": "k", "recorded_at": ' + bad + "}]}",
            encoding="utf-8",
        )
        assert read_events(path) == []


class TestPendingAndDelivery:
    def test_pending_is_this_sessions_undelivered_events_oldest_first(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        record_event(path, _event(recorded_at=2.0))
        record_event(path, _event(kind=KIND_AGENT_KILLED, detail="a", recorded_at=1.0))
        record_event(path, _event(session_id="other", recorded_at=3.0))
        record_event(path, _event(recorded_at=4.0, delivered_at=5.0))
        assert [e.recorded_at for e in pending_events(path, "s1")] == [1.0, 2.0]

    def test_mark_delivered_stamps_only_this_sessions_undelivered_events(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "limit-events.json"
        record_event(path, _event(recorded_at=1.0))
        record_event(path, _event(session_id="other", recorded_at=2.0))
        assert mark_delivered(path, "s1", now=_NOW + 10) is True
        by_session = {e.session_id: e.delivered_at for e in read_events(path)}
        assert by_session == {"s1": _NOW + 10, "other": None}
        assert pending_events(path, "s1") == []

    def test_mark_delivered_does_not_touch_the_file_when_nothing_is_pending(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "limit-events.json"
        assert mark_delivered(path, "s1", now=_NOW) is True
        assert not path.exists()

    def test_mark_delivered_keeps_an_earlier_delivery_time(self, tmp_path: Path) -> None:
        path = tmp_path / "limit-events.json"
        record_event(path, _event(delivered_at=7.0))
        mark_delivered(path, "s1", now=99.0)
        assert read_events(path)[0].delivered_at == 7.0

    def test_mark_delivered_reports_a_failed_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "limit-events.json"
        record_event(path, _event())

        def _fail(_path: Path, _payload: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.utils.limit_events.write_json_atomically", _fail
        )
        assert mark_delivered(path, "s1", now=_NOW) is False
        assert pending_events(path, "s1") != []


class TestDefaultPath:
    def test_no_project_context_means_no_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ProjectContext, "is_initialized", classmethod(lambda cls: False))
        assert default_events_path() is None

    def test_the_path_is_under_the_daemon_untracked_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ProjectContext, "is_initialized", classmethod(lambda cls: True))
        monkeypatch.setattr(
            ProjectContext, "daemon_untracked_dir", classmethod(lambda cls: tmp_path)
        )
        assert default_events_path() == tmp_path / "limit-events.json"
