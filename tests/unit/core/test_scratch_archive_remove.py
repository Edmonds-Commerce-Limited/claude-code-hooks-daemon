"""Remove a claimed, archived tree, and resume a leftover claim (Plan 00627 Task 3.4).

DESIGN.md section 5.2 step 6 and section 5.3: removal is descriptor-based and
driven by a listing taken after the archive verified, never by a fresh scan; it
follows no link, stays on one mount, and refuses on any difference. It runs
only for an entry whose archive is in the index and verifies against the tree
with the recorded SHA-256. A leftover ``.sweeping-`` tree is finished when an
archive verifies against what is left, and renamed back otherwise.
"""

from __future__ import annotations

import ast
import dataclasses
import errno
import os
import shutil
import stat
import subprocess
import tarfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import claude_code_hooks_daemon
from claude_code_hooks_daemon.core import scratch_archive_pack as pack_mod
from claude_code_hooks_daemon.core import scratch_archive_remove as remove_mod
from claude_code_hooks_daemon.core.scratch_archive import (
    EVENTS_NAME,
    ArchiveRecord,
    ArchiveStore,
    ExpiredEvent,
    KeepEvent,
    new_archive_id,
)
from claude_code_hooks_daemon.core.scratch_archive_adopt import PROOF_ID as ADOPT_PROOF_ID
from claude_code_hooks_daemon.core.scratch_archive_adopt import adopt
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    CLAIM_PREFIX,
    Claimed,
    WalkRefused,
    claim,
    fingerprint_at,
    open_dir,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import TarTool, find_gnu_tar, pack
from claude_code_hooks_daemon.core.scratch_archive_remove import (
    Removed,
    RemoveRefused,
    Resumed,
    remove_claimed,
    resume_claimed,
)

MAX = 1000
CHECKOUT = "main"
Snapshot = dict[str, tuple[str, bytes]]


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


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory outside the scratch root that nothing may touch."""
    path = tmp_path / "outside"
    path.mkdir()
    (path / "keep.txt").write_text("outside content")
    return path


def _entry(root: Path, name: str = "e1") -> Path:
    entry = root / name
    (entry / "sub" / "deep").mkdir(parents=True)
    (entry / "a.txt").write_text("alpha")
    (entry / "sub" / "b.bin").write_bytes(bytes(range(256)))
    (entry / "sub" / "deep" / "c.txt").write_text("gamma")
    (entry / "rel-link").symlink_to("a.txt")
    return entry


def _claim(root_fd: int, name: str) -> Claimed:
    result = claim(root_fd, name, fingerprint_at(root_fd, name, max_inodes=MAX), max_inodes=MAX)
    assert isinstance(result, Claimed)
    return result


def _record(name: str, store: ArchiveStore, handle: Claimed, tar: TarTool) -> ArchiveRecord:
    result = pack(handle, store, new_archive_id(), tar=tar, max_inodes=MAX)
    return ArchiveRecord(
        archive_id=result.archive_id,
        original_path=f"untracked/scratch/{name}",
        checkout=CHECKOUT,
        verdict="DISPOSABLE",
        proof_ids=("P1",),
        packed_at="2026-11-20T00:00:00Z",
        expires_at=None,
        counts=result.counts,
        archive_size=result.size,
        sha256=result.sha256,
        skipped=result.skipped,
        restore_command=f"hooks-daemon scratch restore {result.archive_id}",
    )


def _archived(
    root_fd: int, store: ArchiveStore, tar: TarTool, name: str = "e1"
) -> tuple[Claimed, ArchiveRecord]:
    handle = _claim(root_fd, name)
    record = _record(name, store, handle, tar)
    store.append(record)
    return handle, record


NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
RETENTION: dict[str, float] = {"DISPOSABLE": 24.0}


def clock() -> datetime:
    return NOW


#: The required removal policy (unit 1): a clock and the verdict retention.
POLICY: dict[str, Any] = {"clock": clock, "retention_hours": RETENTION}


def _remove(
    root_fd: int, store: ArchiveStore, tar: TarTool, record: ArchiveRecord, name: str = "e1"
) -> Removed:
    return remove_claimed(
        root_fd,
        CLAIM_PREFIX + name,
        store,
        record,
        tar=tar,
        max_inodes=MAX,
        clock=clock,
        retention_hours=RETENTION,
    )


def _resume(root_fd: int, store: ArchiveStore, tar: TarTool, name: str = "e1") -> Resumed:
    return resume_claimed(
        root_fd,
        CLAIM_PREFIX + name,
        store,
        checkout=CHECKOUT,
        tar=tar,
        max_inodes=MAX,
        clock=clock,
        retention_hours=RETENTION,
    )


def _snapshot(path: Path) -> Snapshot:
    """Every name under ``path`` with its type and content, read without following links."""
    found: Snapshot = {}

    def one(rel: str, item: Path) -> None:
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode):
            found[rel] = ("link", str(item.readlink()).encode())
        elif stat.S_ISDIR(info.st_mode):
            found[rel] = ("dir", b"")
            for child in sorted(item.iterdir()):
                one(f"{rel}/{child.name}" if rel else child.name, child)
        elif stat.S_ISREG(info.st_mode):
            found[rel] = ("file", item.read_bytes())
        else:
            found[rel] = ("special", b"")

    one("", path)
    return found


def _archive_snapshot(store: ArchiveStore, record: ArchiveRecord) -> Snapshot:
    found: Snapshot = {}
    with tarfile.open(store.path / f"{record.archive_id}.tar") as archive:
        for member in archive.getmembers():
            rel = "" if member.name in (".", "./") else member.name.removeprefix("./").rstrip("/")
            if member.isdir():
                found[rel] = ("dir", b"")
            elif member.issym():
                found[rel] = ("link", member.linkname.encode())
            else:
                extracted = archive.extractfile(member)
                assert extracted is not None
                found[rel] = ("file", extracted.read())
    return found


def _outside_state(outside: Path) -> tuple[str, int]:
    keep = outside / "keep.txt"
    return keep.read_text(), keep.stat().st_mtime_ns


def _claimed_exists(root: Path, name: str = "e1") -> bool:
    return os.path.lexists(root / (CLAIM_PREFIX + name))


class TestRemoveClaimed:
    def test_removes_a_recorded_verified_tree(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        result = _remove(root_fd, store, tar, record)
        assert result.removed == 7
        assert result.archive_id == record.archive_id
        assert result.partial is False
        assert list(root.iterdir()) == []

    def test_removes_a_file_root(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        (root / "f1").write_text("file root")
        _handle, record = _archived(root_fd, store, tar, "f1")
        result = _remove(root_fd, store, tar, record, "f1")
        assert result.removed == 1
        assert list(root.iterdir()) == []

    def test_a_symlink_root_loses_only_the_link(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        (root / "l1").symlink_to(outside)
        before = _outside_state(outside)
        _handle, record = _archived(root_fd, store, tar, "l1")
        result = _remove(root_fd, store, tar, record, "l1")
        assert result.link_target == str(outside)
        assert list(root.iterdir()) == []
        assert _outside_state(outside) == before

    @pytest.mark.parametrize(
        "bad",
        ["e1", "..", ".", CLAIM_PREFIX, CLAIM_PREFIX + "../e1", CLAIM_PREFIX + CLAIM_PREFIX + "e1"],
    )
    def test_refuses_a_name_that_is_not_one_claim(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, bad: str
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        before = _snapshot(root)
        with pytest.raises(RemoveRefused):
            remove_claimed(root_fd, bad, store, record, tar=tar, max_inodes=MAX, **POLICY)
        assert _snapshot(root) == before

    def test_refuses_without_the_store_lock(
        self, tmp_path: Path, root: Path, root_fd: int, tar: TarTool
    ) -> None:
        _entry(root)
        path = tmp_path / "project" / "untracked" / "scratch-archive"
        with ArchiveStore.open(path) as opened:
            with opened.lock():
                _handle, record = _archived(root_fd, opened, tar)
            with pytest.raises(RemoveRefused, match="lock"):
                _remove(root_fd, opened, tar, record)
        assert _claimed_exists(root)

    def test_refuses_a_record_not_in_the_index(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        handle = _claim(root_fd, "e1")
        record = _record("e1", store, handle, tar)
        before = _snapshot(root)
        with pytest.raises(RemoveRefused, match="index"):
            _remove(root_fd, store, tar, record)
        assert _snapshot(root) == before

    @pytest.mark.parametrize(
        "change",
        [
            lambda r: dataclasses.replace(r, sha256="0" * 64),
            lambda r: dataclasses.replace(r, original_path="untracked/scratch/xe1"),
            lambda r: dataclasses.replace(r, checkout="other"),
        ],
        ids=["sha256", "original_path", "checkout"],
    )
    def test_refuses_a_record_that_differs_from_the_index(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        change: Callable[[ArchiveRecord], ArchiveRecord],
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        before = _snapshot(root)
        with pytest.raises(RemoveRefused):
            _remove(root_fd, store, tar, change(record))
        assert _snapshot(root) == before

    def test_refuses_a_record_for_another_entry_name(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root, "e1")
        _entry(root, "xe1")
        _h1, record = _archived(root_fd, store, tar, "e1")
        _archived(root_fd, store, tar, "xe1")
        before = _snapshot(root)
        with pytest.raises(RemoveRefused, match="names"):
            _remove(root_fd, store, tar, record, "xe1")
        assert _snapshot(root) == before

    def test_refuses_when_the_archive_differs_from_its_record(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        with open(store.path / f"{record.archive_id}.tar", "ab") as handle:
            handle.write(b"\0" * 512)
        before = _snapshot(root)
        with pytest.raises(RemoveRefused, match="SHA-256"):
            _remove(root_fd, store, tar, record)
        assert _snapshot(root) == before

    def test_refuses_when_the_archive_is_missing(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        (store.path / f"{record.archive_id}.tar").rename(store.path / "moved")
        before = _snapshot(root)
        with pytest.raises(RemoveRefused):
            _remove(root_fd, store, tar, record)
        assert _snapshot(root) == before

    @pytest.mark.parametrize("change", ["new-file", "changed-content", "fifo", "hard-link"])
    def test_refuses_content_the_archive_does_not_hold(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        outside: Path,
        change: str,
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        claimed = root / (CLAIM_PREFIX + "e1")
        if change == "new-file":
            (claimed / "late.txt").write_text("late")
        elif change == "changed-content":
            (claimed / "a.txt").write_text("ALPHA")
        elif change == "fifo":
            os.mkfifo(claimed / "pipe")
        else:
            os.link(outside / "keep.txt", claimed / "sub" / "linked")
        before = _snapshot(root)
        with pytest.raises(RemoveRefused):
            _remove(root_fd, store, tar, record)
        assert _snapshot(root) == before
        assert (outside / "keep.txt").read_text() == "outside content"

    def test_removes_a_fifo_the_record_lists_as_skipped(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry = _entry(root)
        os.mkfifo(entry / "pipe")
        _handle, record = _archived(root_fd, store, tar)
        assert record.skipped == ("pipe",)
        _remove(root_fd, store, tar, record)
        assert list(root.iterdir()) == []

    def test_refuses_a_changed_fingerprint(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        handle, record = _archived(root_fd, store, tar)
        stale = dataclasses.replace(handle.fingerprint, count=handle.fingerprint.count + 1)
        before = _snapshot(root)
        with pytest.raises(RemoveRefused, match="fingerprint"):
            remove_claimed(
                root_fd,
                handle.claimed_name,
                store,
                record,
                tar=tar,
                max_inodes=MAX,
                expected=stale,
                **POLICY,
            )
        assert _snapshot(root) == before

    def test_accepts_the_claim_fingerprint(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        handle, record = _archived(root_fd, store, tar)
        remove_claimed(
            root_fd,
            handle.claimed_name,
            store,
            record,
            tar=tar,
            max_inodes=MAX,
            expected=handle.fingerprint,
            **POLICY,
        )
        assert list(root.iterdir()) == []

    def test_refuses_a_tree_deeper_than_the_cap(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        before = _snapshot(root)
        with pytest.raises(RemoveRefused):
            remove_claimed(
                root_fd,
                CLAIM_PREFIX + "e1",
                store,
                record,
                tar=tar,
                max_inodes=MAX,
                max_depth=1,
                **POLICY,
            )
        assert _snapshot(root) == before


class TestEscapes:
    def test_symlink_swapped_in_after_verify_is_never_crossed(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        outside: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        claimed = root / (CLAIM_PREFIX + "e1")
        real_verify = pack_mod.verify

        def verify_then_swap(*args: Any, **kwargs: Any) -> Any:
            result = real_verify(*args, **kwargs)
            (claimed / "sub").rename(root.parent / "sub-moved")
            (claimed / "sub").symlink_to(outside)
            return result

        monkeypatch.setattr(remove_mod, "verify", verify_then_swap)
        before = _outside_state(outside)
        with pytest.raises(RemoveRefused):
            _remove(root_fd, store, tar, record)
        assert _outside_state(outside) == before
        assert (claimed / "a.txt").read_text() == "alpha"

    def test_symlink_swapped_in_mid_removal_is_never_crossed(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        outside: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The swap lands between the lstat and the open: O_NOFOLLOW still refuses it."""
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        claimed = root / (CLAIM_PREFIX + "e1")
        real_lstat = remove_mod._lstat_at

        def lstat_then_swap(dir_fd: int, name: str) -> os.stat_result:
            info = real_lstat(dir_fd, name)
            if name == "sub":
                (claimed / "sub").rename(root.parent / "sub-moved")
                (claimed / "sub").symlink_to(outside)
            return info

        monkeypatch.setattr(remove_mod, "_lstat_at", lstat_then_swap)
        before = _outside_state(outside)
        with pytest.raises(RemoveRefused):
            _remove(root_fd, store, tar, record)
        assert _outside_state(outside) == before
        assert (root.parent / "sub-moved" / "deep" / "c.txt").read_text() == "gamma"

    def test_file_swapped_for_a_link_mid_removal_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        outside: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        claimed = root / (CLAIM_PREFIX + "e1")
        real_lstat = remove_mod._lstat_at

        def swap_then_lstat(dir_fd: int, name: str) -> os.stat_result:
            if name == "a.txt":
                (claimed / "a.txt").unlink()
                (claimed / "a.txt").symlink_to(outside / "keep.txt")
            return real_lstat(dir_fd, name)

        monkeypatch.setattr(remove_mod, "_lstat_at", swap_then_lstat)
        before = _outside_state(outside)
        with pytest.raises(RemoveRefused, match="changed"):
            _remove(root_fd, store, tar, record)
        assert _outside_state(outside) == before
        assert (claimed / "a.txt").is_symlink()

    def test_a_name_added_mid_removal_stops_the_removal(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        claimed = root / (CLAIM_PREFIX + "e1")
        real_lstat = remove_mod._lstat_at

        def add_then_lstat(dir_fd: int, name: str) -> os.stat_result:
            if name == "a.txt":
                (claimed / "late.txt").write_text("late writer")
            return real_lstat(dir_fd, name)

        monkeypatch.setattr(remove_mod, "_lstat_at", add_then_lstat)
        with pytest.raises(RemoveRefused):
            _remove(root_fd, store, tar, record)
        assert (claimed / "late.txt").read_text() == "late writer"

    def test_a_directory_on_another_mount_is_never_entered(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A same-filesystem bind mount keeps ``st_dev``; the mount id tells it apart."""
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        claimed = root / (CLAIM_PREFIX + "e1")
        sub_ino = (claimed / "sub").stat().st_ino
        real_mount_id = remove_mod._mount_id

        def mount_id(fd: int) -> int:
            value = real_mount_id(fd)
            return value + 1 if os.fstat(fd).st_ino == sub_ino else value

        monkeypatch.setattr(remove_mod, "_mount_id", mount_id)
        with pytest.raises(RemoveRefused, match="mount"):
            _remove(root_fd, store, tar, record)
        assert _snapshot(claimed / "sub")["deep/c.txt"] == ("file", b"gamma")

    def test_mount_id_is_read_for_a_real_descriptor(self, root_fd: int) -> None:
        assert remove_mod._mount_id(root_fd) >= 0

    def test_a_real_bind_mount_is_never_entered(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, outside: Path
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        target = root / (CLAIM_PREFIX + "e1") / "sub" / "deep"
        try:
            subprocess.run(
                ["mount", "--bind", str(outside), str(target)],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            pytest.skip(f"bind mount unavailable here: {exc}")
        try:
            before = _outside_state(outside)
            with pytest.raises(RemoveRefused):
                _remove(root_fd, store, tar, record)
            assert _outside_state(outside) == before
        finally:
            subprocess.run(["umount", str(target)], check=True, timeout=10)

    def test_a_read_only_directory_is_made_writable_through_its_descriptor(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Root ignores directory modes, so the EACCES is injected once."""
        entry = _entry(root)
        (entry / "sub" / "deep").chmod(0o555)
        _handle, record = _archived(root_fd, store, tar)
        real_unlink = os.unlink
        real_fchmod = os.fchmod
        fchmods: list[int] = []
        failed: list[str] = []

        def unlink(name: str, *, dir_fd: int) -> None:
            if name == "c.txt" and not failed:
                failed.append(name)
                raise PermissionError(errno.EACCES, "Permission denied", name)
            real_unlink(name, dir_fd=dir_fd)

        def fchmod(fd: int, mode: int) -> None:
            fchmods.append(mode)
            real_fchmod(fd, mode)

        monkeypatch.setattr(os, "unlink", unlink)
        monkeypatch.setattr(os, "fchmod", fchmod)
        _remove(root_fd, store, tar, record)
        assert failed == ["c.txt"]
        assert fchmods and all(mode & stat.S_IWUSR for mode in fchmods)
        assert list(root.iterdir()) == []

    def test_an_unreadable_directory_is_refused_before_anything_goes(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        if os.geteuid() == 0:
            pytest.skip("root reads every directory")
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        claimed = root / (CLAIM_PREFIX + "e1")
        (claimed / "sub").chmod(0)
        try:
            with pytest.raises(RemoveRefused):
                _remove(root_fd, store, tar, record)
        finally:
            (claimed / "sub").chmod(0o755)
        assert (claimed / "a.txt").exists()

    def test_an_unreadable_directory_injected_is_refused_before_anything_goes(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The root-proof twin of the test above: a walk that cannot list refuses."""
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        before = _snapshot(root)

        def unreadable(*_args: Any, **_kwargs: Any) -> Any:
            raise WalkRefused("cannot list a directory: Permission denied")

        monkeypatch.setattr(remove_mod, "walk_tree", unreadable)
        with pytest.raises(RemoveRefused, match="walked"):
            _remove(root_fd, store, tar, record)
        assert _snapshot(root) == before

    def test_an_immutable_file_stops_the_removal_and_a_resume_finishes_it(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """EPERM (immutable) is never chmod-retried; what is left stays claimed."""
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        real_unlink = os.unlink

        def unlink(name: str, *, dir_fd: int) -> None:
            if name == "c.txt":
                raise PermissionError(errno.EPERM, "Operation not permitted", name)
            real_unlink(name, dir_fd=dir_fd)

        monkeypatch.setattr(os, "unlink", unlink)
        with pytest.raises(RemoveRefused):
            _remove(root_fd, store, tar, record)
        assert (root / (CLAIM_PREFIX + "e1") / "sub" / "deep" / "c.txt").exists()
        monkeypatch.setattr(os, "unlink", real_unlink)
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "removed"
        assert resumed.removed is not None and resumed.removed.partial is True
        assert list(root.iterdir()) == []

    def test_a_real_immutable_file_is_never_removed(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        target = root / (CLAIM_PREFIX + "e1") / "sub" / "deep" / "c.txt"
        try:
            subprocess.run(
                ["chattr", "+i", str(target)], check=True, capture_output=True, timeout=10
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            pytest.skip(f"chattr unavailable here: {exc}")
        try:
            with pytest.raises(RemoveRefused):
                _remove(root_fd, store, tar, record)
            assert target.read_text() == "gamma"
        finally:
            subprocess.run(["chattr", "-i", str(target)], check=True, timeout=10)


class TestResume:
    def test_an_absent_claim_is_converged(
        self, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        assert _resume(root_fd, store, tar).outcome == "absent"

    def test_no_record_renames_back(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry = _entry(root)
        before = _snapshot(entry)
        _claim(root_fd, "e1")
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "renamed-back"
        assert _snapshot(entry) == before

    def test_no_record_and_the_name_retaken_is_stuck(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _claim(root_fd, "e1")
        (root / "e1").mkdir()
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "stuck"
        assert (root / (CLAIM_PREFIX + "e1") / "a.txt").read_text() == "alpha"

    def test_a_verified_record_finishes_the_removal(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _archived(root_fd, store, tar)
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "removed"
        assert list(root.iterdir()) == []

    def test_content_the_archive_lacks_is_renamed_back(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _archived(root_fd, store, tar)
        (root / (CLAIM_PREFIX + "e1") / "late.txt").write_text("late")
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "renamed-back"
        assert (root / "e1" / "late.txt").read_text() == "late"
        assert (root / "e1" / "a.txt").read_text() == "alpha"

    def test_another_checkouts_record_is_not_used(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _archived(root_fd, store, tar)
        resumed = resume_claimed(
            root_fd,
            CLAIM_PREFIX + "e1",
            store,
            checkout="other",
            tar=tar,
            max_inodes=MAX,
            **POLICY,
        )
        assert resumed.outcome == "renamed-back"
        assert (root / "e1" / "a.txt").exists()

    def test_an_older_record_of_the_same_name_does_not_authorise(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        handle, old = _archived(root_fd, store, tar)
        remove_claimed(root_fd, handle.claimed_name, store, old, tar=tar, max_inodes=MAX, **POLICY)
        entry = root / "e1"
        entry.mkdir()
        (entry / "new.txt").write_text("new content")
        _claim(root_fd, "e1")
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "renamed-back"
        assert (entry / "new.txt").read_text() == "new content"

    def test_the_matching_record_among_several_authorises(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        (root / "e1").mkdir()
        (root / "e1" / "old.txt").write_text("old")
        handle, old = _archived(root_fd, store, tar)
        remove_claimed(root_fd, handle.claimed_name, store, old, tar=tar, max_inodes=MAX, **POLICY)
        _entry(root)
        _archived(root_fd, store, tar)
        assert _resume(root_fd, store, tar).outcome == "removed"
        assert list(root.iterdir()) == []

    def test_a_partly_removed_tree_is_stuck_when_tar_cannot_run(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No check is not a failed check: the half-removed tree is never renamed back."""
        _entry(root)
        _archived(root_fd, store, tar)
        (root / (CLAIM_PREFIX + "e1") / "sub" / "b.bin").unlink()

        def no_tar(*_args: Any, **_kwargs: Any) -> Any:
            raise OSError(errno.ENOENT, "No such file or directory", "tar")

        monkeypatch.setattr(pack_mod, "_run_tar", no_tar)
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "stuck"
        assert not (root / "e1").exists()
        assert (root / (CLAIM_PREFIX + "e1") / "a.txt").read_text() == "alpha"

    def test_refuses_an_unclaimed_name(
        self, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        with pytest.raises(RemoveRefused):
            resume_claimed(
                root_fd, "e1", store, checkout=CHECKOUT, tar=tar, max_inodes=MAX, **POLICY
            )

    def test_refuses_without_the_store_lock(
        self, tmp_path: Path, root: Path, root_fd: int, tar: TarTool
    ) -> None:
        _entry(root)
        _claim(root_fd, "e1")
        with ArchiveStore.open(tmp_path / "project" / "untracked" / "scratch-archive") as opened:
            with pytest.raises(RemoveRefused, match="lock"):
                _resume(root_fd, opened, tar)
        assert _claimed_exists(root)


# --- adopted (P6) archives: unit 4 of Task 3.8 ------------------------------------

_TAR_FLAGS = {"gzip": "-czf", "none": "-cf", "xz": "-cJf"}


def _adopted(
    root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, compression: str = "gzip"
) -> ArchiveRecord:
    """Adopt a hand-made ``e1/...`` tarball of the entry, then claim the entry."""
    if compression == "xz" and shutil.which("xz", path="/usr/bin:/bin") is None:
        pytest.skip("xz is not installed")
    proc = subprocess.run(
        [tar.path, "--format=gnu", _TAR_FLAGS[compression], "e1.tar.x", "--", "e1"],
        cwd=root,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    adopted = adopt(
        store,
        root_fd,
        "e1",
        "e1.tar.x",
        original_path="untracked/scratch/e1",
        checkout=CHECKOUT,
        verdict="DISPOSABLE",
        proof_ids=(ADOPT_PROOF_ID,),
        expires_at=None,
        restore_command="hooks-daemon scratch-restore",
        now=NOW,
        tar=tar,
        max_inodes=MAX,
    )
    record = store.read_index().by_id(adopted.archive_id)
    assert record is not None and ADOPT_PROOF_ID in record.proof_ids
    _claim(root_fd, "e1")
    return record


class TestAdoptedArchives:
    """Removal's re-verify reads a P6 archive by the layout its record names."""

    @pytest.mark.parametrize("compression", ["gzip", "none", "xz"])
    def test_an_adopted_original_is_removed(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, compression: str
    ) -> None:
        _entry(root)
        record = _adopted(root, root_fd, store, tar, compression)
        result = _remove(root_fd, store, tar, record)
        assert (result.removed, result.partial) == (7, False)
        assert list(root.iterdir()) == []

    def test_an_adopted_empty_directory_is_removed(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        (root / "e1").mkdir()
        record = _adopted(root, root_fd, store, tar)
        assert _remove(root_fd, store, tar, record).removed == 1
        assert list(root.iterdir()) == []

    def test_a_changed_file_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        record = _adopted(root, root_fd, store, tar)
        changed = root / (CLAIM_PREFIX + "e1") / "a.txt"
        changed.write_text("alphA")
        with pytest.raises(RemoveRefused, match="does not verify"):
            _remove(root_fd, store, tar, record)
        assert changed.read_text() == "alphA"

    def test_an_extra_file_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        record = _adopted(root, root_fd, store, tar)
        (root / (CLAIM_PREFIX + "e1") / "late.txt").write_text("late")
        with pytest.raises(RemoveRefused):
            _remove(root_fd, store, tar, record)
        assert (root / (CLAIM_PREFIX + "e1") / "a.txt").read_text() == "alpha"

    def test_an_adopted_archive_without_its_p6_record_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        record = _adopted(root, root_fd, store, tar)
        plain = dataclasses.replace(record, proof_ids=("P1",))
        with pytest.raises(RemoveRefused, match="does not verify"):
            remove_mod._prove(
                root_fd,
                CLAIM_PREFIX + "e1",
                store,
                plain,
                tar=tar,
                max_inodes=MAX,
                max_depth=64,
                timeout=60.0,
                partial=False,
            )
        assert (root / (CLAIM_PREFIX + "e1") / "a.txt").read_text() == "alpha"

    def test_a_p6_record_against_a_packed_archive_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        handle = _claim(root_fd, "e1")
        packed = _record("e1", store, handle, tar)
        record = dataclasses.replace(packed, proof_ids=(ADOPT_PROOF_ID,))
        store.append(record)
        with pytest.raises(RemoveRefused, match="does not verify"):
            _remove(root_fd, store, tar, record)
        assert (root / (CLAIM_PREFIX + "e1") / "a.txt").read_text() == "alpha"

    def test_resume_after_a_partial_removal_finishes(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _adopted(root, root_fd, store, tar, "none")
        claimed = root / (CLAIM_PREFIX + "e1")
        (claimed / "a.txt").unlink()
        (claimed / "sub" / "deep" / "c.txt").unlink()
        (claimed / "sub" / "deep").rmdir()
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "removed"
        assert list(root.iterdir()) == []

    def test_resume_refuses_a_changed_remaining_file(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _adopted(root, root_fd, store, tar)
        claimed = root / (CLAIM_PREFIX + "e1")
        (claimed / "a.txt").unlink()
        (claimed / "sub" / "b.bin").write_bytes(bytes(256))
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "renamed-back"
        assert (root / "e1" / "sub" / "b.bin").read_bytes() == bytes(256)


class TestVerifyAdoptedLayout:
    """``verify`` and ``verify_remaining`` take the layout as an argument, never a guess."""

    def test_verify_maps_walk_names_to_the_adopted_root(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        record = _adopted(root, root_fd, store, tar)
        verified = pack_mod.verify(
            root_fd,
            CLAIM_PREFIX + "e1",
            store,
            record.archive_id,
            tar=tar,
            max_inodes=MAX,
            expected_sha256=record.sha256,
            adopted_root="e1",
        )
        assert "./" in verified.members and "./a.txt" in verified.members

    def test_a_wrong_adopted_root_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        record = _adopted(root, root_fd, store, tar)
        for check in (pack_mod.verify, pack_mod.verify_remaining):
            with pytest.raises(pack_mod.VerifyFailed):
                check(
                    root_fd,
                    CLAIM_PREFIX + "e1",
                    store,
                    record.archive_id,
                    tar=tar,
                    max_inodes=MAX,
                    expected_sha256=record.sha256,
                    adopted_root="other",
                )

    def test_an_unknown_archive_format_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        record = _adopted(root, root_fd, store, tar)
        path = store.path / f"{record.archive_id}.tar"
        path.write_bytes(b"not a tar at all" * 64)
        with pytest.raises(pack_mod.VerifyFailed, match="format"):
            pack_mod.verify(
                root_fd,
                CLAIM_PREFIX + "e1",
                store,
                record.archive_id,
                tar=tar,
                max_inodes=MAX,
                adopted_root="e1",
            )

    def test_an_adopted_root_on_a_file_claim_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        (root / "f1").write_text("file root")
        handle, record = _archived(root_fd, store, tar, "f1")
        with pytest.raises(pack_mod.VerifyFailed):
            pack_mod.verify(
                root_fd,
                handle.claimed_name,
                store,
                record.archive_id,
                tar=tar,
                max_inodes=MAX,
                adopted_root="f1",
            )


PAST = "2026-11-19T00:00:00Z"
FUTURE = "2026-12-01T00:00:00Z"


def _archived_with(
    root_fd: int, store: ArchiveStore, tar: TarTool, **changes: Any
) -> tuple[Claimed, ArchiveRecord]:
    handle = _claim(root_fd, "e1")
    record = dataclasses.replace(_record("e1", store, handle, tar), **changes)
    store.append(record)
    return handle, record


def _due(root_fd: int, store: ArchiveStore, tar: TarTool) -> tuple[Claimed, ArchiveRecord]:
    """An archive whose expiry (``expires_at`` and packed + 24h) is before NOW."""
    return _archived_with(root_fd, store, tar, expires_at=PAST, packed_at="2026-11-18T00:00:00Z")


def _archive_path(store: ArchiveStore, record: ArchiveRecord) -> Path:
    return store.path / f"{record.archive_id}.tar"


class TestRemovalReadsTheEvents:
    """Unit 1: removal refuses an archive that is expired, due or incomplete."""

    def test_an_expired_event_refuses_removal(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        store.append_event(ExpiredEvent(archive_id=record.archive_id, at=PAST))
        before = _snapshot(root)
        with pytest.raises(RemoveRefused, match="expired"):
            _remove(root_fd, store, tar, record)
        assert _snapshot(root) == before

    def test_a_retention_due_archive_refuses_removal(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _due(root_fd, store, tar)
        before = _snapshot(root)
        with pytest.raises(RemoveRefused, match="due"):
            _remove(root_fd, store, tar, record)
        assert _snapshot(root) == before

    def test_a_keep_that_extends_the_expiry_allows_removal(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _due(root_fd, store, tar)
        store.append_event(
            KeepEvent(
                archive_id=record.archive_id,
                original_path=record.original_path,
                reason="still wanted",
                kept_at=PAST,
                until=FUTURE,
            )
        )
        _remove(root_fd, store, tar, record)
        assert list(root.iterdir()) == []

    def test_a_not_yet_due_archive_allows_removal(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived_with(root_fd, store, tar, expires_at=FUTURE)
        _remove(root_fd, store, tar, record)
        assert list(root.iterdir()) == []

    def test_a_null_expiry_allows_removal(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        assert record.expires_at is None
        _remove(root_fd, store, tar, record)
        assert list(root.iterdir()) == []

    def test_a_torn_events_tail_refuses_removal(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _archived(root_fd, store, tar)
        with open(store.path / EVENTS_NAME, "ab") as handle:
            handle.write(b'{"kind": "exp')
        before = _snapshot(root)
        with pytest.raises(RemoveRefused, match="torn"):
            _remove(root_fd, store, tar, record)
        assert _snapshot(root) == before

    @pytest.mark.parametrize("bad_clock", ["raises", "naive"])
    def test_a_bad_clock_refuses_removal(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, bad_clock: str
    ) -> None:
        _entry(root)
        _handle, record = _archived_with(root_fd, store, tar, expires_at=FUTURE)

        def broken() -> datetime:
            if bad_clock == "raises":
                raise OSError("no clock")
            return datetime(2026, 11, 20, 12, 0)

        before = _snapshot(root)
        with pytest.raises(RemoveRefused, match="clock"):
            remove_claimed(
                root_fd,
                CLAIM_PREFIX + "e1",
                store,
                record,
                tar=tar,
                max_inodes=MAX,
                clock=broken,
                retention_hours=RETENTION,
            )
        assert _snapshot(root) == before

    def test_resume_of_an_intact_tree_with_a_due_archive_renames_back(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _due(root_fd, store, tar)
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "renamed-back"
        assert (root / "e1" / "a.txt").read_text() == "alpha"

    def test_resume_of_a_partly_removed_tree_with_a_due_archive_is_stuck(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        _handle, record = _due(root_fd, store, tar)
        (root / (CLAIM_PREFIX + "e1") / "sub" / "b.bin").unlink()
        before = _snapshot(root)
        resumed = _resume(root_fd, store, tar)
        assert resumed.outcome == "stuck"
        assert "a human restores" in resumed.reason
        assert _snapshot(root) == before
        assert _archive_path(store, record).exists()


class _Crash(Exception):
    """A fault injected between two steps."""


STEPS = ("claim", "pack", "append", "unlink-1", "unlink-3", "rmdir-1", "rmdir-3", "remove")


def _sequence(
    root_fd: int,
    store: ArchiveStore,
    tar: TarTool,
    stop_at: str,
    hard: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run claim -> pack -> record -> remove, faulting after ``stop_at`` with no cleanup.

    ``hard`` returns mid-sequence as a killed process would; otherwise an
    exception is raised. A fault inside the removal fails the ``n``-th
    ``unlink`` or ``rmdir`` and is always raised.
    """

    def fault() -> None:
        if not hard:
            raise _Crash(stop_at)

    handle = _claim(root_fd, "e1")
    if stop_at == "claim":
        return fault()
    record = _record("e1", store, handle, tar)
    if stop_at == "pack":
        return fault()
    store.append(record)
    if stop_at == "append":
        return fault()
    if stop_at.startswith(("unlink-", "rmdir-")):
        op, count = stop_at.split("-")
        real: Callable[..., None] = getattr(os, op)
        calls: list[str] = []

        def failing(name: str, *, dir_fd: int) -> None:
            calls.append(name)
            if len(calls) == int(count):
                raise _Crash(stop_at)
            real(name, dir_fd=dir_fd)

        monkeypatch.setattr(os, op, failing)
        try:
            _remove(root_fd, store, tar, record)
        finally:
            monkeypatch.setattr(os, op, real)
        return None
    _remove(root_fd, store, tar, record)
    return fault()


def _preserved(root: Path, store: ArchiveStore, original: Snapshot) -> bool:
    """The original is back under its name, or a recorded archive holds all of it."""
    if os.path.lexists(root / "e1"):
        return _snapshot(root / "e1") == original
    return any(
        record.original_path.endswith("/e1") and _archive_snapshot(store, record) == original
        for record in store.read_index().records
    )


class TestCrashSafety:
    @pytest.mark.parametrize("hard", [False, True], ids=["raised", "hard-stop"])
    @pytest.mark.parametrize("stop_at", STEPS)
    def test_every_fault_point_resumes_or_refuses_and_converges(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
        stop_at: str,
        hard: bool,
    ) -> None:
        original = _snapshot(_entry(root))
        try:
            _sequence(root_fd, store, tar, stop_at, hard, monkeypatch)
        except (_Crash, RemoveRefused):
            assert _claimed_exists(root) or stop_at == "remove"
        assert _claimed_exists(root) or _preserved(root, store, original)
        first = _resume(root_fd, store, tar)
        assert _preserved(root, store, original)
        assert not _claimed_exists(root)
        second = _resume(root_fd, store, tar)
        assert second.outcome == "absent"
        assert _preserved(root, store, original)
        if stop_at in {"claim", "pack"}:
            assert first.outcome == "renamed-back"
        elif stop_at == "remove":
            assert first.outcome == "absent"
        else:
            assert first.outcome == "removed"


_DELETERS = frozenset(
    {
        "unlink",
        "rmdir",
        "rmtree",
        "remove",
        "removedirs",
        "replace",
        "rename",
        "renames",
        "truncate",
        "ftruncate",
    }
)


def _deleter(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in _DELETERS:
        return node.attr
    if isinstance(node, ast.Name) and node.id in _DELETERS:
        return node.id
    return None


def _scan(node: ast.AST, scope: str, module: str, found: set[tuple[str, str, str]]) -> None:
    """Record every deleting reference under ``node``, scoped to its innermost function."""
    for child in ast.iter_child_nodes(node):
        inner = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else scope
        name = _deleter(child)
        if name is not None:
            found.add((module, inner, name))
        _scan(child, inner, module, found)


def _deletion_surfaces() -> set[tuple[str, str, str]]:
    """Every reference to a deleting call in the archive modules: (module, scope, call).

    The whole module is scanned, so a module- or class-level alias such as
    ``_rm = shutil.rmtree`` is listed under ``<module>``.
    """
    core = Path(claude_code_hooks_daemon.__file__).parent / "core"
    found: set[tuple[str, str, str]] = set()
    for path in sorted(core.glob("scratch_archive*.py")):
        _scan(ast.parse(path.read_text(encoding="utf-8")), "<module>", path.name, found)
    return found


def test_the_surface_scan_sees_a_module_level_alias() -> None:
    found: set[tuple[str, str, str]] = set()
    _scan(ast.parse("import shutil\n_rm = shutil.rmtree\n"), "<module>", "m.py", found)
    assert found == {("m.py", "<module>", "rmtree")}


_CTYPES_MOVERS = frozenset({"rename_noreplace", "rename_noreplace_between", "_RENAMEAT2"})


def _ctypes_moves() -> set[tuple[str, str, str]]:
    """Every reference to the ctypes ``renameat2`` movers, which the deleter scan cannot see."""
    core = Path(claude_code_hooks_daemon.__file__).parent / "core"
    found: set[tuple[str, str, str]] = set()

    def scan(node: ast.AST, scope: str, module: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = (
                child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else scope
            )
            name = None
            if isinstance(child, ast.Name) and child.id in _CTYPES_MOVERS:
                name = child.id
            elif isinstance(child, ast.Attribute) and child.attr in _CTYPES_MOVERS:
                name = child.attr
            if name is not None:
                found.add((module, inner, name))
            scan(child, inner, module)

    for path in sorted(core.glob("scratch_archive*.py")):
        scan(ast.parse(path.read_text(encoding="utf-8")), "<module>", path.name)
    return found


def test_ctypes_moves_are_only_the_listed_ones() -> None:
    """The Task 3.9 review list of no-replace renames: a move out of scratch is a removal."""
    assert _ctypes_moves() == {
        ("scratch_archive_claim.py", "<module>", "_RENAMEAT2"),
        ("scratch_archive_claim.py", "rename_noreplace", "_RENAMEAT2"),
        ("scratch_archive_claim.py", "rename_noreplace_between", "_RENAMEAT2"),
        ("scratch_archive_adopt.py", "_move_in", "rename_noreplace_between"),
        ("scratch_archive_adopt.py", "_move_back", "rename_noreplace_between"),
        ("scratch_archive_claim.py", "claim", "rename_noreplace"),
        ("scratch_archive_claim.py", "release", "rename_noreplace"),
        ("scratch_archive_remove.py", "resume_claimed", "rename_noreplace"),
        ("scratch_archive_restore.py", "_move", "rename_noreplace_between"),
    }


def test_deletion_surfaces_are_only_the_listed_ones() -> None:
    """The Task 3.9 review list: every place the archive modules can delete or truncate."""
    assert _deletion_surfaces() == {
        ("scratch_archive.py", "_append_line", "ftruncate"),
        ("scratch_archive.py", "discard_unrecorded", "unlink"),
        ("scratch_archive_expire.py", "_unlink_expired", "unlink"),
        ("scratch_archive_remove.py", "_delete", "unlink"),
        ("scratch_archive_remove.py", "_delete", "rmdir"),
        ("scratch_archive_restore.py", "_clean_staging", "rmdir"),
        ("scratch_archive_restore.py", "_empty_dir", "unlink"),
        ("scratch_archive_restore.py", "_empty_dir", "rmdir"),
    }
