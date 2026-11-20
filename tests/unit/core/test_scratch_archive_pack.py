"""Pack a claimed entry and verify the archive both ways (Plan 00627 Task 3.3).

DESIGN.md section 5.2 steps 4-5 and section 5.3: GNU tar by argv from inside
the claimed directory, links stored as links, special files skipped and
listed, files with more than one hard link refused; then ``tar --compare``
(archive against tree), the member set (tree against archive), SHA-256 and
``fsync``. Every verification failure discards the unrecorded archive.
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.core import scratch_archive_pack as pack_mod
from claude_code_hooks_daemon.core.scratch_archive import ArchiveStore, new_archive_id
from claude_code_hooks_daemon.core.scratch_archive_claim import (
    Claimed,
    claim,
    fingerprint_at,
    open_dir,
)
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    PackRefused,
    TarTool,
    VerifyFailed,
    find_gnu_tar,
    pack,
    verify,
    verify_remaining,
)


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


def _claim(root_fd: int, name: str) -> Claimed:
    result = claim(root_fd, name, fingerprint_at(root_fd, name, max_inodes=1000), max_inodes=1000)
    assert isinstance(result, Claimed)
    return result


def _entry(root: Path) -> Path:
    entry = root / "e1"
    (entry / "sub").mkdir(parents=True)
    (entry / "a.txt").write_text("alpha")
    (entry / "sub" / "b.bin").write_bytes(bytes(range(256)))
    (entry / "rel-link").symlink_to("a.txt")
    return entry


def _archive_names(store: ArchiveStore, archive_id: str) -> list[str]:
    fd = store.open_archive(archive_id)
    with os.fdopen(fd, "rb") as handle, tarfile.open(fileobj=handle, mode="r|") as archive:
        return [m.name for m in archive]


def _store_files(store: ArchiveStore) -> list[str]:
    return sorted(p.name for p in store.path.iterdir() if p.name.endswith(".tar"))


class TestFindTar:
    def test_finds_gnu_tar(self, tar: TarTool) -> None:
        assert Path(tar.path).is_absolute()

    def test_refuses_a_non_gnu_tar(self, tmp_path: Path) -> None:
        fake = tmp_path / "tar"
        fake.write_text("#!/bin/sh\necho 'bsdtar 3.7.2'\n")
        fake.chmod(0o755)
        with pytest.raises(PackRefused, match="GNU"):
            find_gnu_tar(str(fake))

    def test_refuses_a_missing_tar(self, tmp_path: Path) -> None:
        with pytest.raises(PackRefused):
            find_gnu_tar(str(tmp_path / "absent"))

    def test_ignores_a_tar_earlier_on_the_callers_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D-EXEC 3 (Task 3.9): tar is looked up on the pinned PATH, like every run."""
        shadow = tmp_path / "tar"
        shadow.write_text("#!/bin/sh\necho 'tar (GNU tar) 1.35'\n")
        shadow.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
        assert find_gnu_tar().path != str(shadow)

    def test_a_hung_version_check_is_refused_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def hung(*args: object, **kwargs: object) -> object:
            raise subprocess.TimeoutExpired(cmd="tar", timeout=Timeout.TAR_VERSION_PROBE)

        monkeypatch.setattr(subprocess, "run", hung)
        with pytest.raises(PackRefused, match="did not answer"):
            find_gnu_tar("/usr/bin/tar")


class TestPack:
    def test_round_trip(self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool) -> None:
        _entry(root)
        claimed = _claim(root_fd, "e1")
        archive_id = new_archive_id()
        result = pack(claimed, store, archive_id, tar=tar, max_inodes=1000)
        assert result.members == ("./", "./a.txt", "./rel-link", "./sub/", "./sub/b.bin")
        assert result.skipped == ()
        assert result.counts == {"dir": 2, "file": 2, "symlink": 1}
        assert len(result.sha256) == 64
        assert result.size == (store.path / f"{archive_id}.tar").stat().st_size
        assert sorted(_archive_names(store, archive_id)) == [
            ".",
            "./a.txt",
            "./rel-link",
            "./sub",
            "./sub/b.bin",
        ]
        restore = root.parent / "restored"
        restore.mkdir()
        fd = store.open_archive(archive_id)
        with os.fdopen(fd, "rb") as handle, tarfile.open(fileobj=handle) as archive:
            archive.extractall(restore, filter="tar")
        assert (restore / "sub" / "b.bin").read_bytes() == bytes(range(256))
        assert str((restore / "rel-link").readlink()) == "a.txt"
        claimed.close()

    def test_a_loose_file_entry(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        (root / "notes.txt").write_text("n")
        claimed = _claim(root_fd, "notes.txt")
        result = pack(claimed, store, new_archive_id(), tar=tar, max_inodes=10)
        assert result.members == ("./.sweeping-notes.txt",)
        claimed.close()

    def test_links_are_stored_as_links_and_outside_content_is_not_copied(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, tmp_path: Path
    ) -> None:
        secret = tmp_path / "outside-secret"
        secret.write_text("SECRET-CONTENT")
        before = secret.stat()
        entry = root / "e1"
        entry.mkdir()
        (entry / "to-secret").symlink_to(secret)
        (entry / "to-dir").symlink_to(tmp_path)
        claimed = _claim(root_fd, "e1")
        archive_id = new_archive_id()
        pack(claimed, store, archive_id, tar=tar, max_inodes=100)
        assert b"SECRET-CONTENT" not in (store.path / f"{archive_id}.tar").read_bytes()
        after = secret.stat()
        assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)
        claimed.close()

    def test_special_files_are_skipped_and_listed_without_blocking(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry = root / "e1"
        entry.mkdir()
        (entry / "a.txt").write_text("a")
        os.mkfifo(entry / "pipe")
        claimed = _claim(root_fd, "e1")
        result = pack(claimed, store, new_archive_id(), tar=tar, max_inodes=100)
        assert result.skipped == ("pipe",)
        assert result.members == ("./", "./a.txt")
        assert result.counts["fifo"] == 1
        claimed.close()

    def test_an_entry_that_is_a_fifo_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        os.mkfifo(root / "p")
        claimed = _claim(root_fd, "p")
        with pytest.raises(PackRefused, match="fifo"):
            pack(claimed, store, new_archive_id(), tar=tar, max_inodes=10)
        assert _store_files(store) == []
        claimed.close()

    def test_an_internal_hard_link_pair_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry = root / "e1"
        entry.mkdir()
        (entry / "a").write_text("a")
        os.link(entry / "a", entry / "b")
        claimed = _claim(root_fd, "e1")
        with pytest.raises(PackRefused, match="hard link"):
            pack(claimed, store, new_archive_id(), tar=tar, max_inodes=100)
        assert _store_files(store) == []
        claimed.close()

    def test_a_hard_link_to_outside_content_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.write_text("owned elsewhere")
        entry = root / "e1"
        entry.mkdir()
        os.link(outside, entry / "inside")
        claimed = _claim(root_fd, "e1")
        with pytest.raises(PackRefused, match="hard link"):
            pack(claimed, store, new_archive_id(), tar=tar, max_inodes=100)
        claimed.close()

    def test_hostile_file_names_are_never_options(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, tmp_path: Path
    ) -> None:
        entry = root / "e1"
        entry.mkdir()
        marker = root / ".sweeping-e1" / "pwned-cp"
        hostile = [
            "-rf",
            "--checkpoint=1",
            "--checkpoint-action=exec=touch pwned-cp",
            "--to-command=touch pwned",
            "new\nline",
            " lead space",
        ]
        for name in hostile:
            (entry / name).write_text(name)
        claimed = _claim(root_fd, "e1")
        archive_id = new_archive_id()
        result = pack(claimed, store, archive_id, tar=tar, max_inodes=100)
        assert not marker.exists()
        assert not (root / ".sweeping-e1" / "pwned").exists()
        assert sorted(_archive_names(store, archive_id)) == sorted(
            ["."] + [f"./{n}" for n in hostile]
        )
        assert len(result.members) == len(hostile) + 1
        claimed.close()

    def test_huge_file_count_is_refused_by_the_cap(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        entry = root / "e1"
        entry.mkdir()
        for i in range(300):
            (entry / f"f{i}").write_text("")
        claimed = _claim(root_fd, "e1")
        with pytest.raises(PackRefused, match="inode"):
            pack(claimed, store, new_archive_id(), tar=tar, max_inodes=100)
        assert _store_files(store) == []
        claimed.close()

    def test_a_change_after_the_claim_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        claimed = _claim(root_fd, "e1")
        (root / ".sweeping-e1" / "late").write_text("late")
        with pytest.raises(PackRefused, match="fingerprint"):
            pack(claimed, store, new_archive_id(), tar=tar, max_inodes=1000)
        claimed.close()

    def test_a_failing_tar_discards_the_partial_archive(
        self, root: Path, root_fd: int, store: ArchiveStore, tmp_path: Path
    ) -> None:
        _entry(root)
        fake = tmp_path / "faketar"
        fake.write_text("#!/bin/sh\nprintf 'partial'\nexit 2\n")
        fake.chmod(0o755)
        claimed = _claim(root_fd, "e1")
        with pytest.raises(PackRefused):
            pack(claimed, store, new_archive_id(), tar=TarTool(str(fake)), max_inodes=1000)
        assert _store_files(store) == []
        claimed.close()

    def test_the_tar_environment_is_scrubbed(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        marker = tmp_path / "env-pwned"
        monkeypatch.setenv("TAR_OPTIONS", f"--checkpoint=1 --checkpoint-action=exec=touch {marker}")
        _entry(root)
        claimed = _claim(root_fd, "e1")
        pack(claimed, store, new_archive_id(), tar=tar, max_inodes=1000)
        assert not marker.exists()
        claimed.close()

    def test_the_working_directory_is_the_claimed_inode_not_a_path(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, tmp_path: Path
    ) -> None:
        _entry(root)
        claimed = _claim(root_fd, "e1")
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        (decoy / "a.txt").write_text("DECOY")
        (root / ".sweeping-e1").rename(tmp_path / "moved-away")
        (root / ".sweeping-e1").symlink_to(decoy)
        with pytest.raises(PackRefused):
            pack(claimed, store, new_archive_id(), tar=tar, max_inodes=1000)
        assert (decoy / "a.txt").read_text() == "DECOY"
        claimed.close()


def _packed(
    root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
) -> tuple[Claimed, str, str]:
    _entry(root)
    claimed = _claim(root_fd, "e1")
    archive_id = new_archive_id()
    result = pack(claimed, store, archive_id, tar=tar, max_inodes=1000)
    return claimed, archive_id, result.sha256


class TestVerify:
    def test_verifies_an_untouched_pair(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        claimed, archive_id, sha = _packed(root, root_fd, store, tar)
        result = verify(
            claimed.parent_fd,
            claimed.claimed_name,
            store,
            archive_id,
            tar=tar,
            max_inodes=1000,
            expected_sha256=sha,
        )
        assert result.sha256 == sha
        claimed.close()

    def test_changed_content_fails_the_compare(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        claimed, archive_id, _sha = _packed(root, root_fd, store, tar)
        (root / ".sweeping-e1" / "a.txt").write_text("ALPHA")
        with pytest.raises(VerifyFailed, match="compare"):
            verify(
                claimed.parent_fd, claimed.claimed_name, store, archive_id, tar=tar, max_inodes=1000
            )
        claimed.close()

    def test_a_file_added_after_packing_fails_the_member_set(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        claimed, archive_id, _sha = _packed(root, root_fd, store, tar)
        (root / ".sweeping-e1" / "sub" / "new.txt").write_text("new")
        with pytest.raises(VerifyFailed, match="member"):
            verify(
                claimed.parent_fd, claimed.claimed_name, store, archive_id, tar=tar, max_inodes=1000
            )
        claimed.close()

    def test_a_file_removed_after_packing_fails(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        claimed, archive_id, _sha = _packed(root, root_fd, store, tar)
        (root / ".sweeping-e1" / "a.txt").unlink()
        with pytest.raises(VerifyFailed):
            verify(
                claimed.parent_fd, claimed.claimed_name, store, archive_id, tar=tar, max_inodes=1000
            )
        claimed.close()

    def test_a_corrupted_archive_fails_the_digest(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        claimed, archive_id, sha = _packed(root, root_fd, store, tar)
        path = store.path / f"{archive_id}.tar"
        data = bytearray(path.read_bytes())
        data[-1] ^= 0xFF
        path.write_bytes(bytes(data))
        with pytest.raises(VerifyFailed, match="SHA-256"):
            verify(
                claimed.parent_fd,
                claimed.claimed_name,
                store,
                archive_id,
                tar=tar,
                max_inodes=1000,
                expected_sha256=sha,
            )
        claimed.close()

    @pytest.mark.parametrize(
        "member",
        ["../evil", "/abs/evil", "./sub/../../evil", "./a/../../../etc/x"],
    )
    def test_escaping_member_names_refuse_before_any_compare(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tmp_path: Path,
        member: str,
    ) -> None:
        _entry(root)
        claimed = _claim(root_fd, "e1")
        archive_id = new_archive_id()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
            info = tarfile.TarInfo(member)
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
        fd = store.create_archive(archive_id)
        os.write(fd, buffer.getvalue())
        os.close(fd)
        spy = tmp_path / "spy-tar"
        spy_log = tmp_path / "spy-ran"
        spy.write_text(f"#!/bin/sh\ntouch {spy_log}\nexit 0\n")
        spy.chmod(0o755)
        with pytest.raises(VerifyFailed, match="member"):
            verify(
                claimed.parent_fd,
                claimed.claimed_name,
                store,
                archive_id,
                tar=TarTool(str(spy)),
                max_inodes=1000,
            )
        assert not spy_log.exists()
        claimed.close()

    def test_a_hard_link_member_is_refused(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        _entry(root)
        claimed = _claim(root_fd, "e1")
        archive_id = new_archive_id()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
            info = tarfile.TarInfo("./x")
            info.type = tarfile.LNKTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
        fd = store.create_archive(archive_id)
        os.write(fd, buffer.getvalue())
        os.close(fd)
        with pytest.raises(VerifyFailed, match="member"):
            verify(
                claimed.parent_fd, claimed.claimed_name, store, archive_id, tar=tar, max_inodes=1000
            )
        claimed.close()


class TestVerifyRemaining:
    """A partly removed tree verifies when all that is left is in the archive, unchanged."""

    def _check(self, claimed: Claimed, store: ArchiveStore, archive_id: str, sha: str) -> None:
        verify_remaining(
            claimed.parent_fd,
            claimed.claimed_name,
            store,
            archive_id,
            tar=find_gnu_tar(),
            max_inodes=1000,
            expected_sha256=sha,
        )

    def test_a_whole_tree_verifies(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        claimed, archive_id, sha = _packed(root, root_fd, store, tar)
        self._check(claimed, store, archive_id, sha)
        claimed.close()

    def test_a_partly_removed_tree_verifies(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool
    ) -> None:
        claimed, archive_id, sha = _packed(root, root_fd, store, tar)
        tree = root / claimed.claimed_name
        (tree / "sub" / "b.bin").unlink()
        (tree / "rel-link").unlink()
        self._check(claimed, store, archive_id, sha)
        claimed.close()

    def test_compares_in_argv_batches_and_catches_a_change_in_a_later_one(
        self,
        root: Path,
        root_fd: int,
        store: ArchiveStore,
        tar: TarTool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        claimed, archive_id, sha = _packed(root, root_fd, store, tar)
        tree = root / claimed.claimed_name
        (tree / "sub" / "b.bin").unlink()
        monkeypatch.setattr(pack_mod, "COMPARE_ARGV_BUDGET", 1)
        seen: list[tuple[str, ...]] = []
        real_compare = pack_mod._compare

        def compare(*args: Any, **kwargs: Any) -> None:
            seen.append(kwargs["only"])
            real_compare(*args, **kwargs)

        monkeypatch.setattr(pack_mod, "_compare", compare)
        self._check(claimed, store, archive_id, sha)
        assert seen == [("./a.txt",), ("./rel-link",)]
        (tree / "rel-link").unlink()
        (tree / "rel-link").symlink_to("elsewhere")
        with pytest.raises(VerifyFailed):
            self._check(claimed, store, archive_id, sha)
        claimed.close()

    @pytest.mark.parametrize("change", ["new-file", "changed-content", "wrong-sha"])
    def test_anything_the_archive_lacks_fails(
        self, root: Path, root_fd: int, store: ArchiveStore, tar: TarTool, change: str
    ) -> None:
        claimed, archive_id, sha = _packed(root, root_fd, store, tar)
        tree = root / claimed.claimed_name
        (tree / "sub" / "b.bin").unlink()
        if change == "new-file":
            (tree / "sub" / "late.txt").write_text("late")
        elif change == "changed-content":
            (tree / "a.txt").write_text("ALPHA")
        else:
            sha = "0" * 64
        with pytest.raises(VerifyFailed):
            self._check(claimed, store, archive_id, sha)
        claimed.close()
