"""A fake scratch tree for the scratch-sweep tests (Plan 00627 Task 1.1).

``root`` plays ``untracked/scratch/``; ``outside`` is a sibling directory that
holds dummy files a link inside the root may point at, so a test can prove the
sweep never followed one. Every timestamp is set with ``lstat`` semantics
(``follow_symlinks=False``), so ageing a tree never touches a link's target.

An unreadable directory is made with :meth:`ScratchTree.refusing_scandir`
rather than ``chmod 000``: these tests run as root in the container, where a
mode of 000 does not stop a listing, and a test built on it would pass without
testing anything.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.core.scratch_walk import ScandirFn

#: name relative to ``base`` -> (mtime_ns, ctime_ns), every inode, links not followed.
Snapshot = dict[str, tuple[int, int]]


@dataclass(frozen=True)
class ScratchTree:
    """A scratch root and an outside directory under one temporary base."""

    base: Path
    root: Path
    outside: Path

    def _path(self, rel: str) -> Path:
        return self.root / rel

    def file(self, rel: str, content: bytes = b"x", mtime: float | None = None) -> Path:
        """A regular file at ``rel`` under the root, parents created."""
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime), follow_symlinks=False)
        return path

    def directory(self, rel: str, mtime: float | None = None) -> Path:
        """A directory at ``rel`` under the root."""
        path = self._path(rel)
        path.mkdir(parents=True, exist_ok=True)
        if mtime is not None:
            os.utime(path, (mtime, mtime), follow_symlinks=False)
        return path

    def outside_dummy(self, name: str, content: bytes = b"dummy") -> Path:
        """A dummy file outside the root, for a link to point at."""
        path = self.outside / name
        path.write_bytes(content)
        return path

    def symlink(self, rel: str, target: Path | str) -> Path:
        """A symbolic link at ``rel`` pointing at ``target`` (never resolved)."""
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        return path

    def hardlink(self, rel: str, existing: Path) -> Path:
        """A second name at ``rel`` for the inode of ``existing``."""
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.hardlink_to(existing)
        return path

    def fifo(self, rel: str) -> Path:
        """A named pipe at ``rel``."""
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)
        return path

    def git_marker(self, rel_dir: str, gitdir: str | None = None) -> Path:
        """A ``.git`` directory in ``rel_dir``, or a ``.git`` FILE naming ``gitdir``."""
        directory = self.directory(rel_dir)
        marker = directory / ".git"
        if gitdir is None:
            marker.mkdir()
        else:
            marker.write_text(f"gitdir: {gitdir}\n")
        return marker

    def set_tree_mtime(self, rel: str, mtime: float) -> None:
        """Set the mtime of ``rel`` and everything under it, deepest first, links not followed."""
        top = self._path(rel)
        for path in [*self._descendants(top), top]:
            os.utime(path, (mtime, mtime), follow_symlinks=False)

    def _descendants(self, top: Path) -> list[Path]:
        if top.is_symlink() or not top.is_dir():
            return []
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(top, topdown=False):
            found.extend(Path(dirpath) / name for name in (*filenames, *dirnames))
        return found

    def refusing_scandir(self, *refused: str) -> ScandirFn:
        """``os.scandir``, raising ``PermissionError`` for each directory in ``refused``."""
        blocked = {str(self._path(rel)) for rel in refused}

        def scandir(path: str) -> os._ScandirIterator[str]:
            if path in blocked:
                raise PermissionError(13, "Permission denied", path)
            return os.scandir(path)

        return scandir

    def snapshot(self) -> Snapshot:
        """Every inode under ``base`` (root and outside): name -> (mtime_ns, ctime_ns).

        atime is left out on purpose: listing a directory may change it.
        """
        result: Snapshot = {}
        for path in self._all_under_base():
            info = os.lstat(path)
            result[path.relative_to(self.base).as_posix()] = (info.st_mtime_ns, info.st_ctime_ns)
        return result

    def _all_under_base(self) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(self.base):
            yield Path(dirpath)
            for name in filenames:
                yield Path(dirpath) / name
            for name in dirnames:
                candidate = Path(dirpath) / name
                if candidate.is_symlink():
                    yield candidate


def build_scratch_tree(base: Path) -> ScratchTree:
    """A fresh fake tree under ``base`` (normally pytest's ``tmp_path``)."""
    root = base / "project" / "untracked" / "scratch"
    outside = base / "outside"
    root.mkdir(parents=True)
    outside.mkdir()
    return ScratchTree(base=base, root=root, outside=outside)
