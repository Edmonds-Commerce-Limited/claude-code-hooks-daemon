"""The scratch archive store (Plan 00627 Task 3.1, DESIGN.md section 5.1).

The store is one flat directory, mode 0700, holding archive files, one
``index.jsonl`` and one lock file. It is opened through a descriptor and
refused, never repaired, when it is a link, foreign-owned or the wrong mode.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.scratch_archive import (
    INDEX_NAME,
    ArchiveRecord,
    ArchiveStore,
    StoreBusy,
    StoreRefused,
    new_archive_id,
)


def _record(archive_id: str, *, sha: str = "0" * 64) -> ArchiveRecord:
    return ArchiveRecord(
        archive_id=archive_id,
        original_path="untracked/scratch/e1",
        checkout="/project",
        verdict="DISPOSABLE",
        proof_ids=("P1",),
        packed_at="2026-11-20T00:00:00Z",
        expires_at="2026-11-20T12:00:00Z",
        counts={"file": 2, "dir": 1},
        archive_size=10240,
        sha256=sha,
        skipped=(),
        restore_command=f"hooks-daemon scratch-restore {archive_id}",
    )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "untracked" / "scratch-archive"


class TestOpen:
    def test_creates_store_mode_0700(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        old = os.umask(0o077)
        try:
            with ArchiveStore.open(store_path):
                pass
        finally:
            os.umask(old)
        assert stat.S_IMODE(store_path.lstat().st_mode) == 0o700

    def test_creates_store_0700_under_a_permissive_umask(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        old = os.umask(0)
        try:
            with ArchiveStore.open(store_path):
                pass
        finally:
            os.umask(old)
        assert stat.S_IMODE(store_path.lstat().st_mode) == 0o700

    def test_refuses_wrong_mode_without_repairing(self, store_path: Path) -> None:
        store_path.mkdir(parents=True, mode=0o700)
        store_path.chmod(0o755)
        with pytest.raises(StoreRefused, match="mode"):
            ArchiveStore.open(store_path)
        assert stat.S_IMODE(store_path.lstat().st_mode) == 0o755

    def test_refuses_a_symlinked_store(self, tmp_path: Path, store_path: Path) -> None:
        real = tmp_path / "elsewhere"
        real.mkdir(mode=0o700)
        store_path.parent.mkdir()
        store_path.symlink_to(real)
        with pytest.raises(StoreRefused):
            ArchiveStore.open(store_path)

    def test_refuses_a_store_that_is_a_file(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        store_path.write_text("x")
        with pytest.raises(StoreRefused):
            ArchiveStore.open(store_path)

    def test_refuses_a_missing_parent(self, store_path: Path) -> None:
        with pytest.raises(StoreRefused):
            ArchiveStore.open(store_path)

    def test_refuses_a_symlinked_index(self, tmp_path: Path, store_path: Path) -> None:
        store_path.mkdir(parents=True, mode=0o700)
        target = tmp_path / "victim"
        target.write_text("keep\n")
        (store_path / INDEX_NAME).symlink_to(target)
        with ArchiveStore.open(store_path) as store:
            with store.lock(), pytest.raises(StoreRefused):
                store.append(_record(new_archive_id()))
        assert target.read_text() == "keep\n"


class TestLock:
    def test_second_lock_is_busy(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        with ArchiveStore.open(store_path) as one, ArchiveStore.open(store_path) as two:
            with one.lock():
                with pytest.raises(StoreBusy):
                    with two.lock():
                        pass
            with two.lock():
                pass

    def test_append_outside_the_lock_is_refused(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        with ArchiveStore.open(store_path) as store:
            with pytest.raises(StoreRefused, match="lock"):
                store.append(_record(new_archive_id()))


class TestIndex:
    def test_round_trip(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        ids = [new_archive_id() for _ in range(3)]
        with ArchiveStore.open(store_path) as store, store.lock():
            for archive_id in ids:
                store.append(_record(archive_id))
            index = store.read_index()
        assert [r.archive_id for r in index.records] == ids
        assert index.torn_tail is False
        assert index.records[0] == _record(ids[0])
        mode = stat.S_IMODE((store_path / INDEX_NAME).lstat().st_mode)
        assert mode == 0o600

    def test_torn_tail_is_reported_and_dropped_before_the_next_append(
        self, store_path: Path
    ) -> None:
        store_path.parent.mkdir()
        first, second = new_archive_id(), new_archive_id()
        with ArchiveStore.open(store_path) as store, store.lock():
            store.append(_record(first))
        with (store_path / INDEX_NAME).open("a") as handle:
            handle.write('{"archive_id": "torn')
        with ArchiveStore.open(store_path) as store, store.lock():
            index = store.read_index()
            assert index.torn_tail is True
            assert [r.archive_id for r in index.records] == [first]
            store.append(_record(second))
            index = store.read_index()
        assert index.torn_tail is False
        assert [r.archive_id for r in index.records] == [first, second]

    def test_interior_malformed_line_refuses(self, store_path: Path) -> None:
        store_path.mkdir(parents=True, mode=0o700)
        good = json.dumps(_record(new_archive_id()).to_json())
        (store_path / INDEX_NAME).write_text(f"garbage\n{good}\n")
        with ArchiveStore.open(store_path) as store, store.lock():
            with pytest.raises(StoreRefused, match="line 1"):
                store.read_index()

    def test_record_with_a_path_shaped_id_is_refused(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        with ArchiveStore.open(store_path) as store, store.lock():
            with pytest.raises(ValueError):
                store.append(_record("../escape"))

    def test_missing_index_reads_empty(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        with ArchiveStore.open(store_path) as store, store.lock():
            index = store.read_index()
        assert index.records == ()
        assert index.torn_tail is False


class TestArchiveFiles:
    def test_create_archive_is_exclusive_and_0600(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        archive_id = new_archive_id()
        with ArchiveStore.open(store_path) as store, store.lock():
            fd = store.create_archive(archive_id)
            os.close(fd)
            with pytest.raises(StoreRefused):
                store.create_archive(archive_id)
        path = store_path / f"{archive_id}.tar"
        assert stat.S_IMODE(path.lstat().st_mode) == 0o600

    def test_store_stays_flat(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        with ArchiveStore.open(store_path) as store, store.lock():
            for _ in range(3):
                archive_id = new_archive_id()
                os.close(store.create_archive(archive_id))
                store.append(_record(archive_id))
        assert all(not p.is_dir() for p in store_path.iterdir())

    def test_orphans_and_missing_archives(self, store_path: Path) -> None:
        store_path.parent.mkdir()
        recorded, orphan, missing = new_archive_id(), new_archive_id(), new_archive_id()
        with ArchiveStore.open(store_path) as store, store.lock():
            os.close(store.create_archive(recorded))
            os.close(store.create_archive(orphan))
            store.append(_record(recorded))
            store.append(_record(missing))
            audit = store.audit()
        assert audit.unrecorded_archives == (f"{orphan}.tar",)
        assert audit.records_without_archive == (missing,)

    def test_new_ids_are_unique_and_name_safe(self) -> None:
        ids = {new_archive_id() for _ in range(200)}
        assert len(ids) == 200
        assert all("/" not in i and not i.startswith(".") for i in ids)
