"""Completeness, keep and expiry of archives in the store (Plan 00627 Task 3.6).

DESIGN.md section 5.2 step 7: a later sweep removes an archive whose retention
has passed, after re-checking that no keep record or new reference covers it.
Expiry writes its ``expired`` event BEFORE the unlink, so a crash between the
two leaves an event a rerun finishes, never an unrecorded deletion.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import scratch_archive_expire as expire_mod
from claude_code_hooks_daemon.core.scratch_archive import (
    EVENTS_NAME,
    INDEX_NAME,
    ArchiveRecord,
    ArchiveStore,
    ExpiredEvent,
    KeepEvent,
    StoreRefused,
    archive_file_name,
    new_archive_id,
)
from claude_code_hooks_daemon.core.scratch_archive_expire import (
    ExpiryRefused,
    Incomplete,
    KeepRefused,
    complete_records,
    expire_due,
    keep,
    records_of,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
PACKED = "2026-11-20T00:00:00+00:00"
RETENTION = {"DISPOSABLE": 12.0, "UNCERTAIN": 168.0}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ArchiveStore]:
    with ArchiveStore.open(tmp_path / "scratch-archive") as opened:
        with opened.lock():
            yield opened


def _record(
    archive_id: str,
    *,
    path: str = "untracked/scratch/e",
    verdict: str = "DISPOSABLE",
    expires_at: str | None = "2026-11-20T12:00:00+00:00",
    packed_at: str = PACKED,
    sha: str = "a" * 64,
    size: int = 10,
) -> ArchiveRecord:
    return ArchiveRecord(
        archive_id=archive_id,
        original_path=path,
        checkout="main",
        verdict=verdict,
        proof_ids=("P1",),
        packed_at=packed_at,
        expires_at=expires_at,
        counts={"file": 1},
        archive_size=size,
        sha256=sha,
        skipped=(),
        restore_command="x",
    )


def _archive(store: ArchiveStore, archive_id: str, data: bytes = b"0123456789") -> None:
    fd = store.create_archive(archive_id)
    os.write(fd, data)
    os.close(fd)


def _present(store: ArchiveStore, archive_id: str) -> bool:
    return (store.path / archive_file_name(archive_id)).exists()


def _write_raw(store: ArchiveStore, name: str, data: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600, dir_fd=store.dir_fd)
    os.write(fd, data)
    os.close(fd)


def _never(_records: tuple[ArchiveRecord, ...]) -> bool:
    return False


def _clock(at: datetime = NOW + timedelta(hours=1)) -> Callable[[], datetime]:
    return lambda: at


# --- completeness -------------------------------------------------------------


class TestComplete:
    def test_a_recorded_id_is_complete(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        records = complete_records(store.read_index(), store.read_events(), archive_id)
        assert [r.archive_id for r in records] == [archive_id]

    def test_every_record_of_a_batch_is_returned(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id, path="d/a"))
        store.append(_record(archive_id, path="d/b"))
        index = store.read_index()
        assert index.by_id(archive_id) is not None
        assert [r.original_path for r in records_of(index, archive_id)] == ["d/a", "d/b"]
        records = complete_records(index, store.read_events(), archive_id)
        assert len(records) == 2

    def test_an_unknown_id_is_incomplete(self, store: ArchiveStore) -> None:
        with pytest.raises(Incomplete, match="no record"):
            complete_records(store.read_index(), store.read_events(), new_archive_id())

    def test_a_torn_index_is_incomplete(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        _write_raw(store, INDEX_NAME, b'{"archive_id": "x')
        with pytest.raises(Incomplete, match="torn"):
            complete_records(store.read_index(), store.read_events(), archive_id)

    @pytest.mark.parametrize("field", ["sha", "size"])
    def test_records_that_disagree_are_incomplete(self, store: ArchiveStore, field: str) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id, path="d/a"))
        if field == "sha":
            store.append(_record(archive_id, path="d/b", sha="b" * 64))
        else:
            store.append(_record(archive_id, path="d/b", size=11))
        with pytest.raises(Incomplete, match="disagree"):
            complete_records(store.read_index(), store.read_events(), archive_id)

    def test_an_expired_id_is_incomplete(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        store.append_event(ExpiredEvent(archive_id=archive_id, at=NOW.isoformat()))
        with pytest.raises(Incomplete, match="expired"):
            complete_records(store.read_index(), store.read_events(), archive_id)


# --- keep -------------------------------------------------------------------------


def _keep(
    store: ArchiveStore,
    archive_id: str,
    *,
    reason: str = "still reading the notes",
    until: datetime = NOW + timedelta(hours=48),
    now: datetime = NOW,
    max_hours: float = 168.0,
    max_keeps: int = 3,
    entry: str | None = None,
) -> KeepEvent:
    return keep(
        store,
        archive_id,
        reason=reason,
        until=until,
        now=now,
        max_hours=max_hours,
        max_keeps=max_keeps,
        retention_hours=RETENTION,
        entry=entry,
    )


class TestKeep:
    def test_a_keep_is_recorded_with_its_normalised_reason(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        event = _keep(store, archive_id, reason="  still   reading\tthe notes ")
        assert event.reason == "still reading the notes"
        assert event.original_path == "untracked/scratch/e"
        assert store.read_events().events == (event,)

    def test_a_keep_needs_the_lock(self, tmp_path: Path) -> None:
        with ArchiveStore.open(tmp_path / "scratch-archive") as unlocked:
            with pytest.raises(StoreRefused, match="lock"):
                _keep(unlocked, new_archive_id())

    @pytest.mark.parametrize("reason", ["", "   ", "\n\t", "x" * 501])
    def test_an_empty_or_huge_reason_is_refused(self, store: ArchiveStore, reason: str) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        with pytest.raises(KeepRefused, match="reason"):
            _keep(store, archive_id, reason=reason)
        assert store.read_events().events == ()

    def test_a_repeated_reason_is_refused_whatever_its_spacing_or_case(
        self, store: ArchiveStore
    ) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        _keep(store, archive_id, reason="Still reading")
        with pytest.raises(KeepRefused, match="repeat"):
            _keep(store, archive_id, reason="  still   READING ", until=NOW + timedelta(hours=96))

    def test_keeps_are_capped(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        for n in range(3):
            _keep(store, archive_id, reason=f"reason {n}", until=NOW + timedelta(hours=20 + n))
        with pytest.raises(KeepRefused, match="cap"):
            _keep(store, archive_id, reason="reason 4", until=NOW + timedelta(hours=40))

    def test_until_is_bounded(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        with pytest.raises(KeepRefused, match="bound"):
            _keep(store, archive_id, until=NOW + timedelta(hours=169))
        with pytest.raises(KeepRefused, match="future"):
            _keep(store, archive_id, until=NOW)

    def test_a_keep_that_does_not_extend_the_expiry_is_refused(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        _keep(store, archive_id, reason="first", until=NOW + timedelta(hours=48))
        with pytest.raises(KeepRefused, match="extend"):
            _keep(store, archive_id, reason="second", until=NOW + timedelta(hours=24))

    def test_retention_counts_toward_the_expiry_a_keep_must_pass(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id, verdict="UNCERTAIN"))
        # packed_at + 168h is later than until, so the keep would extend nothing.
        with pytest.raises(KeepRefused, match="extend"):
            _keep(store, archive_id, until=NOW + timedelta(hours=24))

    def test_a_null_expiry_cannot_be_kept(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id, verdict="REFERENCED", expires_at=None))
        with pytest.raises(KeepRefused, match="never expires"):
            _keep(store, archive_id)

    def test_naive_instants_are_refused(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        with pytest.raises(KeepRefused, match="zone"):
            _keep(store, archive_id, until=datetime(2026, 11, 22, 0, 0))
        with pytest.raises(KeepRefused, match="zone"):
            _keep(store, archive_id, now=datetime(2026, 11, 20, 0, 0))

    def test_an_expired_or_unknown_id_is_refused(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        store.append_event(ExpiredEvent(archive_id=archive_id, at=NOW.isoformat()))
        with pytest.raises(KeepRefused, match="expired"):
            _keep(store, archive_id)
        with pytest.raises(KeepRefused, match="no record"):
            _keep(store, new_archive_id())

    def test_a_batch_keep_names_its_entry(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id, path="d/a"))
        store.append(_record(archive_id, path="d/b"))
        with pytest.raises(KeepRefused, match="entry"):
            _keep(store, archive_id)
        with pytest.raises(KeepRefused, match="entry"):
            _keep(store, archive_id, entry="d/c")
        assert _keep(store, archive_id, entry="d/b").original_path == "d/b"

    def test_a_torn_events_tail_is_cut_by_the_keep(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        _write_raw(store, EVENTS_NAME, b'{"kind": "ke')
        event = _keep(store, archive_id)
        read = store.read_events()
        assert read.events == (event,)
        assert not read.torn_tail


# --- expiry -------------------------------------------------------------------------


def _expire(
    store: ArchiveStore,
    *,
    clock: Callable[[], datetime] | None = None,
    referenced: Callable[[tuple[ArchiveRecord, ...]], bool] = _never,
) -> dict[str, tuple[str, str]]:
    outcomes = expire_due(
        store,
        clock=clock or _clock(),
        retention_hours=RETENTION,
        still_referenced=referenced,
    )
    return {o.archive_id: (o.outcome, o.reason) for o in outcomes}


class TestExpire:
    def test_a_due_archive_is_deleted_after_its_event(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))
        assert _expire(store)[archive_id][0] == "expired"
        assert not _present(store, archive_id)
        events = store.read_events().events
        assert len(events) == 1
        assert isinstance(events[0], ExpiredEvent)
        assert store.audit().records_without_archive == ()

    def test_an_archive_not_yet_due_is_held(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))
        outcome = _expire(store, clock=_clock(NOW - timedelta(minutes=1)))
        assert outcome[archive_id][0] == "held"
        assert _present(store, archive_id)
        assert store.read_events().events == ()

    def test_retention_by_verdict_outlasts_a_short_expires_at(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id, verdict="UNCERTAIN"))
        assert _expire(store, clock=_clock(NOW + timedelta(hours=100)))[archive_id][0] == "held"
        assert _present(store, archive_id)
        assert _expire(store, clock=_clock(NOW + timedelta(hours=200)))[archive_id][0] == (
            "expired"
        )

    @pytest.mark.parametrize("verdict", ["REFERENCED", "SOMETHING_NEW"])
    def test_an_unknown_verdict_or_null_expiry_is_held(
        self, store: ArchiveStore, verdict: str
    ) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        expires = None if verdict == "REFERENCED" else "2026-11-20T12:00:00+00:00"
        store.append(_record(archive_id, verdict=verdict, expires_at=expires))
        far = _clock(NOW + timedelta(days=3650))
        assert _expire(store, clock=far)[archive_id][0] == "held"
        assert _present(store, archive_id)

    def test_a_keep_holds_the_archive_until_it_passes(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))
        _keep(store, archive_id, until=NOW + timedelta(hours=48))
        assert _expire(store, clock=_clock(NOW + timedelta(hours=47)))[archive_id][0] == "held"
        assert _expire(store, clock=_clock(NOW + timedelta(hours=49)))[archive_id][0] == "expired"

    def test_one_keep_on_a_batch_entry_holds_the_whole_archive(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id, path="d/a"))
        store.append(_record(archive_id, path="d/b"))
        _keep(store, archive_id, entry="d/b", until=NOW + timedelta(hours=48))
        assert _expire(store)[archive_id][0] == "held"
        assert _present(store, archive_id)

    def test_one_null_expiry_in_a_batch_holds_the_whole_archive(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id, path="d/a"))
        store.append(_record(archive_id, path="d/b", expires_at=None))
        assert _expire(store, clock=_clock(NOW + timedelta(days=30)))[archive_id][0] == "held"

    @pytest.mark.parametrize("bad", ["2026-11-20T12:00:00", "soon", ""])
    def test_an_unparseable_instant_holds(self, store: ArchiveStore, bad: str) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id, expires_at=bad))
        other = new_archive_id()
        _archive(store, other)
        store.append(_record(other, packed_at=bad))
        outcomes = _expire(store, clock=_clock(NOW + timedelta(days=30)))
        assert outcomes[archive_id][0] == "held"
        assert outcomes[other][0] == "held"
        assert _present(store, archive_id)
        assert _present(store, other)

    def test_a_reference_holds_and_its_failure_holds(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))
        assert _expire(store, referenced=lambda _r: True)[archive_id] == ("held", "referenced")

        def broken(_records: tuple[ArchiveRecord, ...]) -> bool:
            raise RuntimeError("git is gone")

        assert _expire(store, referenced=broken)[archive_id][0] == "held"
        assert _present(store, archive_id)

    def test_a_broken_or_naive_clock_holds(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))

        def broken() -> datetime:
            raise OSError("no clock")

        assert _expire(store, clock=broken)[archive_id][0] == "held"
        naive = _clock(datetime(2030, 1, 1))
        assert _expire(store, clock=naive)[archive_id][0] == "held"
        assert _present(store, archive_id)

    def test_a_torn_index_or_events_tail_refuses_the_run(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))
        _write_raw(store, EVENTS_NAME, b'{"kind": "keep"')
        with pytest.raises(ExpiryRefused, match="torn"):
            _expire(store)
        assert _present(store, archive_id)

    def test_a_torn_index_refuses_the_run(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))
        _write_raw(store, INDEX_NAME, b'{"archive_')
        with pytest.raises(ExpiryRefused, match="torn"):
            _expire(store)
        assert _present(store, archive_id)

    def test_expiry_needs_the_lock(self, tmp_path: Path) -> None:
        with ArchiveStore.open(tmp_path / "scratch-archive") as unlocked:
            with pytest.raises(StoreRefused, match="lock"):
                _expire(unlocked)

    def test_a_link_or_directory_in_the_archive_name_is_held(self, store: ArchiveStore) -> None:
        linked = new_archive_id()
        os.symlink("/etc/passwd", archive_file_name(linked), dir_fd=store.dir_fd)
        store.append(_record(linked))
        dirred = new_archive_id()
        os.mkdir(archive_file_name(dirred), dir_fd=store.dir_fd)
        store.append(_record(dirred))
        outcomes = _expire(store)
        assert outcomes[linked][0] == "held"
        assert outcomes[dirred][0] == "held"
        assert (store.path / archive_file_name(linked)).is_symlink()
        assert (store.path / archive_file_name(dirred)).is_dir()
        assert store.read_events().events == ()

    def test_a_missing_archive_is_reported_and_writes_nothing(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        store.append(_record(archive_id))
        assert _expire(store)[archive_id][0] == "absent"
        assert store.read_events().events == ()

    def test_a_crash_between_event_and_unlink_is_finished_by_a_rerun(
        self, store: ArchiveStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))

        class Crash(BaseException):
            pass

        def crash(_store: ArchiveStore, _archive_id: str, _expected: os.stat_result) -> bool:
            raise Crash

        monkeypatch.setattr(expire_mod, "_unlink_expired", crash)
        with pytest.raises(Crash):
            _expire(store)
        monkeypatch.undo()
        assert _present(store, archive_id)
        assert isinstance(store.read_events().events[-1], ExpiredEvent)
        # An expired id is neither restorable nor keepable...
        with pytest.raises(KeepRefused, match="expired"):
            _keep(store, archive_id)
        # ...and the rerun finishes the deletion even before the archive is due again.
        assert _expire(store, clock=_clock(NOW - timedelta(days=1)))[archive_id][0] == "finished"
        assert not _present(store, archive_id)
        assert len(store.read_events().events) == 1
        assert _expire(store)[archive_id][0] == "absent"

    def test_a_crash_before_the_event_leaves_everything(
        self, store: ArchiveStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))

        class Crash(BaseException):
            pass

        def crash(_self: ArchiveStore, _event: object) -> None:
            raise Crash

        monkeypatch.setattr(ArchiveStore, "append_event", crash)
        with pytest.raises(Crash):
            _expire(store)
        monkeypatch.undo()
        assert _present(store, archive_id)
        assert store.read_events().events == ()

    def test_an_archive_swapped_after_the_event_is_not_unlinked_this_run(
        self, store: ArchiveStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))
        real = ArchiveStore.append_event

        def swap(self: ArchiveStore, event: ExpiredEvent) -> None:
            real(self, event)
            name = archive_file_name(archive_id)
            os.unlink(name, dir_fd=self.dir_fd)
            os.symlink("/etc/passwd", name, dir_fd=self.dir_fd)

        monkeypatch.setattr(ArchiveStore, "append_event", swap)
        assert _expire(store)[archive_id][0] == "held"
        monkeypatch.undo()
        assert (store.path / archive_file_name(archive_id)).is_symlink()
        # The rerun still refuses to unlink a link under the archive's name.
        assert _expire(store)[archive_id][0] == "held"
        assert (store.path / archive_file_name(archive_id)).is_symlink()

    def test_audit_does_not_report_an_expired_archive_as_missing(self, store: ArchiveStore) -> None:
        archive_id = new_archive_id()
        _archive(store, archive_id)
        store.append(_record(archive_id))
        _expire(store)
        lost = new_archive_id()
        store.append(_record(lost))
        assert store.audit().records_without_archive == (lost,)
