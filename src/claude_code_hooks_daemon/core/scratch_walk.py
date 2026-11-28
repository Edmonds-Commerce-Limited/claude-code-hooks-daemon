"""Walk one scratch entry and record what it holds (Plan 00627 Task 1.3).

The walk reads ``lstat`` data and directory listings only. It never follows a
link, never opens a file and never leaves the entry root's device. It shares
one :class:`WalkBudget` (a deadline and an inode cap) with every other entry
of the same sweep, and any stop -- an unreadable directory, a spent budget, a
second device, an entry that vanished -- is returned as
:func:`~claude_code_hooks_daemon.utils.bounded_walk.stopped` with its reason.
An incomplete walk is never read as "nothing there" (DESIGN.md section 5.3).
"""

from __future__ import annotations

import enum
import os
import stat
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from claude_code_hooks_daemon.utils.bounded_walk import Bounded, finished, stopped

#: ``os.scandir`` as the walker calls it: one string path in, an iterator of entries out.
ScandirFn = Callable[[str], AbstractContextManager[Iterator[os.DirEntry[str]]]]

#: The name git gives its directory, or the file pointing at it, in a checkout.
GIT_MARKER = ".git"

#: A scratch root's own ignore file: part of the root, never an entry.
ROOT_IGNORE_FILE = ".gitignore"

_NANOSECONDS = 1_000_000_000


class NodeKind(enum.Enum):
    """What one inode in an entry is, from ``lstat`` alone."""

    DIRECTORY = "directory"
    FILE = "file"
    SYMLINK = "symlink"
    SPECIAL = "special"
    #: An entry root the walk could not ``lstat``: its walk is always stopped.
    UNREAD = "unread"


@dataclass(frozen=True)
class Node:
    """One inode of an entry. ``path`` is relative to the scratch root, entry name first."""

    path: str
    kind: NodeKind
    size: int
    #: True only for a directory the walk listed and found with no children.
    empty: bool = False


@dataclass
class EntryStats:
    """What a walk found in one entry; for a stopped walk, what it found before stopping."""

    name: str
    kind: NodeKind
    root_ctime_ns: int
    directories: int = 0
    files: int = 0
    bytes: int = 0
    #: Newest mtime of any inode; an mtime after ``now`` counts as that inode's ctime.
    newest_mtime_ns: int = 0
    nodes: list[Node] = field(default_factory=list)
    special_files: tuple[str, ...] = ()
    #: Files with more names than the walk saw inside the entry: another name is elsewhere.
    multi_linked: tuple[str, ...] = ()
    git_markers: tuple[str, ...] = ()
    #: Where an entry that is itself a link points; never followed.
    link_target: str | None = None


class WalkBudget:
    """One deadline and one inode cap, shared by every entry of one sweep."""

    def __init__(
        self,
        *,
        seconds: float,
        max_inodes: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if seconds <= 0 or max_inodes < 1:
            raise ValueError("a walk budget needs positive seconds and at least one inode")
        self._clock = clock
        self._deadline = clock() + seconds
        self._max_inodes = max_inodes
        self._inodes = 0
        self.spent_reason = ""

    def spend(self) -> str:
        """Charge one inode. Returns why the budget is spent, or "" while it is not."""
        if self.spent_reason:
            return self.spent_reason
        self._inodes += 1
        if self._inodes > self._max_inodes:
            self.spent_reason = f"inode cap of {self._max_inodes} reached"
        elif self._clock() >= self._deadline:
            self.spent_reason = "walk deadline reached"
        return self.spent_reason


def kind_of(mode: int) -> NodeKind:
    """The :class:`NodeKind` of an ``lstat`` mode."""
    if stat.S_ISDIR(mode):
        return NodeKind.DIRECTORY
    if stat.S_ISLNK(mode):
        return NodeKind.SYMLINK
    if stat.S_ISREG(mode):
        return NodeKind.FILE
    return NodeKind.SPECIAL


class _Walk:
    """The state of one entry's walk."""

    def __init__(self, root: Path, now: float, budget: WalkBudget, scandir: ScandirFn) -> None:
        self._root = root
        self._now_ns = int(now * _NANOSECONDS)
        self._budget = budget
        self._scandir = scandir
        self._specials: list[str] = []
        self._markers: list[str] = []
        self._names: Counter[tuple[int, int]] = Counter()
        self._link_counts: dict[tuple[int, int], tuple[int, list[str]]] = {}
        self.stats = EntryStats(name="", kind=NodeKind.UNREAD, root_ctime_ns=0)

    def run(self, name: str) -> str:
        """Walk entry ``name``. Returns why the walk stopped, or "" when it finished."""
        top = self._root / name
        self.stats.name = name
        try:
            info = os.lstat(top)
        except OSError as exc:
            return f"entry {name} could not be read: {type(exc).__name__}"
        kind = kind_of(info.st_mode)
        self.stats.kind = kind
        self.stats.root_ctime_ns = info.st_ctime_ns
        device = info.st_dev
        reason = self._budget.spend()
        if reason:
            return reason
        if kind is NodeKind.SYMLINK:
            try:
                self.stats.link_target = str(top.readlink())
            except OSError as exc:
                return f"entry link {name} could not be read: {type(exc).__name__}"
        pending: list[tuple[Path, str, os.stat_result]] = [(top, name, info)]
        while pending:
            path, rel, node_info = pending.pop()
            reason = self._record(path, rel, node_info, device, pending)
            if reason:
                return reason
        return ""

    def _record(
        self,
        path: Path,
        rel: str,
        info: os.stat_result,
        device: int,
        pending: list[tuple[Path, str, os.stat_result]],
    ) -> str:
        if info.st_dev != device:
            return f"{rel} is on a second device"
        kind = kind_of(info.st_mode)
        mtime_ns = info.st_ctime_ns if info.st_mtime_ns > self._now_ns else info.st_mtime_ns
        self.stats.newest_mtime_ns = max(self.stats.newest_mtime_ns, mtime_ns)
        if path.name == GIT_MARKER:
            self._markers.append(rel)
        if kind is not NodeKind.DIRECTORY:
            self._record_leaf(rel, kind, info)
            return ""
        self.stats.directories += 1
        try:
            with self._scandir(str(path)) as listing:
                children = sorted(child.name for child in listing)
        except OSError as exc:
            return f"directory {rel} could not be listed: {type(exc).__name__}"
        self.stats.nodes.append(Node(rel, kind, 0, empty=not children))
        for child in children:
            reason = self._budget.spend()
            if reason:
                return reason
            child_path = path / child
            try:
                child_info = os.lstat(child_path)
            except OSError as exc:
                return f"{rel}/{child} could not be read: {type(exc).__name__}"
            pending.append((child_path, f"{rel}/{child}", child_info))
        return ""

    def _record_leaf(self, rel: str, kind: NodeKind, info: os.stat_result) -> None:
        self.stats.nodes.append(Node(rel, kind, info.st_size))
        self.stats.bytes += info.st_size
        if kind is NodeKind.SPECIAL:
            self._specials.append(rel)
        else:
            self.stats.files += 1
        key = (info.st_dev, info.st_ino)
        self._names[key] += 1
        paths = self._link_counts.setdefault(key, (info.st_nlink, []))[1]
        paths.append(rel)

    def finish(self) -> EntryStats:
        """The stats, with the lists that need the whole walk filled in."""
        multi = [
            path
            for key, (nlink, paths) in self._link_counts.items()
            if nlink > self._names[key]
            for path in paths
        ]
        self.stats.special_files = tuple(sorted(self._specials))
        self.stats.multi_linked = tuple(sorted(multi))
        self.stats.git_markers = tuple(sorted(self._markers))
        self.stats.nodes.sort(key=lambda node: node.path)
        return self.stats


def walk_entry(
    root: Path,
    name: str,
    *,
    now: float,
    budget: WalkBudget,
    scandir: ScandirFn = os.scandir,
) -> Bounded[EntryStats]:
    """Walk entry ``name`` of scratch root ``root``, charging ``budget``.

    ``now`` is the wall clock in seconds, for spotting an mtime in the future.
    An entry root that could not be read has kind :attr:`NodeKind.UNREAD`.
    """
    walk = _Walk(root, now, budget, scandir)
    reason = walk.run(name)
    stats = walk.finish()
    return stopped(stats, reason) if reason else finished(stats)


def list_entries(root: Path, *, scandir: ScandirFn = os.scandir) -> Bounded[tuple[str, ...]]:
    """The entries of scratch root ``root``, sorted, without the root's own ignore file."""
    try:
        with scandir(str(root)) as listing:
            names = sorted(child.name for child in listing if child.name != ROOT_IGNORE_FILE)
    except OSError as exc:
        return stopped((), f"scratch root {root} could not be listed: {type(exc).__name__}")
    return finished(tuple(names))


__all__ = [
    "GIT_MARKER",
    "ROOT_IGNORE_FILE",
    "EntryStats",
    "Node",
    "NodeKind",
    "ScandirFn",
    "WalkBudget",
    "kind_of",
    "list_entries",
    "walk_entry",
]
