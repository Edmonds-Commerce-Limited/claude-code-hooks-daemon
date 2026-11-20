"""Proof P6: adopt a tarball that sits beside its original (Plan 00627 Task 3.7)."""

from __future__ import annotations

import gzip
import io
import lzma
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import scratch_archive_pack as pack_mod
from claude_code_hooks_daemon.core.scratch_archive_pack import (
    PackRefused,
    compression_flags,
    compression_of,
    require_decompressor,
    tarfile_mode,
)

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
def test_a_missing_decompressor_is_a_refusal(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pack_mod.shutil, "which", lambda *_a, **_k: None)
    with pytest.raises(PackRefused, match="decompressor"):
        require_decompressor(kind)


def test_a_plain_tar_needs_no_decompressor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pack_mod.shutil, "which", lambda *_a, **_k: None)
    require_decompressor("none")
