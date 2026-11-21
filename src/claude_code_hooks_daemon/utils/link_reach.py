"""The protected files a link-following recursive read reaches through a link (Plan 00613).

A worktree seeded in link mode holds links into the main checkout, and
``grep -R``, ``find -L``, ``zip -r`` and the like FOLLOW every link below the
root they are handed. The protected-file index answers only for what a root
lexically holds (:meth:`ProtectedFileIndex.find_under`), so a protected file
behind a link below the root was read with no word of the command naming it.

:func:`reached_through_links` lists the links below a root and judges each
target as a read of the target itself would be judged:

- a directory link (followed only by a :attr:`LinkFollow.ALL` reader) is a root
  of its own, asked of :meth:`~ProtectedFileIndex.find_under`, which fails closed
  for a target outside the project; the links inside it are listed in turn;
- a file link (followed by :attr:`LinkFollow.FILES` and ``ALL`` readers) is
  protected when its target is an indexed file or a protected glob matches the
  link or its target.

The links come from the verified in-memory link index (Plan 00623) when the
root lies in the project and the index is complete, and otherwise from a
bounded walk that does not follow links. Fail closed: a walk past its caps or
deadline, more links than :data:`LINK_CAP`, a link whose target cannot be
stat-ed, or a project with no link index for a root above it each answer the
first protected pattern, so the caller denies.
"""

from __future__ import annotations

import errno
import logging
import os
import stat
import time
from collections import deque
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils import link_index
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.protected_file_index import ProtectedFileIndex, TreeView

logger = logging.getLogger(__name__)

#: Directories one bounded walk lists before it stops (the read is then denied).
WALK_DIRECTORY_CAP: Final[int] = 4096
#: Links one judgement follows before it stops (the read is then denied).
LINK_CAP: Final[int] = 4096
#: Wall-clock budget of one judgement (the read is then denied).
DEADLINE_SECONDS: Final[float] = 2.0


class LinkFollow(Enum):
    """Which links below its root a recursive reader follows."""

    #: Proven to follow none (``grep -r``, ``rg`` without ``-L``, ``git grep``).
    NONE = "none"
    #: Opens file links but does not descend directory links (``find -exec cat``).
    FILES = "files"
    #: Follows every link (``grep -R``, ``find -L``, ``zip``, anything not proven otherwise).
    ALL = "all"


class _Stopped(Exception):
    """The links below a root could not all be judged: the read fails closed."""


class _Kind(Enum):
    DIRECTORY = "directory"
    FILE = "file"
    GONE = "gone"


def _is_under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip("/") + "/")


def _strictly_under(path: str, base: str) -> bool:
    return path != base and _is_under(path, base)


def _kind(link: str) -> _Kind:
    """What ``link`` leads to; a loop or a dangling link leads nowhere a reader opens."""
    try:
        mode = Path(link).stat().st_mode
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOENT, errno.ENOTDIR):
            return _Kind.GONE
        raise _Stopped("a link whose target cannot be stat-ed") from exc
    return _Kind.DIRECTORY if stat.S_ISDIR(mode) else _Kind.FILE


class _Links:
    """Where the links below a directory are found: the link index, else a bounded walk."""

    def __init__(self, project_root: str, deadline: float) -> None:
        self._root = os.path.normpath(project_root)
        self._real_root = os.path.realpath(project_root)
        self._deadline = deadline
        self._scan_read = False
        self._indexed: tuple[str, ...] | None = None

    def _index_links(self) -> tuple[str, ...] | None:
        if not self._scan_read:
            self._scan_read = True
            scan = link_index.link_scan_for(self._root)
            if scan is not None and scan.complete:
                self._indexed = scan.value.links
        return self._indexed

    def _in_project(self, path: str) -> str | None:
        """``path`` spelled as the link index spells it, when it lies in the project."""
        if _is_under(path, self._root):
            return path
        if _is_under(path, self._real_root):
            return self._root + path[len(self._real_root) :]
        return None

    def beneath(self, directory: str) -> list[str]:
        """Every link below ``directory`` (it may itself be a link, which is followed)."""
        lexical = os.path.normpath(directory)
        real = os.path.realpath(directory)
        spelled = [s for s in dict.fromkeys((lexical, real)) if s]
        placed = [p for p in (self._in_project(s) for s in spelled) if p is not None]
        if placed:
            indexed = self._index_links()
            if indexed is not None:
                return [link for link in indexed if any(_strictly_under(link, p) for p in placed)]
            return self._walk(lexical)
        if any(_is_under(self._real_root, s) or _is_under(self._root, s) for s in spelled):
            # A root above the project (``/`` for a read that cannot be placed): the
            # project's links are judged, and only the link index lists them all.
            indexed = self._index_links()
            if indexed is None:
                raise _Stopped("the project's link index is not available")
            return list(indexed)
        return self._walk(lexical)

    def _walk(self, directory: str) -> list[str]:
        """The links below ``directory``, listed without following any below it."""
        links: list[str] = []
        queue: deque[str] = deque([directory])
        listed = 0
        while queue:
            if time.monotonic() > self._deadline:
                raise _Stopped("the walk passed its deadline")
            listed += 1
            if listed > WALK_DIRECTORY_CAP:
                raise _Stopped("the walk passed its directory cap")
            path = queue.popleft()
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        if entry.is_symlink():
                            links.append(entry.path)
                        elif entry.is_dir(follow_symlinks=False):
                            queue.append(entry.path)
            except (FileNotFoundError, NotADirectoryError) as exc:
                # A file root that is itself a link is find_under's to judge.
                log_and_continue(
                    logger,
                    exc,
                    reason="a missing root, or a file, holds no link below it",
                    level=logging.DEBUG,
                )
                continue
            except OSError as exc:
                log_and_continue(
                    logger,
                    exc,
                    reason="a directory a link-following read enters cannot be listed (fail closed)",
                    level=logging.DEBUG,
                )
                raise _Stopped("a directory cannot be listed") from exc
        return links


def reached_through_links(
    root: str,
    follow: LinkFollow,
    index: ProtectedFileIndex,
    *,
    is_exempt: Callable[[str], bool] | None = None,
) -> str | None:
    """The protected pattern a read of ``root`` that follows ``follow`` links reaches, else None.

    Only what lies BEHIND a link is judged here: what ``root`` lexically holds is
    :meth:`ProtectedFileIndex.find_under`'s answer.
    """
    if follow is LinkFollow.NONE or not index.patterns:
        return None
    fail_closed = index.patterns[0]
    deadline = time.monotonic() + DEADLINE_SECONDS
    links = _Links(index.project_root, deadline)
    try:
        return _judge(root, follow, index, links, is_exempt, deadline)
    except _Stopped as stopped:
        logger.debug("link-following read not judged in full: %s (fail closed)", stopped)
        return fail_closed


def _judge(
    root: str,
    follow: LinkFollow,
    index: ProtectedFileIndex,
    links: _Links,
    is_exempt: Callable[[str], bool] | None,
    deadline: float,
) -> str | None:
    from claude_code_hooks_daemon.utils.secret_file_matching import protecting_pattern_under

    queue: deque[str] = deque([root])
    entered: set[str] = set()
    judged = 0
    while queue:
        directory = queue.popleft()
        real = os.path.realpath(directory)
        if real in entered:
            continue
        entered.add(real)
        for link in links.beneath(directory):
            judged += 1
            if judged > LINK_CAP or time.monotonic() > deadline:
                raise _Stopped("more links than one judgement follows")
            kind = _kind(link)
            if kind is _Kind.GONE:
                continue
            if kind is _Kind.DIRECTORY:
                if follow is not LinkFollow.ALL:
                    continue
                hit = index.find_under(link, view=TreeView.ALL, is_exempt=is_exempt)
                if hit is not None:
                    return hit
                queue.append(link)
                continue
            target = os.path.realpath(link)
            if is_exempt is not None and is_exempt(target):
                continue
            hit = index.find_under(link, view=TreeView.ALL, is_exempt=is_exempt)
            if hit is None:
                hit = protecting_pattern_under(link, index.patterns, index.project_root)
            if hit is not None:
                return hit
    return None
