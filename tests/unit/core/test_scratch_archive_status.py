"""``scratch-sweep status``: the live archives and their effective expiry (Plan 00627 Task 3.10).

Read-only: reading the status never creates the store, takes no lock, and
computes expiry with the expiry module's own rule (keeps applied).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.scratch_archive import (
    INDEX_NAME,
    ArchiveEvent,
    ArchiveRecord,
    ArchiveStore,
    ExpiredEvent,
    KeepEvent,
    StoreAbsent,
    new_archive_id,
)
from claude_code_hooks_daemon.core.scratch_archive_status import (
    ArchiveStatus,
    read_status,
    render_status,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
PACKED = "2026-11-20T00:00:00+00:00"
RETENTION = {"DISPOSABLE": 12.0, "UNCERTAIN": 168.0}


def _record(
    archive_id: str,
    *,
    path: str = "untracked/scratch/e",
    verdict: str = "DISPOSABLE",
    expires_at: str | None = "2026-11-20T06:00:00+00:00",
    sha: str = "a" * 64,
) -> ArchiveRecord:
    return ArchiveRecord(
        archive_id=archive_id,
        original_path=path,
        checkout="main",
        verdict=verdict,
        proof_ids=("P1",),
        packed_at=PACKED,
        expires_at=expires_at,
        counts={"file": 1},
        archive_size=10,
        sha256=sha,
        skipped=(),
        restore_command=f"hooks-daemon scratch-sweep restore {archive_id}",
    )


def _store_path(tmp_path: Path) -> Path:
    return tmp_path / "scratch-archive"


def _seed(tmp_path: Path, *records: ArchiveRecord, events: tuple[ArchiveEvent, ...] = ()) -> Path:
    path = _store_path(tmp_path)
    with ArchiveStore.open(path) as store, store.lock():
        for record in records:
            store.append(record)
        for event in events:
            store.append_event(event)
    return path


def _by_id(rows: tuple[ArchiveStatus, ...]) -> dict[str, ArchiveStatus]:
    return {row.archive_id: row for row in rows}


class TestReadOnly:
    def test_a_missing_store_is_not_created(self, tmp_path: Path) -> None:
        path = _store_path(tmp_path)
        with pytest.raises(StoreAbsent):
            read_status(path, RETENTION)
        assert not path.exists()

    def test_open_without_create_refuses_an_absent_store(self, tmp_path: Path) -> None:
        path = _store_path(tmp_path)
        with pytest.raises(StoreAbsent):
            ArchiveStore.open(path, create=False)
        assert not path.exists()

    def test_reading_takes_no_lock_and_changes_nothing(self, tmp_path: Path) -> None:
        archive_id = new_archive_id()
        path = _seed(tmp_path, _record(archive_id))
        before = sorted((p.name, p.stat().st_mtime_ns) for p in path.iterdir())
        with ArchiveStore.open(path) as holder, holder.lock():
            status = read_status(path, RETENTION)
        assert [row.archive_id for row in status.archives] == [archive_id]
        assert sorted((p.name, p.stat().st_mtime_ns) for p in path.iterdir()) == before


class TestRows:
    def test_expiry_is_the_latest_of_expires_at_and_retention(self, tmp_path: Path) -> None:
        archive_id = new_archive_id()
        path = _seed(tmp_path, _record(archive_id, verdict="UNCERTAIN"))
        (row,) = read_status(path, RETENTION).archives
        assert row.expires == datetime(2026, 11, 20, tzinfo=UTC) + timedelta(hours=168)
        assert row.verdict == "UNCERTAIN"
        assert row.original_paths == ("untracked/scratch/e",)
        assert row.note == ""

    def test_a_keep_extends_the_effective_expiry(self, tmp_path: Path) -> None:
        archive_id = new_archive_id()
        until = NOW + timedelta(hours=100)
        keep_event = KeepEvent(
            archive_id=archive_id,
            original_path="untracked/scratch/e",
            reason="still reading",
            kept_at=NOW.isoformat(),
            until=until.isoformat(),
        )
        path = _seed(tmp_path, _record(archive_id), events=(keep_event,))
        (row,) = read_status(path, RETENTION).archives
        assert row.expires == until
        assert row.keeps == 1

    def test_an_expired_archive_is_not_listed(self, tmp_path: Path) -> None:
        gone, live = new_archive_id(), new_archive_id()
        path = _seed(
            tmp_path,
            _record(gone),
            _record(live),
            events=(ExpiredEvent(archive_id=gone, at=NOW.isoformat()),),
        )
        assert list(_by_id(read_status(path, RETENTION).archives)) == [live]

    def test_a_batch_is_one_row_with_every_path(self, tmp_path: Path) -> None:
        archive_id = new_archive_id()
        path = _seed(tmp_path, _record(archive_id, path="a"), _record(archive_id, path="b"))
        (row,) = read_status(path, RETENTION).archives
        assert row.original_paths == ("a", "b")

    def test_a_null_expiry_is_held_with_its_reason(self, tmp_path: Path) -> None:
        archive_id = new_archive_id()
        path = _seed(tmp_path, _record(archive_id, expires_at=None))
        (row,) = read_status(path, RETENTION).archives
        assert row.expires is None
        assert "never expires" in row.note

    def test_disagreeing_records_are_listed_as_incomplete(self, tmp_path: Path) -> None:
        archive_id = new_archive_id()
        path = _seed(
            tmp_path,
            _record(archive_id, path="a"),
            _record(archive_id, path="b", sha="b" * 64),
        )
        (row,) = read_status(path, RETENTION).archives
        assert row.expires is None
        assert "disagree" in row.note

    def test_a_torn_index_is_reported(self, tmp_path: Path) -> None:
        archive_id = new_archive_id()
        path = _seed(tmp_path, _record(archive_id))
        fd = os.open(path / INDEX_NAME, os.O_WRONLY | os.O_APPEND)
        os.write(fd, b'{"archive_id": "x')
        os.close(fd)
        status = read_status(path, RETENTION)
        assert status.torn
        (row,) = status.archives
        assert row.archive_id == archive_id


class TestRender:
    def test_the_table_names_id_path_verdict_and_expiry(self, tmp_path: Path) -> None:
        archive_id = new_archive_id()
        path = _seed(tmp_path, _record(archive_id))
        lines = render_status(read_status(path, RETENTION), now=NOW)
        text = "\n".join(lines)
        assert archive_id in text
        assert "untracked/scratch/e" in text
        assert "DISPOSABLE" in text
        assert "2026-11-20T12:00:00+00:00" in text
        assert "due" in text

    def test_an_empty_store_says_so(self, tmp_path: Path) -> None:
        path = _seed(tmp_path)
        assert render_status(read_status(path, RETENTION), now=NOW) == [
            "scratch-sweep status: no live archives"
        ]
