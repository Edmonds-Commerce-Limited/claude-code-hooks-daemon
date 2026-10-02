"""Plan 00479 Task 4.5: the ``<session>.usage-paused`` record (daemon side).

The record is the interface between the daemon's usage gate (writer, clearer)
and the standalone ccy supervisor (reader, in ``.claude/ccy/claude-supervise.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils import usage_pause
from claude_code_hooks_daemon.utils.usage_pause import UsagePause

_SESSION = "sess-abc"
_NOW = 1_000_000.0


def _pause(**overrides: Any) -> UsagePause:  # Any: deliberately wrong-typed values are tested
    fields: dict[str, Any] = {
        "session_id": _SESSION,
        "paused_at": _NOW,
        "resume_at": _NOW + 3600.0,
        "window": usage_pause.WINDOW_FIVE_HOUR,
        "used_percentage": 91.5,
        "ceiling": 90.0,
        "reason": "five_hour window at 91.5% (ceiling 90%)",
    }
    fields.update(overrides)
    return UsagePause(**fields)


class TestPath:
    def test_lives_in_the_context_sidecar_dir_named_per_session(self, tmp_path: Path) -> None:
        path = usage_pause.pause_path(tmp_path, _SESSION)
        assert path == tmp_path / "context-sidecar" / "sess-abc.usage-paused"

    def test_suffix_is_not_json_so_the_sidecar_reader_ignores_it(self) -> None:
        assert not usage_pause.SIGNAL_SUFFIX.endswith(".json")

    def test_unsafe_session_characters_cannot_steer_the_path(self, tmp_path: Path) -> None:
        path = usage_pause.pause_path(tmp_path, "../../etc/passwd")
        assert path.parent == tmp_path / "context-sidecar"
        assert "/" not in path.name

    def test_empty_session_id_uses_the_fallback_stem(self, tmp_path: Path) -> None:
        assert usage_pause.pause_path(tmp_path, "").name == "unknown.usage-paused"


class TestWrite:
    def test_round_trips_every_field(self, tmp_path: Path) -> None:
        pause = _pause()
        path = usage_pause.write_usage_pause(tmp_path, pause)
        assert path == usage_pause.pause_path(tmp_path, _SESSION)
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW + 1) == pause

    def test_on_disk_fields_are_the_documented_names(self, tmp_path: Path) -> None:
        path = usage_pause.write_usage_pause(tmp_path, _pause())
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) == {
            "session_id",
            "paused_at",
            "resume_at",
            "window",
            "used_percentage",
            "ceiling",
            "reason",
        }

    def test_overwrites_an_earlier_record(self, tmp_path: Path) -> None:
        usage_pause.write_usage_pause(tmp_path, _pause())
        later = _pause(paused_at=_NOW + 10, resume_at=_NOW + 7200, window="seven_day")
        usage_pause.write_usage_pause(tmp_path, later)
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW + 11) == later

    def test_leaves_no_temp_file_behind(self, tmp_path: Path) -> None:
        usage_pause.write_usage_pause(tmp_path, _pause())
        names = [p.name for p in (tmp_path / "context-sidecar").iterdir()]
        assert names == ["sess-abc.usage-paused"]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"session_id": ""},
            {"window": "monthly"},
            {"resume_at": _NOW},
            {"resume_at": _NOW - 1},
            {"used_percentage": float("nan")},
            {"ceiling": float("inf")},
            {"used_percentage": True},
            {"reason": ""},
        ],
    )
    def test_refuses_a_record_the_supervisor_would_reject(
        self, tmp_path: Path, overrides: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError):
            usage_pause.write_usage_pause(tmp_path, _pause(**overrides))
        assert not usage_pause.pause_path(tmp_path, _SESSION).exists()

    def test_write_failure_raises_oserror(self, tmp_path: Path) -> None:
        blocker = tmp_path / "context-sidecar"
        blocker.write_text("a file where the directory should be", encoding="utf-8")
        with pytest.raises(OSError):
            usage_pause.write_usage_pause(tmp_path, _pause())


class TestRead:
    def test_missing_record_is_no_pause(self, tmp_path: Path) -> None:
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW) is None

    def test_other_sessions_record_is_no_pause(self, tmp_path: Path) -> None:
        usage_pause.write_usage_pause(tmp_path, _pause(session_id="other"))
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW + 1) is None

    def test_record_naming_another_session_in_this_file_is_no_pause(self, tmp_path: Path) -> None:
        path = usage_pause.write_usage_pause(tmp_path, _pause())
        data = json.loads(path.read_text(encoding="utf-8"))
        data["session_id"] = "forged"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW + 1) is None

    @pytest.mark.parametrize("content", ["", "not json", "[]", '{"paused_at": "x"}', "null"])
    def test_corrupt_record_is_no_pause_and_logged(
        self, tmp_path: Path, content: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = usage_pause.pause_path(tmp_path, _SESSION)
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
        with caplog.at_level("WARNING"):
            assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW) is None
        assert "usage_pause" in caplog.text

    def test_empty_session_id_reads_nothing(self, tmp_path: Path) -> None:
        usage_pause.write_usage_pause(tmp_path, _pause())
        assert usage_pause.read_usage_pause(tmp_path, "", now=_NOW + 1) is None

    def test_future_dated_record_is_no_pause(self, tmp_path: Path) -> None:
        usage_pause.write_usage_pause(tmp_path, _pause())
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW - 5) is None


class TestFailsOpenOnAnyReadError:
    """Plan 00479 M1: a record that cannot be read is never a pause and never raises."""

    def test_the_read_never_asks_exists_which_raises_on_eacces(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pause = _pause()
        usage_pause.write_usage_pause(tmp_path, pause)

        def deny(self: Path, *args: Any, **kwargs: Any) -> bool:
            raise PermissionError("EACCES")

        monkeypatch.setattr(Path, "exists", deny)
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW + 1) == pause

    def test_read_text_raising_permission_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        usage_pause.write_usage_pause(tmp_path, _pause())

        def deny(self: Path, *args: Any, **kwargs: Any) -> str:
            raise PermissionError("EACCES")

        monkeypatch.setattr(Path, "read_text", deny)
        with caplog.at_level("WARNING"):
            assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW + 1) is None
        assert "usage_pause" in caplog.text

    def test_a_missing_record_is_silent(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW) is None
        assert caplog.text == ""


class TestSpanCap:
    """Plan 00479 M4: a record cannot pause a session for longer than the cap."""

    def test_the_cap_is_eight_days(self) -> None:
        assert usage_pause.MAX_PAUSE_SPAN_SECONDS == 8 * 86400.0

    def test_refuses_to_write_a_record_beyond_the_cap(self, tmp_path: Path) -> None:
        too_far = _pause(resume_at=_NOW + usage_pause.MAX_PAUSE_SPAN_SECONDS + 1)
        with pytest.raises(ValueError):
            usage_pause.write_usage_pause(tmp_path, too_far)

    def test_a_record_at_the_cap_is_written(self, tmp_path: Path) -> None:
        at_cap = _pause(resume_at=_NOW + usage_pause.MAX_PAUSE_SPAN_SECONDS)
        usage_pause.write_usage_pause(tmp_path, at_cap)
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW + 1) == at_cap

    def test_a_hand_edited_record_beyond_the_cap_reads_as_no_pause(self, tmp_path: Path) -> None:
        path = usage_pause.write_usage_pause(tmp_path, _pause())
        data = json.loads(path.read_text(encoding="utf-8"))
        data["resume_at"] = _NOW + 10 * 365 * 86400.0
        path.write_text(json.dumps(data), encoding="utf-8")
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=_NOW + 1) is None


class TestLiveness:
    def test_live_until_resume_plus_grace(self) -> None:
        pause = _pause()
        end = pause.resume_at + usage_pause.PAUSE_GRACE_SECONDS
        assert pause.is_live(session_id=_SESSION, now=end) is True
        assert pause.is_live(session_id=_SESSION, now=end + 1) is False

    def test_a_record_left_by_a_crashed_gate_cannot_pause_forever(self, tmp_path: Path) -> None:
        usage_pause.write_usage_pause(tmp_path, _pause())
        stale_now = _NOW + 3600.0 + usage_pause.PAUSE_GRACE_SECONDS + 1
        assert usage_pause.read_usage_pause(tmp_path, _SESSION, now=stale_now) is None

    def test_wrong_session_is_not_live(self) -> None:
        assert _pause().is_live(session_id="other", now=_NOW + 1) is False


class TestClear:
    def test_removes_the_record_and_reports_it(self, tmp_path: Path) -> None:
        usage_pause.write_usage_pause(tmp_path, _pause())
        assert usage_pause.clear_usage_pause(tmp_path, _SESSION) is True
        assert not usage_pause.pause_path(tmp_path, _SESSION).exists()

    def test_absent_record_reports_false(self, tmp_path: Path) -> None:
        assert usage_pause.clear_usage_pause(tmp_path, _SESSION) is False

    def test_failure_to_remove_raises_oserror(self, tmp_path: Path) -> None:
        usage_pause.pause_path(tmp_path, _SESSION).mkdir(parents=True)
        with pytest.raises(OSError):
            usage_pause.clear_usage_pause(tmp_path, _SESSION)


class TestOwnerOverride:
    """Plan 00479 round 2 N4: ``usage-pause clear`` records an override marker.

    While it is valid no gate starts a pause for that session. It is per session, ends at
    ``until`` and is capped like a pause (:data:`MAX_PAUSE_SPAN_SECONDS`).
    """

    def test_lives_beside_the_pause_record_with_its_own_suffix(self, tmp_path: Path) -> None:
        path = usage_pause.override_path(tmp_path, _SESSION)
        assert path == tmp_path / "context-sidecar" / "sess-abc.usage-override"
        assert path.suffix != usage_pause.SIGNAL_SUFFIX

    def test_active_until_the_end_time_only(self, tmp_path: Path) -> None:
        usage_pause.write_usage_override(tmp_path, _SESSION, until=_NOW + 100, now=_NOW)
        assert usage_pause.usage_override_active(tmp_path, _SESSION, now=_NOW + 99) is True
        assert usage_pause.usage_override_active(tmp_path, _SESSION, now=_NOW + 101) is False

    def test_no_marker_is_not_an_override(self, tmp_path: Path) -> None:
        assert usage_pause.usage_override_active(tmp_path, _SESSION, now=_NOW) is False

    def test_another_session_is_not_covered(self, tmp_path: Path) -> None:
        usage_pause.write_usage_override(tmp_path, "other", until=_NOW + 100, now=_NOW)
        assert usage_pause.usage_override_active(tmp_path, _SESSION, now=_NOW) is False

    def test_the_end_time_is_capped_like_a_pause(self, tmp_path: Path) -> None:
        far = _NOW + 10 * 365 * 86400
        until = usage_pause.write_usage_override(tmp_path, _SESSION, until=far, now=_NOW)
        assert until == _NOW + usage_pause.MAX_PAUSE_SPAN_SECONDS
        assert usage_pause.usage_override_active(tmp_path, _SESSION, now=far) is False

    def test_an_end_time_not_after_now_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            usage_pause.write_usage_override(tmp_path, _SESSION, until=_NOW, now=_NOW)

    def test_an_unreadable_marker_fails_toward_not_pausing(self, tmp_path: Path) -> None:
        usage_pause.write_usage_override(tmp_path, _SESSION, until=_NOW + 100, now=_NOW)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "read_text", _raise_permission_error)
            assert usage_pause.usage_override_active(tmp_path, _SESSION, now=_NOW) is True

    def test_a_malformed_marker_is_ignored(self, tmp_path: Path) -> None:
        path = usage_pause.override_path(tmp_path, _SESSION)
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        assert usage_pause.usage_override_active(tmp_path, _SESSION, now=_NOW) is False


def _raise_permission_error(*_args: Any, **_kwargs: Any) -> str:
    raise PermissionError("denied")
