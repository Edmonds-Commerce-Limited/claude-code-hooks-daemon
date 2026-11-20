"""Proof P6: adopt a tarball that sits beside its original (Plan 00627 Task 3.7)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

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
