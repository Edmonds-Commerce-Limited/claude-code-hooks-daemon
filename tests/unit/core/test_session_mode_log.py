"""Tests for the session-mode transition log (Plan 00501 Task 4.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.session_mode_log import (
    CORRUPT_SUFFIX,
    ModeTransition,
    TransitionAction,
    TransitionLog,
    TransitionLogError,
)
from claude_code_hooks_daemon.utils.session_modes import ModeLabel


def _transition(n: int, *, session_id: str = "s-1") -> ModeTransition:
    return ModeTransition(
        at=1_000.0 + n,
        session_id=session_id,
        label=ModeLabel.FOCUS,
        action=TransitionAction.ENTER,
        evidence=f"evidence {n}",
        detail=f"task {n}",
    )


class TestModeTransition:
    def test_record_round_trip(self) -> None:
        transition = _transition(1)
        assert ModeTransition.from_record(transition.to_record()) == transition

    def test_blank_evidence_is_refused(self) -> None:
        with pytest.raises(ValueError, match="evidence"):
            ModeTransition(
                at=1.0,
                session_id="s",
                label=ModeLabel.FOCUS,
                action=TransitionAction.EXIT,
                evidence="  ",
            )

    def test_blank_session_is_refused(self) -> None:
        with pytest.raises(ValueError, match="session"):
            ModeTransition(
                at=1.0,
                session_id=" ",
                label=ModeLabel.FOCUS,
                action=TransitionAction.EXIT,
                evidence="x",
            )

    @pytest.mark.parametrize(
        "record",
        [
            "not a dict",
            {"at": 1.0},
            {
                "at": "soon",
                "session_id": "s",
                "label": "focus",
                "action": "enter",
                "evidence": "x",
                "detail": "",
            },
            {
                "at": 1.0,
                "session_id": "s",
                "label": "nonsense",
                "action": "enter",
                "evidence": "x",
                "detail": "",
            },
            {
                "at": 1.0,
                "session_id": "s",
                "label": "focus",
                "action": "enter",
                "evidence": "x",
                "detail": 3,
            },
            {
                "at": True,
                "session_id": "s",
                "label": "focus",
                "action": "enter",
                "evidence": "x",
                "detail": "",
            },
        ],
    )
    def test_malformed_record_is_a_named_error(self, record: object) -> None:
        with pytest.raises(TransitionLogError):
            ModeTransition.from_record(record)

    def test_line_names_session_label_action_evidence_and_detail(self) -> None:
        line = _transition(1, session_id="abcdef0123456789").line()
        assert "abcdef01" in line
        assert "enter focus" in line
        assert "evidence 1" in line
        assert "task 1" in line
        assert "UTC" in line


class TestTransitionLog:
    def test_missing_log_reads_as_no_transitions(self, tmp_path: Path) -> None:
        assert TransitionLog(tmp_path / "log.jsonl").recent(10) == []

    def test_append_then_read_in_order(self, tmp_path: Path) -> None:
        log = TransitionLog(tmp_path / "sub" / "log.jsonl")
        log.append([_transition(1), _transition(2)])
        log.append([_transition(3)])
        assert [t.at for t in log.recent(10)] == [1001.0, 1002.0, 1003.0]

    def test_recent_limits_to_the_newest(self, tmp_path: Path) -> None:
        log = TransitionLog(tmp_path / "log.jsonl")
        log.append([_transition(n) for n in range(5)])
        assert [t.at for t in log.recent(2)] == [1003.0, 1004.0]

    def test_recent_filters_by_session(self, tmp_path: Path) -> None:
        log = TransitionLog(tmp_path / "log.jsonl")
        log.append([_transition(1, session_id="a"), _transition(2, session_id="b")])
        assert [t.session_id for t in log.recent(10, session_id="b")] == ["b"]

    def test_recent_refuses_a_non_positive_limit(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="limit"):
            TransitionLog(tmp_path / "log.jsonl").recent(0)

    def test_log_is_bounded(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        log = TransitionLog(path, max_records=3)
        log.append([_transition(n) for n in range(5)])
        log.append([_transition(9)])
        assert [t.at for t in log.recent(10)] == [1003.0, 1004.0, 1009.0]
        assert len(path.read_text(encoding="utf-8").splitlines()) == 3

    def test_max_records_must_be_positive(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="max_records"):
            TransitionLog(tmp_path / "log.jsonl", max_records=0)

    def test_append_nothing_writes_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        TransitionLog(path).append([])
        assert not path.exists()

    def test_append_leaves_no_temp_file(self, tmp_path: Path) -> None:
        log = TransitionLog(tmp_path / "log.jsonl")
        log.append([_transition(1)])
        assert [p.name for p in tmp_path.iterdir()] == ["log.jsonl"]

    def test_corrupt_log_is_a_named_error_on_read(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text("{not json\n", encoding="utf-8")
        with pytest.raises(TransitionLogError, match="log.jsonl"):
            TransitionLog(path).recent(5)

    def test_unreadable_log_is_a_named_error_on_read(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.mkdir()
        with pytest.raises(TransitionLogError, match="cannot read"):
            TransitionLog(path).recent(5)

    def test_append_over_a_corrupt_log_quarantines_it(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text(json.dumps({"at": 1}) + "\n", encoding="utf-8")
        log = TransitionLog(path)
        log.append([_transition(1)])
        assert (tmp_path / f"log.jsonl{CORRUPT_SUFFIX}").exists()
        assert [t.at for t in log.recent(5)] == [1001.0]
        assert "corrupt" in caplog.text.lower()

    def test_failed_write_raises_and_leaves_no_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = TransitionLog(tmp_path / "log.jsonl")

        def refuse(self: Path, target: Path) -> Path:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "replace", refuse)
        with pytest.raises(OSError, match="disk full"):
            log.append([_transition(1)])
        assert list(tmp_path.iterdir()) == []
