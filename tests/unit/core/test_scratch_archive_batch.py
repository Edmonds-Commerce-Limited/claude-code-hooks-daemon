"""Batch packing of loose files by run and verdict (Plan 00627 Task 3.5)."""

from __future__ import annotations

import os
import shlex
import tarfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.scratch_archive import (
    ArchiveRecord,
    ArchiveStore,
    new_archive_id,
)
from claude_code_hooks_daemon.core.scratch_archive_batch import (
    BatchPackResult,
    BatchRefused,
    LooseFile,
    batch_records,
    pack_batch,
    plan_batches,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    CLAIM_PREFIX,
    Claimed,
    claim,
    fingerprint_at,
    open_dir,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import TarTool, find_gnu_tar
from claude_code_hooks_daemon.core.scratch_archive_remove import (
    RemoveRefused,
    record_claim,
    remove_claimed,
    resume_claimed,
)

MAX = 1000
CHECKOUT = "main"


def _clock() -> datetime:
    return datetime(2026, 11, 20, 6, 0, tzinfo=UTC)


#: Removal's required policy: the batch records below are not due at this clock.
POLICY: dict[str, Any] = {"clock": _clock, "retention_hours": {"DISPOSABLE": 24.0}}
HOSTILE = ("-rf", "--files-from=x", "new\nline", "sp ace", "ünï", "a\\b", "*")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "project" / "untracked" / "scratch"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def root_fd(root: Path) -> Iterator[int]:
    fd = open_dir(root)
    yield fd
    os.close(fd)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ArchiveStore]:
    with ArchiveStore.open(tmp_path / "project" / "untracked" / "scratch-archive") as opened:
        with opened.lock():
            yield opened


@pytest.fixture
def tar() -> TarTool:
    return find_gnu_tar()


def _claim(parent_fd: int, name: str, store: ArchiveStore | None = None) -> Claimed:
    """Claim ``name``; with a store, record the claim first as a sweep does."""
    expected = fingerprint_at(parent_fd, name, max_inodes=MAX)
    if store is not None:
        record_claim(
            store,
            expected,
            parent_fd=parent_fd,
            name=name,
            archive_id=new_archive_id(),
            original_path=f"untracked/scratch/{name}",
            checkout=CHECKOUT,
            at=_clock(),
        )
    result = claim(parent_fd, name, expected, max_inodes=MAX)
    assert isinstance(result, Claimed)
    return result


def _loose(root: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    content = {}
    for index, name in enumerate(names):
        data = f"content {index} of {name!r}\n".encode()
        (root / name).write_bytes(data)
        content[name] = data
    return content


def _records(
    result_names: tuple[str, ...], store: ArchiveStore, claims: list[Claimed], tar: TarTool
) -> tuple[ArchiveRecord, ...]:
    result = pack_batch(claims, store, new_archive_id(), tar=tar)
    assert result.entries == result_names
    return batch_records(
        result,
        directory="untracked/scratch",
        checkout=CHECKOUT,
        verdict="DISPOSABLE",
        proof_ids=("P1",),
        packed_at="2026-11-20T00:00:00Z",
        expires_at="2026-11-20T12:00:00Z",
    )


def _archive_files(store: ArchiveStore, archive_id: str) -> dict[str, bytes]:
    found = {}
    with tarfile.open(store.path / f"{archive_id}.tar") as archive:
        for member in archive.getmembers():
            if member.issym():
                found[member.name] = member.linkname.encode()
                continue
            extracted = archive.extractfile(member)
            assert extracted is not None
            found[member.name] = extracted.read()
    return found


def _store_files(store: ArchiveStore) -> list[str]:
    return sorted(p.name for p in store.path.iterdir() if p.name.endswith(".tar"))


class TestPlanBatches:
    def test_groups_by_verdict_and_splits_by_count_and_bytes(self) -> None:
        files = [
            LooseFile("a", "DISPOSABLE", 10),
            LooseFile("b", "UNCERTAIN", 10),
            LooseFile("c", "DISPOSABLE", 10),
            LooseFile("d", "DISPOSABLE", 10),
            LooseFile("e", "DISPOSABLE", 100),
        ]
        batches = plan_batches(files, max_members=2, max_bytes=50)
        assert batches == [
            ("DISPOSABLE", ("a", "c")),
            ("DISPOSABLE", ("d",)),
            ("DISPOSABLE", ("e",)),
            ("UNCERTAIN", ("b",)),
        ]

    def test_refuses_a_name_twice_and_a_bad_name(self) -> None:
        with pytest.raises(BatchRefused):
            plan_batches(
                [LooseFile("a", "DISPOSABLE", 1), LooseFile("a", "UNCERTAIN", 1)],
                max_members=5,
                max_bytes=5,
            )
        for bad in ("", "x/y", "..", CLAIM_PREFIX + "x"):
            with pytest.raises(BatchRefused):
                plan_batches([LooseFile(bad, "DISPOSABLE", 1)], max_members=5, max_bytes=5)

    def test_refuses_non_positive_limits(self) -> None:
        with pytest.raises(BatchRefused):
            plan_batches([], max_members=0, max_bytes=5)


class TestPackBatch:
    def test_round_trip_with_hostile_names_and_a_link(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        content = _loose(root, HOSTILE)
        (root / "lnk").symlink_to("../../outside-target")
        names = tuple(sorted((*HOSTILE, "lnk")))
        claims = [_claim(root_fd, n) for n in names]
        records = _records(names, store, claims, tar)
        assert len({r.archive_id for r in records}) == 1
        assert [r.original_path for r in records] == [f"untracked/scratch/{n}" for n in names]
        for record in records:
            store.append(record)
        archived = _archive_files(store, records[0].archive_id)
        for name, data in content.items():
            assert archived[f"./{CLAIM_PREFIX}{name}"] == data
        for name, record in zip(names, records, strict=True):
            remove_claimed(
                root_fd, CLAIM_PREFIX + name, store, record, tar=tar, max_inodes=MAX, **POLICY
            )
        assert sorted(p.name for p in root.iterdir()) == []
        assert _store_files(store) == [f"{records[0].archive_id}.tar"]

    def test_a_directory_is_not_a_loose_file(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        (root / "d").mkdir()
        _loose(root, ("f",))
        claims = [_claim(root_fd, "d"), _claim(root_fd, "f")]
        with pytest.raises(BatchRefused):
            pack_batch(claims, store, new_archive_id(), tar=tar)
        assert _store_files(store) == []

    def test_a_hard_linked_file_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, tmp_path: Path
    ) -> None:
        _loose(root, ("f",))
        os.link(root / "f", tmp_path / "other-name")
        with pytest.raises(BatchRefused):
            pack_batch([_claim(root_fd, "f")], store, new_archive_id(), tar=tar)
        assert _store_files(store) == []

    def test_claims_from_two_directories_are_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        (root / "sub").mkdir()
        _loose(root, ("f",))
        _loose(root / "sub", ("g",))
        sub_fd = open_dir(root / "sub")
        try:
            claims = [_claim(root_fd, "f"), _claim(sub_fd, "g")]
            with pytest.raises(BatchRefused):
                pack_batch(claims, store, new_archive_id(), tar=tar)
        finally:
            os.close(sub_fd)
        assert _store_files(store) == []

    def test_a_file_changed_after_its_claim_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _loose(root, ("f", "g"))
        claims = [_claim(root_fd, "f"), _claim(root_fd, "g")]
        (root / (CLAIM_PREFIX + "g")).write_bytes(b"a late writer was here, longer\n")
        with pytest.raises(BatchRefused):
            pack_batch(claims, store, new_archive_id(), tar=tar)
        assert _store_files(store) == []

    def test_empty_and_duplicate_claims_are_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        with pytest.raises(BatchRefused):
            pack_batch([], store, new_archive_id(), tar=tar)
        _loose(root, ("f",))
        handle = _claim(root_fd, "f")
        with pytest.raises(BatchRefused):
            pack_batch([handle, handle], store, new_archive_id(), tar=tar)

    def test_needs_the_store_lock(
        self, root: Path, root_fd: int, tmp_path: Path, tar: TarTool
    ) -> None:
        _loose(root, ("f",))
        with ArchiveStore.open(tmp_path / "unlocked-store") as unlocked:
            with pytest.raises(BatchRefused):
                pack_batch([_claim(root_fd, "f")], unlocked, new_archive_id(), tar=tar)


class TestBatchRemoval:
    def test_a_file_changed_after_recording_is_not_removed(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _loose(root, ("f", "g"))
        records = _records(("f", "g"), store, [_claim(root_fd, "f"), _claim(root_fd, "g")], tar)
        for record in records:
            store.append(record)
        (root / (CLAIM_PREFIX + "g")).write_bytes(b"changed")
        with pytest.raises(RemoveRefused):
            remove_claimed(
                root_fd, CLAIM_PREFIX + "g", store, records[1], tar=tar, max_inodes=MAX, **POLICY
            )
        assert (root / (CLAIM_PREFIX + "g")).read_bytes() == b"changed"

    def test_one_files_record_does_not_remove_another_file(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _loose(root, ("f", "g"))
        records = _records(("f", "g"), store, [_claim(root_fd, "f"), _claim(root_fd, "g")], tar)
        for record in records:
            store.append(record)
        with pytest.raises(RemoveRefused):
            remove_claimed(
                root_fd, CLAIM_PREFIX + "g", store, records[0], tar=tar, max_inodes=MAX, **POLICY
            )
        assert (root / (CLAIM_PREFIX + "g")).exists()


STEPS = ("packed", "one-record", "all-records", "one-removed", "done")


@pytest.mark.parametrize("stop_at", STEPS)
def test_a_crash_after_each_step_converges(
    stop_at: str, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
) -> None:
    """Hard stop after each step, then resume every leftover claim; nothing is lost."""
    names = ("f", "g", "h")
    content = _loose(root, names)
    claims = [_claim(root_fd, n, store) for n in names]
    result = pack_batch(claims, store, new_archive_id(), tar=tar)
    records = batch_records(
        result,
        directory="untracked/scratch",
        checkout=CHECKOUT,
        verdict="DISPOSABLE",
        proof_ids=("P1",),
        packed_at="2026-11-20T00:00:00Z",
        expires_at=None,
    )
    if stop_at != "packed":
        store.append(records[0])
    if stop_at in ("all-records", "one-removed", "done"):
        for record in records[1:]:
            store.append(record)
    if stop_at in ("one-removed", "done"):
        remove_claimed(
            root_fd, CLAIM_PREFIX + "f", store, records[0], tar=tar, max_inodes=MAX, **POLICY
        )
    if stop_at == "done":
        for name, record in zip(names[1:], records[1:], strict=True):
            remove_claimed(
                root_fd, CLAIM_PREFIX + name, store, record, tar=tar, max_inodes=MAX, **POLICY
            )
    for _round in (1, 2):
        for name in names:
            resume_claimed(
                root_fd,
                CLAIM_PREFIX + name,
                store,
                checkout=CHECKOUT,
                tar=tar,
                max_inodes=MAX,
                **POLICY,
            )
    recorded = {r.original_path.rpartition("/")[2] for r in store.read_index().records}
    archived = _archive_files(store, result.archive_id)
    for name in names:
        on_disk = root / name
        if on_disk.exists():
            assert on_disk.read_bytes() == content[name]
        else:
            assert name in recorded
            assert archived[f"./{CLAIM_PREFIX}{name}"] == content[name]
        assert not (root / (CLAIM_PREFIX + name)).exists()


@pytest.mark.parametrize("name", ["it's $(id).txt", "a`b`.txt", "$HOME.txt", "plain.txt"])
def test_the_printed_restore_command_is_shell_quoted(name: str) -> None:
    """D-EXEC 2 (Task 3.9): the command round-trips through a shell, so pasting it
    names the entry and runs nothing."""
    result = BatchPackResult(
        archive_id="A1", entries=(name,), kinds=("file",), size=1, sha256="0" * 64
    )
    (record,) = batch_records(
        result,
        directory="untracked/scratch",
        checkout=CHECKOUT,
        verdict="DISPOSABLE",
        proof_ids=("P1",),
        packed_at="2026-11-20T00:00:00Z",
        expires_at=None,
    )
    # shlex.split never expands, so it cannot catch a double-quoted `$(...)`:
    # the command must be exactly the POSIX-quoted argv.
    argv = [
        "hooks-daemon",
        "scratch-sweep",
        "restore",
        "A1",
        "--entry",
        f"untracked/scratch/{name}",
    ]
    assert record.restore_command == shlex.join(argv)
    assert shlex.split(record.restore_command) == argv
