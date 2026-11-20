"""The store's events file: keep and expired records beside the index (Plan 00627 Task 3.6)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.scratch_archive import (
    EVENTS_NAME,
    INDEX_NAME,
    ArchiveRecord,
    ArchiveStore,
    ClaimEvent,
    ExpiredEvent,
    KeepEvent,
    StoreRefused,
    new_archive_id,
    parse_instant,
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ArchiveStore]:
    with ArchiveStore.open(tmp_path / "scratch-archive") as opened:
        with opened.lock():
            yield opened


def _record(archive_id: str) -> ArchiveRecord:
    return ArchiveRecord(
        archive_id=archive_id,
        original_path="untracked/scratch/e",
        checkout="main",
        verdict="UNCERTAIN",
        proof_ids=(),
        packed_at="2026-11-20T00:00:00+00:00",
        expires_at="2026-11-27T00:00:00+00:00",
        counts={"dir": 1},
        archive_size=10,
        sha256="0" * 64,
        skipped=(),
        restore_command="x",
    )


def _keep(archive_id: str, reason: str = "still reading it") -> KeepEvent:
    return KeepEvent(
        archive_id=archive_id,
        original_path="untracked/scratch/e",
        reason=reason,
        kept_at="2026-11-20T00:00:00+00:00",
        until="2026-11-28T00:00:00+00:00",
    )


def test_events_round_trip_and_coexist_with_the_index(store: ArchiveStore) -> None:
    archive_id = new_archive_id()
    store.append(_record(archive_id))
    keep = _keep(archive_id)
    expired = ExpiredEvent(archive_id=archive_id, at="2026-11-29T00:00:00+00:00")
    store.append_event(keep)
    store.append_event(expired)
    store.append(_record(new_archive_id()))
    assert len(store.read_index().records) == 2
    read = store.read_events()
    assert read.events == (keep, expired)
    assert not read.torn_tail


def _claim_event(archive_id: str, root_ino: str = "42") -> ClaimEvent:
    return ClaimEvent(
        archive_id=archive_id,
        original_path="untracked/scratch/e",
        checkout="main",
        root_dev="7",
        root_ino=root_ino,
        at="2026-11-20T00:00:00+00:00",
    )


def test_a_claim_event_round_trips(store: ArchiveStore) -> None:
    claim = _claim_event(new_archive_id())
    store.append_event(claim)
    assert store.read_events().events == (claim,)


def test_a_claim_event_with_a_non_numeric_inode_refuses_the_store(store: ArchiveStore) -> None:
    store.append_event(_claim_event(new_archive_id(), root_ino="x"))
    with pytest.raises(StoreRefused):
        store.read_events()


def test_no_events_file_reads_as_no_events(store: ArchiveStore) -> None:
    read = store.read_events()
    assert read.events == ()
    assert not read.torn_tail


def test_an_event_needs_the_lock(tmp_path: Path) -> None:
    with ArchiveStore.open(tmp_path / "scratch-archive") as unlocked:
        with pytest.raises(StoreRefused, match="lock"):
            unlocked.append_event(_keep(new_archive_id()))


def test_a_torn_event_tail_is_reported_and_cut_by_the_next_append(store: ArchiveStore) -> None:
    archive_id = new_archive_id()
    store.append_event(_keep(archive_id))
    fd = os.open(EVENTS_NAME, os.O_WRONLY | os.O_APPEND, dir_fd=store.dir_fd)
    os.write(fd, b'{"kind": "keep", "arch')
    os.close(fd)
    assert store.read_events().torn_tail
    store.append_event(ExpiredEvent(archive_id=archive_id, at="2026-11-29T00:00:00+00:00"))
    read = store.read_events()
    assert not read.torn_tail
    assert len(read.events) == 2


@pytest.mark.parametrize(
    "line",
    [
        {"kind": "nope", "archive_id": "x"},
        {"kind": "expired", "archive_id": "bad", "at": "2026-11-29T00:00:00+00:00"},
        {"kind": "expired", "archive_id": "20261120T000000Z-0123456789ab", "at": "yesterday"},
        {
            "kind": "expired",
            "archive_id": "20261120T000000Z-0123456789ab",
            "at": "2026-11-29T00:00:00",
        },
        {
            "kind": "keep",
            "archive_id": "20261120T000000Z-0123456789ab",
            "original_path": "e",
            "reason": "r",
            "kept_at": "2026-11-20T00:00:00+00:00",
            "until": "soon",
        },
        {"kind": "expired", "archive_id": "20261120T000000Z-0123456789ab"},
    ],
)
def test_an_interior_bad_event_line_refuses_the_store(
    store: ArchiveStore, line: dict[str, str]
) -> None:
    fd = os.open(EVENTS_NAME, os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=store.dir_fd)
    os.write(fd, json.dumps(line).encode() + b"\n")
    os.close(fd)
    with pytest.raises(StoreRefused, match=EVENTS_NAME):
        store.read_events()


def test_an_event_line_in_the_index_still_refuses_the_index(store: ArchiveStore) -> None:
    """Why events have their own file: the index reader refuses any non-record line."""
    fd = os.open(INDEX_NAME, os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=store.dir_fd)
    os.write(fd, json.dumps({"kind": "expired"}).encode() + b"\n")
    os.close(fd)
    with pytest.raises(StoreRefused):
        store.read_index()


def test_parse_instant_needs_a_zone() -> None:
    assert parse_instant("2026-11-20T00:00:00Z") == parse_instant("2026-11-20T00:00:00+00:00")
    for bad in ("2026-11-20T00:00:00", "", "tomorrow", "2026-13-01T00:00:00Z"):
        with pytest.raises(ValueError):
            parse_instant(bad)
