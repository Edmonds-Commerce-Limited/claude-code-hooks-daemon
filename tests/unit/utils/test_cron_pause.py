"""Tests for the session-scoped cron pause (ledger 00422 N4, decision 2).

A session told to cancel a DECLARED cron had no legal move: obeying failed
``cron_stop_enforcer``, and satisfying the enforcer disobeyed the instruction.
The only knob, ``persistent_crons``, is committed config that stops the job for
every session on every branch.

The pause gives "cancelled for now" a spelling. It is a marker, not config: it
belongs to ONE session, names a reason, and expires within 24 hours on its own,
through the same validity rule as the "blocked only on human input" marker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.cron_pause import (
    CRON_PAUSES_FILENAME,
    PAUSE_TTL_SECONDS,
    CronPause,
    live_pauses,
    read_pauses,
    record_pause,
    remove_pause,
    render_paused_note,
)

_SESSION = "pause-session-1"
_OTHER_SESSION = "pause-session-2"
_NOW = 1_000_000.0
_DAY_SECONDS = 24 * 60 * 60


def _path(tmp_path: Path) -> Path:
    return tmp_path / CRON_PAUSES_FILENAME


def _pause(
    job_id: str = "issue-sdlc", *, session_id: str = _SESSION, at: float = _NOW
) -> CronPause:
    return CronPause(job_id=job_id, session_id=session_id, reason="owner said stop", recorded_at=at)


class TestTheExpiryIsWithinADay:
    def test_the_ttl_is_at_most_twenty_four_hours(self) -> None:
        assert 0 < PAUSE_TTL_SECONDS <= _DAY_SECONDS

    def test_expires_at_is_recorded_at_plus_the_ttl(self) -> None:
        assert _pause().expires_at == _NOW + PAUSE_TTL_SECONDS


class TestRecordAndRead:
    def test_a_recorded_pause_reads_back(self, tmp_path: Path) -> None:
        record_pause(_path(tmp_path), _pause(), now=_NOW)

        assert read_pauses(_path(tmp_path)) == [_pause()]

    def test_the_file_is_owner_only(self, tmp_path: Path) -> None:
        record_pause(_path(tmp_path), _pause(), now=_NOW)

        assert _path(tmp_path).stat().st_mode & 0o777 == 0o600

    def test_re_pausing_the_same_job_replaces_rather_than_duplicates(self, tmp_path: Path) -> None:
        record_pause(_path(tmp_path), _pause(), now=_NOW)
        later = CronPause(
            job_id="issue-sdlc", session_id=_SESSION, reason="still stopped", recorded_at=_NOW + 60
        )

        record_pause(_path(tmp_path), later, now=_NOW + 60)

        assert read_pauses(_path(tmp_path)) == [later]

    def test_another_sessions_pause_is_kept_alongside(self, tmp_path: Path) -> None:
        record_pause(_path(tmp_path), _pause(), now=_NOW)
        other = _pause(session_id=_OTHER_SESSION)

        record_pause(_path(tmp_path), other, now=_NOW)

        assert set(read_pauses(_path(tmp_path))) == {_pause(), other}

    def test_expired_entries_are_pruned_on_write(self, tmp_path: Path) -> None:
        record_pause(_path(tmp_path), _pause("old-job"), now=_NOW)
        much_later = _NOW + PAUSE_TTL_SECONDS + 1

        record_pause(_path(tmp_path), _pause(at=much_later), now=much_later)

        assert [p.job_id for p in read_pauses(_path(tmp_path))] == ["issue-sdlc"]

    def test_a_write_to_an_unwritable_location_raises(self, tmp_path: Path) -> None:
        """The CLI must be able to say the pause was NOT recorded."""
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")

        with pytest.raises(OSError):
            record_pause(blocker / CRON_PAUSES_FILENAME, _pause(), now=_NOW)


class TestReadingFailsOpen:
    """A pause is a positive assertion. Anything unreadable means NO pause,
    so the enforcer keeps enforcing -- never the other way round."""

    def test_missing_file_is_no_pauses(self, tmp_path: Path) -> None:
        assert read_pauses(_path(tmp_path)) == []

    def test_corrupt_file_is_no_pauses(self, tmp_path: Path) -> None:
        _path(tmp_path).write_text("{not json", encoding="utf-8")

        assert read_pauses(_path(tmp_path)) == []

    def test_malformed_entries_are_skipped_not_fatal(self, tmp_path: Path) -> None:
        good = {
            "job_id": "issue-sdlc",
            "session_id": _SESSION,
            "reason": "r",
            "recorded_at": _NOW,
        }
        bad = [{"job_id": 3}, "string", {"job_id": "x", "session_id": _SESSION}]
        _path(tmp_path).write_text(json.dumps({"pauses": [*bad, good]}), encoding="utf-8")

        assert [p.job_id for p in read_pauses(_path(tmp_path))] == ["issue-sdlc"]

    def test_a_boolean_timestamp_is_rejected(self, tmp_path: Path) -> None:
        entry = {"job_id": "j", "session_id": _SESSION, "reason": "r", "recorded_at": True}
        _path(tmp_path).write_text(json.dumps({"pauses": [entry]}), encoding="utf-8")

        assert read_pauses(_path(tmp_path)) == []


class TestLivePauses:
    def test_a_fresh_pause_for_this_session_is_live(self) -> None:
        assert live_pauses([_pause()], session_id=_SESSION, now=_NOW + 1) == {
            "issue-sdlc": _pause()
        }

    def test_another_sessions_pause_is_not_live_here(self) -> None:
        assert live_pauses([_pause()], session_id=_OTHER_SESSION, now=_NOW + 1) == {}

    def test_an_expired_pause_is_not_live(self) -> None:
        assert live_pauses([_pause()], session_id=_SESSION, now=_NOW + PAUSE_TTL_SECONDS + 1) == {}

    def test_a_pause_at_exactly_the_ttl_is_still_live(self) -> None:
        assert live_pauses([_pause()], session_id=_SESSION, now=_NOW + PAUSE_TTL_SECONDS) != {}

    def test_a_future_dated_pause_is_not_live(self) -> None:
        """Clock skew or corruption: never read as a pause."""
        assert live_pauses([_pause(at=_NOW + 100)], session_id=_SESSION, now=_NOW) == {}

    def test_an_empty_session_id_matches_nothing(self) -> None:
        assert live_pauses([_pause(session_id="")], session_id="", now=_NOW) == {}


class TestRemove:
    def test_resume_removes_this_sessions_pause(self, tmp_path: Path) -> None:
        record_pause(_path(tmp_path), _pause(), now=_NOW)

        removed = remove_pause(_path(tmp_path), job_id="issue-sdlc", session_id=_SESSION, now=_NOW)

        assert removed == _pause()
        assert read_pauses(_path(tmp_path)) == []

    def test_resume_leaves_other_sessions_alone(self, tmp_path: Path) -> None:
        other = _pause(session_id=_OTHER_SESSION)
        record_pause(_path(tmp_path), _pause(), now=_NOW)
        record_pause(_path(tmp_path), other, now=_NOW)

        remove_pause(_path(tmp_path), job_id="issue-sdlc", session_id=_SESSION, now=_NOW)

        assert read_pauses(_path(tmp_path)) == [other]

    def test_resuming_a_job_that_is_not_paused_returns_none(self, tmp_path: Path) -> None:
        assert (
            remove_pause(_path(tmp_path), job_id="issue-sdlc", session_id=_SESSION, now=_NOW)
            is None
        )

    def test_an_expired_pause_is_not_reported_as_removed(self, tmp_path: Path) -> None:
        record_pause(_path(tmp_path), _pause(), now=_NOW)
        much_later = _NOW + PAUSE_TTL_SECONDS + 1

        removed = remove_pause(
            _path(tmp_path), job_id="issue-sdlc", session_id=_SESSION, now=much_later
        )

        assert removed is None


class TestTheNoteIsNeverSilent:
    def test_it_names_the_job_the_reason_and_the_expiry(self) -> None:
        note = render_paused_note([_pause()], now=_NOW)

        assert "issue-sdlc" in note
        assert "owner said stop" in note
        assert "expires" in note
        assert "UTC" in note

    def test_it_names_the_resume_command_and_the_permanent_switch(self) -> None:
        note = render_paused_note([_pause()], now=_NOW)

        assert "cron-resume issue-sdlc" in note
        assert "persistent_crons" in note
