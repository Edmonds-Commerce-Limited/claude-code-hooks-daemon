"""The daemon's own record of when each session cron was created (Plan 00470 Task 2.1).

`session_crons` carries no creation time, so the daemon cannot read a job's age
from the Stop payload. It records the age itself, from the `CronCreate` result.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from claude_code_hooks_daemon.utils.cron_records import (
    CRON_EXPIRY_SECONDS,
    CronRecord,
    forget_cron,
    forget_missing,
    prompt_fingerprint,
    read_records,
    record_cron,
)

_NOW = 1_000_000.0


def _record(
    cron_id: str = "c1",
    session_id: str = "s1",
    created_at: float = _NOW,
    schedule: str = "23 * * * *",
) -> CronRecord:
    return CronRecord(
        session_id=session_id,
        cron_id=cron_id,
        schedule=schedule,
        prompt_hash=prompt_fingerprint("do the thing"),
        created_at=created_at,
    )


class TestPromptFingerprint:
    def test_it_is_a_hash_not_the_prompt(self) -> None:
        assert "do the thing" not in prompt_fingerprint("do the thing")

    def test_layout_and_the_tick_sentinel_do_not_change_it(self) -> None:
        plain = prompt_fingerprint("one\ntwo")
        assert prompt_fingerprint("[tick:job:x]\n\n  one\n\ntwo  \n") == plain

    def test_different_words_differ(self) -> None:
        assert prompt_fingerprint("one") != prompt_fingerprint("two")


class TestRecording:
    def test_a_created_cron_is_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(), now=_NOW)
        assert read_records(path) == [_record()]

    def test_the_file_never_holds_the_prompt_text(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(), now=_NOW)
        assert "do the thing" not in path.read_text(encoding="utf-8")

    def test_recording_the_same_cron_again_replaces_it(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(created_at=_NOW), now=_NOW)
        record_cron(path, _record(created_at=_NOW + 5), now=_NOW + 5)
        assert [r.created_at for r in read_records(path)] == [_NOW + 5]

    def test_the_same_id_in_another_session_is_a_different_record(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(session_id="s1"), now=_NOW)
        record_cron(path, _record(session_id="s2"), now=_NOW)
        assert {r.session_id for r in read_records(path)} == {"s1", "s2"}

    def test_concurrent_recordings_all_survive(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        threads = [
            threading.Thread(
                target=record_cron, args=(path, _record(cron_id=f"c{n}")), kwargs={"now": _NOW}
            )
            for n in range(12)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(read_records(path)) == 12


class TestAnUnwritableLocationIsReportedNotRaised:
    def test_recording_into_an_unwritable_location_returns_false(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        assert record_cron(blocker / "cron-records.json", _record(), now=_NOW) is False

    def test_a_successful_recording_returns_true(self, tmp_path: Path) -> None:
        assert record_cron(tmp_path / "cron-records.json", _record(), now=_NOW) is True


class TestDeleting:
    def test_a_deleted_cron_is_forgotten(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(cron_id="c1"), now=_NOW)
        record_cron(path, _record(cron_id="c2"), now=_NOW)
        forget_cron(path, session_id="s1", cron_id="c1", now=_NOW)
        assert [r.cron_id for r in read_records(path)] == ["c2"]

    def test_deleting_an_unknown_cron_changes_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(), now=_NOW)
        forget_cron(path, session_id="s1", cron_id="nope", now=_NOW)
        assert len(read_records(path)) == 1

    def test_deleting_another_sessions_cron_changes_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(session_id="s1"), now=_NOW)
        forget_cron(path, session_id="s2", cron_id="c1", now=_NOW)
        assert len(read_records(path)) == 1

    def test_deleting_with_no_file_is_a_no_op(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        forget_cron(path, session_id="s1", cron_id="c1", now=_NOW)
        assert not path.exists()


class TestPruningRecordsOfSessionsThatAreGone:
    """No session registry exists, so liveness is read from the two signals the daemon has."""

    def test_a_record_past_the_harness_expiry_is_pruned_on_the_next_write(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(cron_id="old", session_id="gone"), now=_NOW)
        later = _NOW + CRON_EXPIRY_SECONDS
        record_cron(path, _record(cron_id="new", created_at=later), now=later)
        assert [r.cron_id for r in read_records(path)] == ["new"]

    def test_a_record_just_inside_the_expiry_is_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(cron_id="old", session_id="other"), now=_NOW)
        later = _NOW + CRON_EXPIRY_SECONDS - 1
        record_cron(path, _record(cron_id="new", created_at=later), now=later)
        assert {r.cron_id for r in read_records(path)} == {"old", "new"}

    def test_a_cron_the_session_no_longer_reports_is_forgotten(self, tmp_path: Path) -> None:
        """`session_crons` is the session's own statement of what is alive."""
        path = tmp_path / "cron-records.json"
        for cron_id in ("alive", "deleted-elsewhere"):
            record_cron(path, _record(cron_id=cron_id), now=_NOW)
        record_cron(path, _record(cron_id="x", session_id="s2"), now=_NOW)

        forget_missing(path, session_id="s1", live_ids={"alive"}, now=_NOW)

        assert {(r.session_id, r.cron_id) for r in read_records(path)} == {
            ("s1", "alive"),
            ("s2", "x"),
        }

    def test_a_future_dated_record_is_treated_as_corrupt_and_pruned(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(cron_id="skewed", created_at=_NOW + 10_000), now=_NOW + 10_000)
        record_cron(path, _record(cron_id="fresh"), now=_NOW)
        assert [r.cron_id for r in read_records(path)] == ["fresh"]


class TestReadingFailsOpen:
    def test_a_missing_file_reads_as_no_records(self, tmp_path: Path) -> None:
        assert read_records(tmp_path / "absent.json") == []

    def test_a_corrupt_file_reads_as_no_records(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        path.write_text("{not json", encoding="utf-8")
        assert read_records(path) == []

    def test_a_malformed_entry_does_not_hide_a_good_one(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        good = {
            "session_id": "s1",
            "cron_id": "c1",
            "schedule": "* * * * *",
            "prompt_hash": "h",
            "created_at": _NOW,
        }
        path.write_text(json.dumps({"records": [{"cron_id": 3}, "junk", good]}), encoding="utf-8")
        assert [r.cron_id for r in read_records(path)] == ["c1"]

    def test_a_boolean_timestamp_is_not_a_number(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        entry = {
            "session_id": "s1",
            "cron_id": "c1",
            "schedule": "* * * * *",
            "prompt_hash": "h",
            "created_at": True,
        }
        path.write_text(json.dumps({"records": [entry]}), encoding="utf-8")
        assert read_records(path) == []

    def test_the_file_is_owner_only(self, tmp_path: Path) -> None:
        path = tmp_path / "cron-records.json"
        record_cron(path, _record(), now=_NOW)
        assert path.stat().st_mode & 0o077 == 0
