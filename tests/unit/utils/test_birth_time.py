"""A file's birth time through statx (Plan 00627: claim identity survives inode reuse)."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import birth_time
from claude_code_hooks_daemon.utils.birth_time import birth_stamp

_NS = 1_000_000_000


def _stat_w(path: Path) -> int:
    """``stat -c %W``: whole seconds, 0 when the filesystem has no birth time."""
    stat_bin = shutil.which("stat")
    if stat_bin is None:
        pytest.skip("no stat(1) to cross-check against")
    out = subprocess.run(
        [stat_bin, "-c", "%W", str(path)], capture_output=True, text=True, check=True
    )
    return int(out.stdout.strip())


@pytest.fixture
def dir_fd(tmp_path: Path) -> Iterator[int]:
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    yield fd
    os.close(fd)


def test_the_stamp_matches_stat_and_lstat(tmp_path: Path, dir_fd: int) -> None:
    (tmp_path / "d").mkdir()
    seconds = _stat_w(tmp_path / "d")
    stamp = birth_stamp(dir_fd, "d")
    if seconds == 0:
        assert stamp is None
        return
    assert stamp is not None
    assert stamp.birth_ns // _NS == seconds
    info = os.lstat(tmp_path / "d")
    assert (stamp.ino, stamp.dev) == (info.st_ino, info.st_dev)


def test_a_link_is_stamped_itself_never_its_target(tmp_path: Path, dir_fd: int) -> None:
    (tmp_path / "target").mkdir()
    (tmp_path / "link").symlink_to("target")
    stamp = birth_stamp(dir_fd, "link")
    if stamp is None:
        pytest.skip("this filesystem reports no birth time")
    assert stamp.ino == os.lstat(tmp_path / "link").st_ino


def test_a_missing_name_raises(dir_fd: int) -> None:
    with pytest.raises(FileNotFoundError):
        birth_stamp(dir_fd, "absent")


def test_no_statx_in_libc_means_no_stamp(
    tmp_path: Path, dir_fd: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "d").mkdir()
    monkeypatch.setattr(birth_time, "_STATX", None)
    assert birth_stamp(dir_fd, "d") is None


def test_a_filesystem_without_birth_time_means_no_stamp(
    tmp_path: Path, dir_fd: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "d").mkdir()
    monkeypatch.setattr(birth_time, "_STATX_BTIME", 0)
    assert birth_stamp(dir_fd, "d") is None
