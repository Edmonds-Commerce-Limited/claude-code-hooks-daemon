"""Proof P6: adopt a tarball that sits beside its original (Plan 00627 Task 3.7)."""

from __future__ import annotations

import gzip
import hashlib
import io
import lzma
import os
import shutil
import subprocess
import tarfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import scratch_archive_adopt as adopt_mod
from claude_code_hooks_daemon.core import scratch_archive_pack as pack_mod
from claude_code_hooks_daemon.core.scratch_archive import (
    ARCHIVE_SUFFIX,
    EVENTS_NAME,
    AdoptEvent,
    ArchiveStore,
    ExpiredEvent,
    StoreRefused,
    archive_file_name,
)
from claude_code_hooks_daemon.core.scratch_archive_adopt import (
    Adopted,
    AdoptRefused,
    AdoptStuck,
    adopt,
    finish_adoption,
    unfinished_adoptions,
)
from claude_code_hooks_daemon.core.scratch_archive_claim import open_dir
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    Compression,
    PackRefused,
    TarTool,
    compression_flags,
    compression_of,
    find_gnu_tar,
    require_decompressor,
    tarfile_mode,
)
from claude_code_hooks_daemon.core.scratch_archive_restore import restore

TAR = shutil.which("tar")
_ENV = {"LC_ALL": "C", "PATH": "/usr/bin:/bin"}


def _tar(
    args: list[str], cwd: Path, stdin: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    assert TAR is not None
    if stdin is None:
        return subprocess.run([TAR, *args], cwd=cwd, env=_ENV, capture_output=True, check=False)
    with stdin.open("rb") as handle:
        return subprocess.run(
            [TAR, *args], cwd=cwd, env=_ENV, stdin=handle, capture_output=True, check=False
        )


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    """A source tree ``src/e`` packed as ``e.tgz``, and a copy ``t`` of ``e``."""
    src = tmp_path / "src"
    (src / "e" / "sub").mkdir(parents=True)
    (src / "e" / "a").write_bytes(b"a\n")
    (src / "e" / "sub" / "b").write_bytes(b"b\n")
    assert _tar(["--format=gnu", "-czf", "../e.tgz", "e"], src).returncode == 0
    copy = tmp_path / "t"
    shutil.copytree(src / "e", copy, symlinks=True)
    for rel in ("a", "sub/b", "sub", "."):
        info = os.lstat(src / "e" / rel)
        os.utime(copy / rel, ns=(info.st_atime_ns, info.st_mtime_ns))
    return tmp_path / "e.tgz", copy


_OPERANDS = ("e/a", "e/sub", "e/sub/b")


def _compare(
    archive: Path, tree: Path, operands: tuple[str, ...] = _OPERANDS
) -> subprocess.CompletedProcess[bytes]:
    """The adopt module's compare: every member but the root, named, without recursion."""
    return _tar(
        [
            "--compare",
            "--gzip",
            "--file=-",
            "--strip-components=1",
            "--format=gnu",
            "--no-recursion",
            "--no-wildcards",
            "--no-unquote",
            "--",
            *operands,
        ],
        tree,
        stdin=archive,
    )


def test_probe_compare_with_strip_components_fails_on_the_stripped_root_member(
    pair: tuple[Path, Path],
) -> None:
    """The root member strips to an empty name tar cannot stat, so it is never an operand."""
    archive, tree = pair
    proc = _tar(
        ["--compare", "--gzip", "--file=-", "--strip-components=1", "--format=gnu"],
        tree,
        stdin=archive,
    )
    assert proc.returncode != 0
    assert b"Cannot stat" in proc.stderr


def test_probe_compare_with_strip_components_is_clean_on_an_equal_tree(
    pair: tuple[Path, Path],
) -> None:
    proc = _compare(*pair)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")


def test_probe_compare_with_strip_components_sees_a_changed_file(
    pair: tuple[Path, Path],
) -> None:
    archive, tree = pair
    (tree / "a").write_bytes(b"X\n")
    assert _compare(archive, tree).returncode != 0


def test_probe_compare_with_strip_components_sees_a_missing_file(
    pair: tuple[Path, Path],
) -> None:
    archive, tree = pair
    (tree / "sub" / "b").unlink()
    assert _compare(archive, tree).returncode != 0


def test_probe_compare_is_silent_about_a_tree_file_the_archive_lacks(
    pair: tuple[Path, Path],
) -> None:
    """Why the member set must equal the walk: --compare alone never sees an extra file."""
    archive, tree = pair
    (tree / "extra").write_bytes(b"z\n")
    proc = _compare(archive, tree)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")


def test_probe_compare_fails_on_a_member_with_too_few_components(tmp_path: Path) -> None:
    """A top-level file strips to an empty name; tar fails rather than skipping it."""
    src = tmp_path / "src"
    (src / "e").mkdir(parents=True)
    (src / "e" / "a").write_bytes(b"a\n")
    (src / "top").write_bytes(b"not in the tree\n")
    assert _tar(["--format=gnu", "-czf", "../top.tgz", "e/a", "top"], src).returncode == 0
    tree = tmp_path / "t"
    tree.mkdir()
    shutil.copy2(src / "e" / "a", tree / "a")
    proc = _compare(tmp_path / "top.tgz", tree, ("e/a", "top"))
    assert proc.returncode != 0
    assert b"Cannot stat" in proc.stderr


def test_probe_compare_without_a_compression_flag_refuses_a_gzip_stream(
    pair: tuple[Path, Path],
) -> None:
    archive, tree = pair
    proc = _tar(["--compare", "--file=-", "--strip-components=1"], tree, stdin=archive)
    assert proc.returncode != 0


# --- the shared compression sniff -------------------------------------------------


def _fd_of(path: Path) -> int:
    return os.open(path, os.O_RDONLY)


def _plain_tar_bytes(fmt: int = tarfile.GNU_FORMAT) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=fmt) as archive:
        info = tarfile.TarInfo("./a")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        (gzip.compress(b"anything"), "gzip"),
        (lzma.compress(b"anything", format=lzma.FORMAT_XZ), "xz"),
        (_plain_tar_bytes(), "none"),
        (_plain_tar_bytes(tarfile.PAX_FORMAT), "none"),
    ],
    ids=["gzip", "xz", "gnu-tar", "pax-tar"],
)
def test_compression_is_chosen_from_the_first_bytes(
    tmp_path: Path, payload: bytes, kind: str
) -> None:
    path = tmp_path / "x"
    path.write_bytes(payload)
    fd = _fd_of(path)
    try:
        assert compression_of(fd) == kind
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x1f", b"BZh91AY&SY" + b"\0" * 600, b"\0" * 1024, b"not an archive at all"],
    ids=["empty", "short-gzip", "bzip2", "zeros", "text"],
)
def test_an_unknown_or_short_format_is_refused(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "x"
    path.write_bytes(payload)
    fd = _fd_of(path)
    try:
        with pytest.raises(PackRefused, match="format"):
            compression_of(fd)
    finally:
        os.close(fd)


def test_the_sniff_reads_from_the_start_whatever_the_offset(tmp_path: Path) -> None:
    path = tmp_path / "x"
    path.write_bytes(gzip.compress(b"z" * 4096))
    fd = _fd_of(path)
    try:
        os.lseek(fd, 100, os.SEEK_SET)
        assert compression_of(fd) == "gzip"
    finally:
        os.close(fd)


def test_the_tar_flag_and_stream_mode_are_explicit() -> None:
    assert compression_flags("gzip") == ("--gzip",)
    assert compression_flags("xz") == ("--xz",)
    assert compression_flags("none") == ()
    assert {tarfile_mode(k) for k in ("gzip", "xz", "none")} == {"r|gz", "r|xz", "r|"}


@pytest.mark.parametrize("kind", ["gzip", "xz"])
def test_a_missing_decompressor_is_a_refusal(
    kind: Compression, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pack_mod.shutil, "which", lambda *_a, **_k: None)
    with pytest.raises(PackRefused, match="decompressor"):
        require_decompressor(kind)


def test_a_plain_tar_needs_no_decompressor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pack_mod.shutil, "which", lambda *_a, **_k: None)
    require_decompressor("none")


# --- adopt ------------------------------------------------------------------------

_NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
_FLAGS = {"gzip": "-czf", "none": "-cf", "xz": "-cJf"}


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
def gnu_tar() -> TarTool:
    return find_gnu_tar()


def _make(root: Path, name: str = "e1") -> dict[str, str]:
    entry = root / name
    (entry / "sub").mkdir(parents=True)
    (entry / "a.txt").write_text("alpha")
    (entry / "sub" / "b.txt").write_text("beta")
    (entry / "rel-link").symlink_to("a.txt")
    return _tree(entry)


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


def _pack_by_hand(
    root: Path, name: str = "e1", compression: str = "gzip", tarball: str = "e1.tgz"
) -> Path:
    if compression == "xz" and shutil.which("xz", path="/usr/bin:/bin") is None:
        pytest.skip("xz is not installed")
    assert TAR is not None
    proc = subprocess.run(
        [TAR, "--format=gnu", _FLAGS[compression], tarball, "--", name],
        cwd=root,
        env=_ENV,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return root / tarball


def _adopt(
    store: ArchiveStore,
    root_fd: int,
    gnu_tar: TarTool,
    tarball: str = "e1.tgz",
    name: str = "e1",
    original: str | None = None,
) -> Adopted:
    return adopt(
        store,
        root_fd,
        name,
        tarball,
        original_path=original or f"untracked/scratch/{name}",
        checkout="main",
        verdict="DISPOSABLE",
        proof_ids=("P6",),
        expires_at="2026-11-21T00:00:00+00:00",
        restore_command="hooks-daemon scratch-restore",
        now=_NOW,
        tar=gnu_tar,
        max_inodes=1000,
    )


def _remove_tree(path: Path) -> None:
    for item in [path, *path.rglob("*")]:
        if item.is_dir() and not item.is_symlink():
            item.chmod(0o755)
    shutil.rmtree(path)


def _store_files(store: ArchiveStore) -> list[str]:
    return sorted(p.name for p in store.path.iterdir() if p.name.endswith(ARCHIVE_SUFFIX))


class TestAdopt:
    @pytest.mark.parametrize("compression", ["gzip", "none", "xz"])
    def test_an_equal_tarball_is_adopted_and_restores_whole(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool, compression: str
    ) -> None:
        before = _make(root)
        tarball = _pack_by_hand(root, compression=compression)
        data = tarball.read_bytes()
        result = _adopt(store, root_fd, gnu_tar)
        assert not tarball.exists()
        assert (root / "e1").is_dir()
        assert _store_files(store) == [archive_file_name(result.archive_id)]
        (record,) = store.read_index().records
        assert (record.archive_id, record.sha256, record.archive_size) == (
            result.archive_id,
            hashlib.sha256(data).hexdigest(),
            len(data),
        )
        assert dict(record.counts) == {"dir": 2, "file": 2, "symlink": 1}
        assert record.original_path == "untracked/scratch/e1"
        assert store.read_events().events == (
            AdoptEvent(
                archive_id=result.archive_id,
                original_path="untracked/scratch/e1",
                tarball="untracked/scratch/e1.tgz",
                at=_NOW.isoformat(),
            ),
        )
        audit = store.audit()
        assert (audit.unrecorded_archives, audit.records_without_archive) == ((), ())
        _remove_tree(root / "e1")
        restored = restore(
            store,
            result.archive_id,
            root_fd,
            root_path="untracked/scratch",
            tar=gnu_tar,
            max_inodes=1000,
        )
        assert restored.layout == "adopted"
        assert _tree(root / "e1") == before

    def test_an_empty_directory_is_checked_by_member_set_alone(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        (root / "e1").mkdir()
        _pack_by_hand(root)
        result = _adopt(store, root_fd, gnu_tar)
        assert store.read_index().by_id(result.archive_id) is not None

    def test_a_hostile_name_is_adopted(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        name = "-rf --to-command=x \n 'q\"\\"
        (root / name).mkdir()
        (root / name / "--checkpoint-action=exec=x").write_text("payload")
        _pack_by_hand(root, name=name, tarball="-x.tgz")
        _adopt(store, root_fd, gnu_tar, tarball="-x.tgz", name=name)
        assert not (root / "-x.tgz").exists()


def _refused(
    store: ArchiveStore,
    root: Path,
    root_fd: int,
    gnu_tar: TarTool,
    match: str,
    tarball: str = "e1.tgz",
    original: str | None = None,
) -> None:
    before = sorted(p.name for p in root.iterdir())
    with pytest.raises(AdoptRefused, match=match):
        _adopt(store, root_fd, gnu_tar, tarball=tarball, original=original)
    assert sorted(p.name for p in root.iterdir()) == before
    assert _store_files(store) == []
    assert store.read_index().records == ()
    assert store.read_events().events == ()


class TestAdoptRefusals:
    def test_needs_the_lock(self, tmp_path: Path, root: Path, root_fd: int) -> None:
        _make(root)
        _pack_by_hand(root)
        with ArchiveStore.open(tmp_path / "other-store") as unlocked:
            with pytest.raises(StoreRefused, match="lock"):
                _adopt(unlocked, root_fd, find_gnu_tar())

    @pytest.mark.parametrize(
        "change",
        ["changed-file", "missing-file", "extra-file", "extra-dir"],
    )
    def test_a_tarball_that_differs_from_its_original_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool, change: str
    ) -> None:
        _make(root)
        _pack_by_hand(root)
        if change == "changed-file":
            (root / "e1" / "a.txt").write_text("ALPHA")
        elif change == "missing-file":
            (root / "e1" / "sub" / "b.txt").unlink()
        elif change == "extra-file":
            (root / "e1" / "sub" / "new.txt").write_text("new work")
        else:
            (root / "e1" / "new").mkdir()
        _refused(store, root, root_fd, gnu_tar, "differ")

    def test_a_tarball_that_is_a_link_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        _make(root)
        _pack_by_hand(root, tarball="real.tgz")
        (root / "e1.tgz").symlink_to("real.tgz")
        _refused(store, root, root_fd, gnu_tar, "link")

    def test_a_multi_linked_tarball_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        _make(root)
        tarball = _pack_by_hand(root)
        os.link(tarball, root / "other-name.tgz")
        _refused(store, root, root_fd, gnu_tar, "hard link")

    def test_a_special_file_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        _make(root)
        os.mkfifo(root / "e1.tgz")
        _refused(store, root, root_fd, gnu_tar, "regular file")

    @pytest.mark.parametrize("tarball", ["../e1.tgz", "e1/inner.tgz", "", "..", "e1"])
    def test_a_tarball_outside_the_entry_directory_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool, tarball: str
    ) -> None:
        _make(root)
        _pack_by_hand(root, tarball="inner.tgz").replace(root / "e1" / "inner.tgz")
        _refused(store, root, root_fd, gnu_tar, "name|regular file", tarball=tarball)

    def test_a_record_path_naming_another_entry_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        _make(root)
        _pack_by_hand(root)
        _refused(store, root, root_fd, gnu_tar, "name", original="untracked/scratch/e2")

    def test_an_original_holding_a_special_file_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        _make(root)
        _pack_by_hand(root)
        os.mkfifo(root / "e1" / "pipe")
        _refused(store, root, root_fd, gnu_tar, "special")

    @pytest.mark.parametrize(
        "payload",
        [b"BZh91AY&SY" + b"\0" * 600, b"\x1f\x8b" + b"\0" * 600, b"\0" * 2048],
        ids=["bzip2", "corrupt-gzip", "zeros"],
    )
    def test_an_unverifiable_tarball_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool, payload: bytes
    ) -> None:
        _make(root)
        (root / "e1.tgz").write_bytes(payload)
        _refused(store, root, root_fd, gnu_tar, "format|headers|member")

    @pytest.mark.parametrize(
        "names",
        [["e1/a.txt"], ["other/", "other/a.txt"], ["e1/", "e1/a.txt", "e1/a.txt"]],
        ids=["no-root-member", "other-root", "repeated"],
    )
    def test_a_tarball_of_the_wrong_shape_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        names: list[str],
    ) -> None:
        (root / "e1").mkdir()
        (root / "e1" / "a.txt").write_text("x")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as archive:
            for name in names:
                info = tarfile.TarInfo(name)
                if name.endswith("/"):
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                else:
                    info.size = 1
                    archive.addfile(info, io.BytesIO(b"x"))
        (root / "e1.tgz").write_bytes(buffer.getvalue())
        _refused(store, root, root_fd, gnu_tar, "member|differ")

    def test_a_missing_decompressor_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make(root)
        _pack_by_hand(root)
        monkeypatch.setattr(pack_mod.shutil, "which", lambda *_a, **_k: None)
        _refused(store, root, root_fd, gnu_tar, "decompressor")

    def test_another_device_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make(root)
        _pack_by_hand(root)
        real = os.fstat

        def other_device(fd: int) -> Any:
            info = real(fd)
            if fd == store.dir_fd:
                return os.stat_result((*info[:2], info.st_dev + 1, *info[3:]))
            return info

        monkeypatch.setattr(adopt_mod.os, "fstat", other_device)
        _refused(store, root, root_fd, gnu_tar, "device")


class TestAdoptCrashes:
    def test_a_crash_before_the_move_leaves_the_tarball_beside_its_original(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make(root)
        tarball = _pack_by_hand(root)
        data = tarball.read_bytes()

        def crash(*_args: Any, **_kwargs: Any) -> None:
            raise Crash

        monkeypatch.setattr(adopt_mod, "rename_noreplace_between", crash)
        with pytest.raises(Crash):
            _adopt(store, root_fd, gnu_tar)
        assert tarball.read_bytes() == data
        assert _store_files(store) == []
        assert store.read_index().records == ()
        (event,) = store.read_events().events
        assert isinstance(event, AdoptEvent)

    def test_a_crash_after_the_move_leaves_a_named_archive_never_discarded(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make(root)
        data = _pack_by_hand(root).read_bytes()

        def crash(*_args: Any, **_kwargs: Any) -> None:
            raise Crash

        monkeypatch.setattr(store, "append", crash)
        with pytest.raises(Crash):
            _adopt(store, root_fd, gnu_tar)
        monkeypatch.undo()
        (event,) = store.read_events().events
        assert isinstance(event, AdoptEvent)
        assert event.tarball == "untracked/scratch/e1.tgz"
        name = archive_file_name(event.archive_id)
        assert (store.path / name).read_bytes() == data
        assert store.audit().unrecorded_archives == (name,)
        with pytest.raises(StoreRefused, match="adopt"):
            store.discard_unrecorded(event.archive_id)
        assert (store.path / name).read_bytes() == data

    def test_a_tarball_swapped_before_the_move_is_moved_back(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make(root)
        tarball = _pack_by_hand(root)
        real = adopt_mod.rename_noreplace_between
        calls: list[str] = []

        def swap_then_move(src_fd: int, src: str, dst_fd: int, dst: str) -> None:
            if not calls:
                (root / "swap").write_bytes(b"someone else's file")
                (root / "swap").replace(tarball)
            calls.append(src)
            real(src_fd, src, dst_fd, dst)

        monkeypatch.setattr(adopt_mod, "rename_noreplace_between", swap_then_move)
        with pytest.raises(AdoptRefused, match="moved back"):
            _adopt(store, root_fd, gnu_tar)
        assert len(calls) == 2
        assert tarball.read_bytes() == b"someone else's file"
        assert _store_files(store) == []
        assert store.read_index().records == ()

    def test_a_swapped_file_whose_old_name_is_retaken_stays_named_in_the_store(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make(root)
        tarball = _pack_by_hand(root)
        real = adopt_mod.rename_noreplace_between
        calls: list[str] = []

        def swap_then_move(src_fd: int, src: str, dst_fd: int, dst: str) -> None:
            if not calls:
                (root / "swap").write_bytes(b"someone else's file")
                (root / "swap").replace(tarball)
            calls.append(src)
            real(src_fd, src, dst_fd, dst)
            if len(calls) == 1:
                tarball.write_bytes(b"a newer file under the old name")

        monkeypatch.setattr(adopt_mod, "rename_noreplace_between", swap_then_move)
        with pytest.raises(AdoptStuck, match="adopt event"):
            _adopt(store, root_fd, gnu_tar)
        monkeypatch.undo()
        assert tarball.read_bytes() == b"a newer file under the old name"
        (event,) = store.read_events().events
        assert isinstance(event, AdoptEvent)
        name = archive_file_name(event.archive_id)
        assert (store.path / name).read_bytes() == b"someone else's file"
        assert store.read_index().records == ()
        with pytest.raises(StoreRefused, match="adopt"):
            store.discard_unrecorded(event.archive_id)


# --- finishing an adoption a crash left without a record (Task 3.8 precondition) --


def _crash_before_record(
    root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool, monkeypatch: pytest.MonkeyPatch
) -> AdoptEvent:
    """Adopt ``e1`` and crash at the index append; return the adopt event."""
    _make(root)
    _pack_by_hand(root)

    def crash(*_args: Any, **_kwargs: Any) -> None:
        raise Crash

    monkeypatch.setattr(store, "append", crash)
    with pytest.raises(Crash):
        _adopt(store, root_fd, gnu_tar)
    monkeypatch.undo()
    (event,) = store.read_events().events
    assert isinstance(event, AdoptEvent)
    return event


def _finish(
    store: ArchiveStore, root_fd: int, gnu_tar: TarTool, archive_id: str, name: str = "e1"
) -> Adopted:
    return finish_adoption(
        store,
        root_fd,
        name,
        archive_id,
        checkout="main",
        verdict="DISPOSABLE",
        proof_ids=("P6",),
        expires_at="2026-11-21T00:00:00+00:00",
        restore_command="hooks-daemon scratch-restore",
        tar=gnu_tar,
        max_inodes=1000,
    )


class TestFinishAdoption:
    def test_needs_the_lock(self, tmp_path: Path, root: Path, root_fd: int) -> None:
        with ArchiveStore.open(tmp_path / "other-store") as unlocked:
            with pytest.raises(StoreRefused, match="lock"):
                _finish(unlocked, root_fd, find_gnu_tar(), "0" * 32)
            with pytest.raises(StoreRefused, match="lock"):
                unfinished_adoptions(unlocked)

    def test_a_crash_before_the_record_is_finished_and_then_restores(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = _crash_before_record(root, root_fd, store, gnu_tar, monkeypatch)
        before = _tree(root / "e1")
        assert unfinished_adoptions(store) == (event,)
        result = _finish(store, root_fd, gnu_tar, event.archive_id)
        assert (result.archive_id, result.original_path, result.tarball) == (
            event.archive_id,
            event.original_path,
            event.tarball,
        )
        (record,) = store.read_index().records
        assert record.archive_id == event.archive_id
        assert record.packed_at == event.at
        assert "P6" in record.proof_ids
        assert record.sha256 == result.sha256
        assert unfinished_adoptions(store) == ()
        audit = store.audit()
        assert (audit.unrecorded_archives, audit.records_without_archive) == ((), ())
        _remove_tree(root / "e1")
        restore(
            store,
            event.archive_id,
            root_fd,
            root_path="untracked/scratch",
            tar=gnu_tar,
            max_inodes=1000,
        )
        assert _tree(root / "e1") == before

    def test_a_changed_original_is_refused_and_the_archive_stays(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = _crash_before_record(root, root_fd, store, gnu_tar, monkeypatch)
        name = archive_file_name(event.archive_id)
        data = (store.path / name).read_bytes()
        (root / "e1" / "a.txt").write_text("changed since")
        with pytest.raises(AdoptRefused, match="differ"):
            _finish(store, root_fd, gnu_tar, event.archive_id)
        assert store.read_index().records == ()
        assert (store.path / name).read_bytes() == data
        assert unfinished_adoptions(store) == (event,)

    def test_a_recorded_id_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        _make(root)
        _pack_by_hand(root)
        adopted = _adopt(store, root_fd, gnu_tar)
        with pytest.raises(AdoptRefused, match="recorded"):
            _finish(store, root_fd, gnu_tar, adopted.archive_id)
        assert len(store.read_index().records) == 1

    def test_an_unknown_id_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, gnu_tar: TarTool
    ) -> None:
        _make(root)
        with pytest.raises(AdoptRefused, match="no adopt event"):
            _finish(store, root_fd, gnu_tar, "0" * 32)
        assert store.read_index().records == ()

    def test_an_expired_id_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = _crash_before_record(root, root_fd, store, gnu_tar, monkeypatch)
        store.append_event(ExpiredEvent(archive_id=event.archive_id, at=event.at))
        assert unfinished_adoptions(store) == ()
        with pytest.raises(AdoptRefused, match="expired"):
            _finish(store, root_fd, gnu_tar, event.archive_id)
        assert store.read_index().records == ()

    def test_another_entry_name_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = _crash_before_record(root, root_fd, store, gnu_tar, monkeypatch)
        _make(root, "e2")
        with pytest.raises(AdoptRefused, match="does not name"):
            _finish(store, root_fd, gnu_tar, event.archive_id, name="e2")
        assert store.read_index().records == ()

    def test_a_crash_before_the_move_has_no_archive_to_finish(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _make(root)
        tarball = _pack_by_hand(root)

        def crash(*_args: Any, **_kwargs: Any) -> None:
            raise Crash

        monkeypatch.setattr(adopt_mod, "rename_noreplace_between", crash)
        with pytest.raises(Crash):
            _adopt(store, root_fd, gnu_tar)
        monkeypatch.undo()
        (event,) = unfinished_adoptions(store)
        with pytest.raises(AdoptRefused, match="not in the store"):
            _finish(store, root_fd, gnu_tar, event.archive_id)
        assert tarball.exists()
        assert store.read_index().records == ()

    def test_a_multi_linked_store_archive_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = _crash_before_record(root, root_fd, store, gnu_tar, monkeypatch)
        name = archive_file_name(event.archive_id)
        os.link(store.path / name, store.path / "extra-link")
        with pytest.raises(AdoptRefused, match="hard links"):
            _finish(store, root_fd, gnu_tar, event.archive_id)
        assert store.read_index().records == ()
        assert (store.path / name).exists()

    def test_a_torn_events_file_is_refused(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        gnu_tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = _crash_before_record(root, root_fd, store, gnu_tar, monkeypatch)
        with (store.path / EVENTS_NAME).open("a") as handle:
            handle.write('{"kind": "exp')
        with pytest.raises(AdoptRefused, match="torn"):
            _finish(store, root_fd, gnu_tar, event.archive_id)
        assert store.read_index().records == ()
