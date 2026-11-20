"""Restore an archived entry beside its original path (Plan 00627 Task 3.6).

Restore never overwrites: the final step is a no-replace rename from a staging
directory in the store. Every check (lock, a complete record, the archive's
SHA-256 read through the descriptor later fed to tar, every header, the layout
against the record, the destination absent, one device) runs BEFORE staging
is created, so a refused restore leaves no trace.
"""

from __future__ import annotations

import errno
import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import scratch_archive_restore as restore_mod
from claude_code_hooks_daemon.core.scratch_archive import (
    ArchiveRecord,
    ArchiveStore,
    ExpiredEvent,
    archive_file_name,
    new_archive_id,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    CLAIM_PREFIX,
    Claimed,
    claim,
    fingerprint_at,
    open_dir,
    rename_noreplace_between,
    walk_tree,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    TarTool,
    find_gnu_tar,
    members_of,
    pack,
)
from claude_code_hooks_daemon.core.scratch_archive_restore import (
    STAGING_PREFIX,
    Restored,
    RestoreRefused,
    leftover_staging,
    restore,
)

_ABSOLUTE = "/".join(("", "etc", "x"))
_PARENT = "/".join(("..", "x"))
_INNER_PARENT = "/".join((".", "a", "..", "..", "x"))
_OUTSIDE = "/".join(("", "var"))


class Crash(BaseException):
    """A simulated process death: no ``except Exception`` cleanup runs."""


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


def _record(
    archive_id: str,
    *,
    path: str,
    counts: dict[str, int],
    size: int,
    sha: str,
    skipped: tuple[str, ...] = (),
) -> ArchiveRecord:
    return ArchiveRecord(
        archive_id=archive_id,
        original_path=path,
        checkout="main",
        verdict="DISPOSABLE",
        proof_ids=("P1",),
        packed_at="2026-11-20T00:00:00+00:00",
        expires_at="2026-11-20T12:00:00+00:00",
        counts=counts,
        archive_size=size,
        sha256=sha,
        skipped=skipped,
        restore_command="x",
    )


def _pack_entry(root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, name: str) -> str:
    """Claim, pack and record ``name``, then delete the claimed original (test-side)."""
    expected = fingerprint_at(root_fd, name, max_inodes=1000)
    handle = claim(root_fd, name, expected, max_inodes=1000)
    assert isinstance(handle, Claimed)
    archive_id = new_archive_id()
    result = pack(handle, store, archive_id, tar=tar, max_inodes=1000)
    store.append(
        _record(
            archive_id,
            path=f"untracked/scratch/{name}",
            counts=result.counts,
            size=result.size,
            sha=result.sha256,
            skipped=result.skipped,
        )
    )
    claimed = root / f"{CLAIM_PREFIX}{name}"
    if claimed.is_dir() and not claimed.is_symlink():
        for path in [claimed, *claimed.rglob("*")]:
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755)
        shutil.rmtree(claimed)
    else:
        claimed.unlink()
    handle.close()
    return archive_id


def _member(name: str, kind: bytes = tarfile.REGTYPE, data: bytes = b"", link: str = "") -> Any:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
    info.linkname = link
    info.size = len(data) if kind in (tarfile.REGTYPE, tarfile.AREGTYPE) else 0
    return info, (io.BytesIO(data) if info.size else None)


def _install(
    store: ArchiveStore,
    members: list[Any],
    *,
    path: str,
    counts: dict[str, int],
    extra_records: tuple[str, ...] = (),
) -> str:
    """Write a hand-built GNU tar into the store with a truthful record."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for info, data in members:
            archive.addfile(info, data)
    payload = buffer.getvalue()
    archive_id = new_archive_id()
    fd = store.create_archive(archive_id)
    os.write(fd, payload)
    os.close(fd)
    sha = hashlib.sha256(payload).hexdigest()
    for one in (path, *extra_records):
        store.append(_record(archive_id, path=one, counts=counts, size=len(payload), sha=sha))
    return archive_id


def _staging(store: ArchiveStore) -> list[str]:
    return sorted(p.name for p in store.path.iterdir() if p.name.startswith(STAGING_PREFIX))


def _names(path: Path) -> list[str]:
    return sorted(p.name for p in path.iterdir())


def _restore(
    store: ArchiveStore, root_fd: int, tar: TarTool, archive_id: str, entry: str | None = None
) -> Restored:
    return restore(store, archive_id, root_fd, entry=entry, tar=tar, max_inodes=1000)


def _tree(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        rel = str(item.relative_to(path))
        if item.is_symlink():
            found[rel] = "-> " + str(item.readlink())
        elif item.is_dir():
            found[rel] = "dir"
        else:
            found[rel] = item.read_text()
    return found


def _make_entry(root: Path, name: str = "e1") -> dict[str, str]:
    entry = root / name
    (entry / "sub").mkdir(parents=True)
    (entry / "a.txt").write_text("alpha")
    (entry / "sub" / "b.txt").write_text("beta")
    (entry / "rel-link").symlink_to("a.txt")
    return _tree(entry)


# --- the between-directories no-replace rename ----------------------------------


class TestRenameBetween:
    def test_moves_between_directories(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "f").write_text("x")
        a_fd, b_fd = open_dir(tmp_path / "a"), open_dir(tmp_path / "b")
        try:
            rename_noreplace_between(a_fd, "f", b_fd, "g")
        finally:
            os.close(a_fd)
            os.close(b_fd)
        assert (tmp_path / "b" / "g").read_text() == "x"
        assert not (tmp_path / "a" / "f").exists()

    @pytest.mark.parametrize("existing", ["file", "dangling-link"])
    def test_never_replaces(self, tmp_path: Path, existing: str) -> None:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "f").write_text("new")
        if existing == "file":
            (tmp_path / "b" / "g").write_text("old")
        else:
            (tmp_path / "b" / "g").symlink_to("nowhere")
        a_fd, b_fd = open_dir(tmp_path / "a"), open_dir(tmp_path / "b")
        try:
            with pytest.raises(OSError) as caught:
                rename_noreplace_between(a_fd, "f", b_fd, "g")
        finally:
            os.close(a_fd)
            os.close(b_fd)
        assert caught.value.errno == errno.EEXIST
        assert (tmp_path / "a" / "f").read_text() == "new"
        assert (tmp_path / "b" / "g").is_symlink() == (existing != "file")

    @pytest.mark.parametrize("bad", ["", ".", "..", "x/y"])
    def test_refuses_a_name_that_is_not_plain(self, tmp_path: Path, bad: str) -> None:
        fd = open_dir(tmp_path)
        try:
            with pytest.raises(ValueError):
                rename_noreplace_between(fd, bad, fd, "ok")
            with pytest.raises(ValueError):
                rename_noreplace_between(fd, "ok", fd, bad)
        finally:
            os.close(fd)


# --- round trips ------------------------------------------------------------------


class TestRoundTrip:
    def test_a_directory_entry_comes_back_whole(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        before = _make_entry(root)
        archive_id = _pack_entry(root, root_fd, store, tar, "e1")
        assert not (root / "e1").exists()
        result = _restore(store, root_fd, tar, archive_id)
        assert result.name == "e1"
        assert _tree(root / "e1") == before
        assert _staging(store) == []
        assert (store.path / archive_file_name(archive_id)).is_file()
        assert len(store.read_index().records) == 1

    def test_a_read_only_directory_entry_comes_back_with_its_mode(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _make_entry(root)
        (root / "e1" / "sub").chmod(0o500)
        (root / "e1").chmod(0o550)
        archive_id = _pack_entry(root, root_fd, store, tar, "e1")
        _restore(store, root_fd, tar, archive_id)
        assert (root / "e1").stat().st_mode & 0o777 == 0o550
        assert (root / "e1" / "sub").stat().st_mode & 0o777 == 0o500
        (root / "e1").chmod(0o755)
        (root / "e1" / "sub").chmod(0o755)

    def test_a_loose_file_entry_comes_back(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        (root / "notes.md").write_text("the notes")
        archive_id = _pack_entry(root, root_fd, store, tar, "notes.md")
        _restore(store, root_fd, tar, archive_id)
        assert (root / "notes.md").read_text() == "the notes"
        assert _staging(store) == []

    def test_a_hostile_name_round_trips(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        name = "-rf --to-command=x \n 'q\"\\"
        (root / name).mkdir()
        (root / name / "--checkpoint-action=exec=x").write_text("payload")
        archive_id = _pack_entry(root, root_fd, store, tar, name)
        _restore(store, root_fd, tar, archive_id)
        assert (root / name / "--checkpoint-action=exec=x").read_text() == "payload"

    def test_a_hostile_loose_file_name_is_never_a_tar_option_or_pattern(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        glob = "".join(chr(c) for c in (42, 63, 91, 97, 93))
        name = f"--to-command=x \n'q\"\\{glob}"
        (root / name).write_text("payload")
        archive_id = _pack_entry(root, root_fd, store, tar, name)
        _restore(store, root_fd, tar, archive_id)
        assert (root / name).read_text() == "payload"
        assert _staging(store) == []

    def test_one_entry_of_a_batch_comes_back(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        members = [
            _member(f"./{CLAIM_PREFIX}a", data=b"one"),
            _member(f"./{CLAIM_PREFIX}b", data=b"two"),
            _member(f"./{CLAIM_PREFIX}c", tarfile.SYMTYPE, link="a"),
        ]
        archive_id = _install(
            store,
            members,
            path="untracked/scratch/b",
            counts={"file": 1},
            extra_records=("untracked/scratch/a",),
        )
        result = _restore(store, root_fd, tar, archive_id, entry="untracked/scratch/b")
        assert result.name == "b"
        assert _names(root) == ["b"]
        assert (root / "b").read_text() == "two"
        assert _staging(store) == []


# --- the P6 ``name/...`` layout (Task 3.7) ------------------------------------------

_P6_FLAGS = {"none": "-cf", "gzip": "-czf", "xz": "-cJf"}


def _install_p6(
    root: Path,
    store: ArchiveStore,
    tar: TarTool,
    name: str,
    compression: str = "gzip",
    *,
    record_name: str | None = None,
) -> str:
    """Pack ``root/name`` by hand as ``name/...`` (the P6 layout), store it, then remove it."""
    if compression == "xz" and shutil.which("xz", path="/usr/bin:/bin") is None:
        pytest.skip("xz is not installed")
    proc = subprocess.run(
        [tar.path, "--format=gnu", _P6_FLAGS[compression], "-", "--", name],
        cwd=root,
        capture_output=True,
        check=True,
    )
    payload = proc.stdout
    root_fd = open_dir(root)
    try:
        counts = members_of(walk_tree(root_fd, name, max_inodes=1000), name).counts
    finally:
        os.close(root_fd)
    archive_id = new_archive_id()
    fd = store.create_archive(archive_id)
    os.write(fd, payload)
    os.close(fd)
    store.append(
        _record(
            archive_id,
            path=f"untracked/scratch/{record_name or name}",
            counts=counts,
            size=len(payload),
            sha=hashlib.sha256(payload).hexdigest(),
        )
    )
    for path in [root / name, *(root / name).rglob("*")]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
    shutil.rmtree(root / name)
    return archive_id


class TestAdoptedLayout:
    @pytest.mark.parametrize("compression", ["gzip", "none", "xz"])
    def test_a_hand_packed_archive_comes_back_whole(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, compression: str
    ) -> None:
        before = _make_entry(root)
        archive_id = _install_p6(root, store, tar, "e1", compression)
        result = _restore(store, root_fd, tar, archive_id)
        assert (result.name, result.layout) == ("e1", "adopted")
        assert _tree(root / "e1") == before
        assert _names(root) == ["e1"]
        assert _staging(store) == []

    def test_a_read_only_root_comes_back_with_its_mode(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _make_entry(root)
        (root / "e1" / "sub").chmod(0o500)
        (root / "e1").chmod(0o550)
        archive_id = _install_p6(root, store, tar, "e1")
        _restore(store, root_fd, tar, archive_id)
        assert (root / "e1").stat().st_mode & 0o777 == 0o550
        assert (root / "e1" / "sub").stat().st_mode & 0o777 == 0o500
        (root / "e1").chmod(0o755)
        (root / "e1" / "sub").chmod(0o755)

    def test_a_hostile_name_round_trips(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        name = "-rf --to-command=x \n 'q\"\\"
        (root / name).mkdir()
        (root / name / "--checkpoint-action=exec=x").write_text("payload")
        archive_id = _install_p6(root, store, tar, name)
        _restore(store, root_fd, tar, archive_id)
        assert (root / name / "--checkpoint-action=exec=x").read_text() == "payload"

    def test_a_root_named_other_than_the_record_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _make_entry(root)
        archive_id = _install_p6(root, store, tar, "e1", record_name="e2")
        _refused_cleanly(store, root, root_fd, tar, archive_id, "layout")

    def test_an_unknown_archive_format_is_refused_before_staging(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        payload = b"BZh91AY&SY" + b"\0" * 2000
        archive_id = new_archive_id()
        fd = store.create_archive(archive_id)
        os.write(fd, payload)
        os.close(fd)
        sha = hashlib.sha256(payload).hexdigest()
        store.append(
            _record(
                archive_id,
                path="untracked/scratch/e1",
                counts={"dir": 1},
                size=len(payload),
                sha=sha,
            )
        )
        _refused_cleanly(store, root, root_fd, tar, archive_id, "format")


# --- refusals before staging ------------------------------------------------------


def _refused_cleanly(
    store: ArchiveStore,
    root: Path,
    root_fd: int,
    tar: TarTool,
    archive_id: str,
    match: str,
    entry: str | None = None,
) -> None:
    before = _names(root)
    with pytest.raises(RestoreRefused, match=match):
        _restore(store, root_fd, tar, archive_id, entry=entry)
    assert _staging(store) == []
    assert _names(root) == before


class TestRefusals:
    def test_needs_the_lock(self, tmp_path: Path, root_fd: int, tar: TarTool) -> None:
        with ArchiveStore.open(tmp_path / "other-store") as unlocked:
            with pytest.raises(Exception, match="lock"):
                _restore(unlocked, root_fd, tar, new_archive_id())

    def test_an_unknown_or_expired_id(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _refused_cleanly(store, root, root_fd, tar, new_archive_id(), "no record")
        (root / "f").write_text("x")
        archive_id = _pack_entry(root, root_fd, store, tar, "f")
        store.append_event(ExpiredEvent(archive_id=archive_id, at="2026-11-21T00:00:00+00:00"))
        _refused_cleanly(store, root, root_fd, tar, archive_id, "expired")

    @pytest.mark.parametrize("existing", ["file", "dir", "dangling-link"])
    def test_an_existing_destination_is_never_touched(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, existing: str
    ) -> None:
        _make_entry(root)
        archive_id = _pack_entry(root, root_fd, store, tar, "e1")
        if existing == "file":
            (root / "e1").write_text("newer work")
        elif existing == "dir":
            (root / "e1").mkdir()
            (root / "e1" / "keep").write_text("newer")
        else:
            (root / "e1").symlink_to("nowhere")
        _refused_cleanly(store, root, root_fd, tar, archive_id, "exists")
        if existing == "file":
            assert (root / "e1").read_text() == "newer work"
        elif existing == "dir":
            assert _names(root / "e1") == ["keep"]
        else:
            assert (root / "e1").is_symlink()

    def test_a_changed_archive_is_refused_by_its_hash(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _make_entry(root)
        archive_id = _pack_entry(root, root_fd, store, tar, "e1")
        path = store.path / archive_file_name(archive_id)
        data = bytearray(path.read_bytes())
        data[600] ^= 0xFF
        path.write_bytes(bytes(data))
        _refused_cleanly(store, root, root_fd, tar, archive_id, "SHA-256")

    def test_a_batch_needs_its_entry(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        members = [_member(f"./{CLAIM_PREFIX}a", data=b"1"), _member(f"./{CLAIM_PREFIX}b")]
        archive_id = _install(
            store,
            members,
            path="untracked/scratch/a",
            counts={"file": 1},
            extra_records=("untracked/scratch/b",),
        )
        _refused_cleanly(store, root, root_fd, tar, archive_id, "entry")
        _refused_cleanly(store, root, root_fd, tar, archive_id, "entry", "untracked/scratch/z")

    @pytest.mark.parametrize("path", ["untracked/scratch/..", "untracked/", "x/.", "/"])
    def test_a_hostile_original_path_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, path: str
    ) -> None:
        archive_id = _install(store, [_member("./", tarfile.DIRTYPE)], path=path, counts={"dir": 1})
        _refused_cleanly(store, root, root_fd, tar, archive_id, "name")

    @pytest.mark.parametrize(
        "members",
        [
            [_member("./", tarfile.DIRTYPE), _member(_PARENT, data=b"x")],
            [_member("./", tarfile.DIRTYPE), _member(_INNER_PARENT, data=b"x")],
            [_member("./", tarfile.DIRTYPE), _member(_ABSOLUTE, data=b"x")],
            [_member("./", tarfile.DIRTYPE), _member("a", data=b"x")],
            [_member("./", tarfile.DIRTYPE), _member("./a//b", data=b"x")],
            [_member("./", tarfile.DIRTYPE), _member("./a/./b", data=b"x")],
            [
                _member("./", tarfile.DIRTYPE),
                _member("./lnk", tarfile.SYMTYPE, link=_OUTSIDE),
                _member("./lnk/x", data=b"x"),
            ],
            [
                _member("./", tarfile.DIRTYPE),
                _member("./a", data=b"x"),
                _member("./a", data=b"y"),
            ],
            [
                _member("./", tarfile.DIRTYPE),
                _member("./a", data=b"x"),
                _member("./h", tarfile.LNKTYPE, link="./a"),
            ],
            [_member("./", tarfile.DIRTYPE), _member("./dev", tarfile.CHRTYPE)],
            [_member("./", tarfile.DIRTYPE), _member("./fifo", tarfile.FIFOTYPE)],
        ],
        ids=[
            "parent",
            "inner-parent",
            "absolute",
            "no-dot-prefix",
            "empty-component",
            "dot-component",
            "beneath-a-link",
            "duplicate",
            "hard-link",
            "device",
            "fifo",
        ],
    )
    def test_an_unsafe_member_is_refused_before_staging(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        members: list[Any],
    ) -> None:
        archive_id = _install(
            store, members, path="untracked/scratch/e1", counts={"dir": 1, "file": 1}
        )
        _refused_cleanly(store, root, root_fd, tar, archive_id, "member")

    @pytest.mark.parametrize(
        ("members", "counts"),
        [
            ([_member("./", tarfile.DIRTYPE), _member("./a", data=b"x")], {"dir": 2}),
            ([_member("./", tarfile.DIRTYPE)], {"dir": 1, "fifo": 1}),
            ([_member(f"./{CLAIM_PREFIX}e1", data=b"x")], {"symlink": 1}),
            ([_member(f"./{CLAIM_PREFIX}other", data=b"x")], {"file": 1}),
            ([_member("./a", data=b"x")], {"file": 1}),
            (
                [_member("other/", tarfile.DIRTYPE), _member("other/a", data=b"x")],
                {"dir": 1, "file": 1},
            ),
            ([_member("e1/", tarfile.DIRTYPE), _member("e1/a", data=b"x")], {"dir": 2}),
            ([_member("e1/a", data=b"x")], {"file": 1}),
            ([_member("e1", data=b"x")], {"file": 1}),
            (
                [_member("e1/", tarfile.DIRTYPE), _member("./a", data=b"x")],
                {"dir": 1, "file": 1},
            ),
            (
                [_member("./", tarfile.DIRTYPE), _member("e1/a", data=b"x")],
                {"dir": 1, "file": 1},
            ),
            (
                [
                    _member(f"./{CLAIM_PREFIX}e1", data=b"x"),
                    _member(f"x/{CLAIM_PREFIX}y", data=b"y"),
                ],
                {"file": 1},
            ),
        ],
        ids=[
            "counts-differ",
            "skips-differ",
            "kind-differs",
            "wrong-member",
            "unclaimed-name",
            "p6-other-root",
            "p6-counts-differ",
            "p6-no-root-member",
            "p6-root-not-a-dir",
            "p6-mixed-with-dot",
            "dot-mixed-with-p6",
            "member-mixed-with-p6",
        ],
    )
    def test_a_layout_that_disagrees_with_the_record_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        members: list[Any],
        counts: dict[str, int],
    ) -> None:
        archive_id = _install(store, members, path="untracked/scratch/e1", counts=counts)
        _refused_cleanly(store, root, root_fd, tar, archive_id, "layout|member")

    def test_another_device_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (root / "f").write_text("x")
        archive_id = _pack_entry(root, root_fd, store, tar, "f")
        real = os.fstat

        def other_device(fd: int) -> Any:
            info = real(fd)
            if fd == root_fd:
                return os.stat_result((*info[:2], info.st_dev + 1, *info[3:]))
            return info

        monkeypatch.setattr(restore_mod.os, "fstat", other_device)
        _refused_cleanly(store, root, root_fd, tar, archive_id, "device")


# --- failures and crashes after staging -------------------------------------------


def _after_extract(monkeypatch: pytest.MonkeyPatch, after: Callable[[], None]) -> None:
    real = restore_mod.run_tar

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        if "--extract" in args[1]:
            after()
        return result

    monkeypatch.setattr(restore_mod, "run_tar", wrapped)


class TestAfterStaging:
    def test_a_destination_that_appears_during_extraction_wins(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make_entry(root)
        archive_id = _pack_entry(root, root_fd, store, tar, "e1")

        def appear() -> None:
            (root / "e1").write_text("written meanwhile")

        _after_extract(monkeypatch, appear)
        with pytest.raises(RestoreRefused, match="exists"):
            _restore(store, root_fd, tar, archive_id)
        assert (root / "e1").read_text() == "written meanwhile"
        assert _staging(store) == []

    def test_a_failing_extraction_cleans_its_staging(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make_entry(root)
        archive_id = _pack_entry(root, root_fd, store, tar, "e1")
        real = restore_mod.run_tar

        def failing(*args: Any, **kwargs: Any) -> Any:
            result = real(*args, **kwargs)
            if "--extract" in args[1]:
                result.returncode = 2
            return result

        monkeypatch.setattr(restore_mod, "run_tar", failing)
        with pytest.raises(RestoreRefused, match="extract"):
            _restore(store, root_fd, tar, archive_id)
        assert _staging(store) == []
        assert not (root / "e1").exists()

    def test_a_tampered_staging_tree_fails_verification_and_is_cleaned(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make_entry(root)
        archive_id = _pack_entry(root, root_fd, store, tar, "e1")

        def tamper() -> None:
            (staged,) = _staging(store)
            (store.path / staged / "root" / "sub" / "b.txt").write_text("changed")
            (store.path / staged / "root" / "sub").chmod(0o500)

        _after_extract(monkeypatch, tamper)
        with pytest.raises(RestoreRefused, match="verif"):
            _restore(store, root_fd, tar, archive_id)
        assert _staging(store) == []
        assert not (root / "e1").exists()

    @pytest.mark.parametrize("step", ["extract", "verify", "move", "clean"])
    def test_a_crash_after_each_step_loses_nothing(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
        step: str,
    ) -> None:
        before = _make_entry(root)
        archive_id = _pack_entry(root, root_fd, store, tar, "e1")

        def crash(*_args: Any, **_kwargs: Any) -> Any:
            raise Crash

        if step == "extract":
            _after_extract(monkeypatch, crash)
        elif step == "verify":
            monkeypatch.setattr(restore_mod, "batched_compare", crash)
        elif step == "move":
            monkeypatch.setattr(restore_mod, "rename_noreplace_between", crash)
        else:
            monkeypatch.setattr(restore_mod, "_clean_staging", crash)
        with pytest.raises(Crash):
            _restore(store, root_fd, tar, archive_id)
        monkeypatch.undo()
        leftovers = leftover_staging(store)
        assert len(leftovers) == 1
        data = (store.path / archive_file_name(archive_id)).read_bytes()
        assert hashlib.sha256(data).hexdigest() == store.read_index().records[0].sha256
        if step == "clean":
            assert _tree(root / "e1") == before
            with pytest.raises(RestoreRefused, match="exists"):
                _restore(store, root_fd, tar, archive_id)
        else:
            assert not (root / "e1").exists()
            _restore(store, root_fd, tar, archive_id)
            assert _tree(root / "e1") == before
        # A leftover is reported, never deleted by a later run.
        assert leftover_staging(store) == leftovers
