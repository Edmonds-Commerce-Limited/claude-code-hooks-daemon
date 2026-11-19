"""The project link index: where a computed ``cd`` could meet a link, without a walk per call.

Plan 00623. A move bash computes (``cd "$D"``, ``cd -``, ``cd ~/x``) may land in
any project directory, so the secret guard judges a relative word read after it
from every directory holding a link and every directory link. Finding those by
walking the project on each call needed a cap (512 directories), and past the
cap the walk could not finish, so ordinary commands were denied in most real
repositories. The index finds them once, off the hot path, and is then CHECKED
rather than rebuilt.

Trust:

- **Memory only.** The index is held by the daemon process and never written
  to disk. Any file the daemon could keep in the project is one an agent can
  write, and a forged index that left out a directory would hide its link.
- **Verified before every use.** :meth:`LinkIndex.verify` lstats every stored
  directory and compares ``(st_dev, st_ino, st_ctime_ns)``. ctime, not mtime:
  ``touch -d`` resets mtime, and nothing unprivileged sets ctime. Adding,
  removing or renaming an entry changes the ctime of the directory holding it,
  so a changed directory is listed again, as is a new one under it. A
  directory listed within :data:`RACY_SECONDS` of its ctime is listed again
  every time, because a change in the same clock tick leaves ctime unchanged.
- **Link kinds are never stored.** Each link is stat-ed again on every
  verification: its target can change with no change to the directory
  holding it.
- **Fail closed.** A tree past :data:`BUILD_DIRECTORY_CAP` (overflowed), a
  verification past :data:`VERIFY_RELIST_CAP` re-listings (stale) or
  :data:`VERIFY_DEADLINE_SECONDS` (deadline), a root that cannot be stat-ed
  (unreadable), a stored entry that breaks the index's own invariants
  (corrupt), or a link whose target cannot be told: each returns a stopped
  :class:`~claude_code_hooks_daemon.utils.bounded_walk.Bounded`, which every
  caller denies. A directory that cannot be listed is reported as holding a
  link, and stops the result too: what lies under it is unknown (unlisted).
"""

from __future__ import annotations

import errno
import logging
import os
import stat
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.bounded_walk import Bounded, finished, stopped
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

#: A project with more directories than this is not indexed (overflowed: callers deny).
BUILD_DIRECTORY_CAP: Final[int] = 200_000
#: A build that takes longer than this is abandoned (overflowed).
BUILD_DEADLINE_SECONDS: Final[float] = 60.0
#: One verification lists at most this many changed or new directories again (stale past it).
VERIFY_RELIST_CAP: Final[int] = 4096
#: One verification gives up after this long (deadline).
VERIFY_DEADLINE_SECONDS: Final[float] = 2.0
#: A directory whose ctime is this close to when it was listed is listed again.
RACY_SECONDS: Final[float] = 3.0
#: A build that failed or overflowed is not retried for this long.
RETRY_AFTER_SECONDS: Final[float] = 30.0
#: How many projects' indexes the daemon holds.
MAX_INDEXES: Final[int] = 4

_GIT_DIRECTORY: Final[str] = ".git"
_NANOSECONDS: Final[int] = 1_000_000_000

_OVERFLOWED: Final[str] = "the project link index overflowed its directory cap"
_STALE: Final[str] = "the project link index is stale: too many directories changed to re-list"
_DEADLINE: Final[str] = "the project link index could not be verified before its deadline"
_UNREADABLE: Final[str] = "the project link index is unreadable: the project root cannot be stat-ed"
_CORRUPT: Final[str] = "the project link index is corrupt"
_UNCLASSIFIED: Final[str] = "the project link index holds a link whose target cannot be told"
_UNLISTED: Final[str] = "the project link index holds a directory that cannot be listed"

_Identity = tuple[int, int, int]


@dataclass(frozen=True)
class _Listing:
    """One directory as last listed."""

    identity: _Identity | None
    listed_at_ns: int
    #: Subdirectories (not links, not ``.git``), as absolute paths.
    children: tuple[str, ...]
    #: Link entries, as absolute paths.
    links: tuple[str, ...]
    #: The directory could not be listed: it is judged as holding a link.
    unlistable: bool = False


@dataclass(frozen=True)
class LinkScanResult:
    """Every directory holding a link (or unlistable), and every link leading to a directory."""

    holding: tuple[str, ...]
    directory_links: tuple[str, ...]


def _identity(stat: os.stat_result) -> _Identity:
    return (stat.st_dev, stat.st_ino, stat.st_ctime_ns)


def _list(path: str, stat: os.stat_result | None) -> _Listing:
    """List ``path`` now; ``stat`` is its lstat taken BEFORE the listing (None: none could be taken)."""
    children: list[str] = []
    links: list[str] = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_symlink():
                    links.append(entry.path)
                elif entry.name != _GIT_DIRECTORY and _may_be_directory(entry):
                    children.append(entry.path)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="a directory the link index cannot list may hold a link, so it is judged as one that does (fail closed)",
            level=logging.DEBUG,
        )
        return _Listing(None, time.time_ns(), (), (), unlistable=True)
    identity = None if stat is None else _identity(stat)
    return _Listing(identity, time.time_ns(), tuple(children), tuple(links))


def _may_be_directory(entry: os.DirEntry[str]) -> bool:
    """Is non-link ``entry`` a directory: True when that cannot be told, so it is listed."""
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="an entry the link index cannot classify may be a directory, so it is listed (fail closed)",
            level=logging.DEBUG,
        )
        return True


def _lstat(path: str) -> os.stat_result | OSError:
    """``path``'s lstat, or the error that refused it (the caller re-lists, failing closed)."""
    try:
        return os.lstat(path)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="a directory the link index cannot stat is listed again (fail closed)",
            level=logging.DEBUG,
        )
        return exc


class _LinkKind(Enum):
    DIRECTORY = "directory"
    OTHER = "other"
    UNKNOWN = "unknown"


def _link_kind(link: str) -> _LinkKind:
    """Does ``link`` lead to a directory; UNKNOWN when that cannot be told."""
    try:
        return _LinkKind.DIRECTORY if stat.S_ISDIR(Path(link).stat().st_mode) else _LinkKind.OTHER
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOENT, errno.ENOTDIR):
            # A loop or a dangling link leads nowhere a `cd` can land.
            return _LinkKind.OTHER
        log_and_continue(
            logger,
            exc,
            reason="a link whose target cannot be stat-ed may lead to a directory (fail closed)",
            level=logging.DEBUG,
        )
        return _LinkKind.UNKNOWN


class LinkIndex:
    """One project's directories and links, checked against the filesystem on each use."""

    def __init__(self, root: str, listings: dict[str, _Listing], *, overflowed: bool) -> None:
        self.root = root
        self._listings = listings
        self._overflowed = overflowed
        self._lock = threading.Lock()

    @property
    def overflowed(self) -> bool:
        return self._overflowed

    def verify(self) -> Bounded[LinkScanResult]:
        """What the project holds NOW, or a stopped result naming why that cannot be told."""
        empty = LinkScanResult((), ())
        if self._overflowed:
            return stopped(empty, _OVERFLOWED)
        with self._lock:
            return self._verify_locked(empty)

    def _verify_locked(self, empty: LinkScanResult) -> Bounded[LinkScanResult]:
        deadline = time.monotonic() + VERIFY_DEADLINE_SECONDS
        racy_ns = int(RACY_SECONDS * _NANOSECONDS)
        if isinstance(_lstat(self.root), OSError):
            return stopped(empty, _UNREADABLE)
        holding: list[str] = []
        directory_links: list[str] = []
        unclassified = False
        unlisted = False
        relisted = 0
        seen: dict[str, _Listing] = {}
        queue: deque[str] = deque([self.root])
        while queue:
            if time.monotonic() > deadline:
                return stopped(empty, _DEADLINE)
            path = queue.popleft()
            stored = self._listings.get(path)
            if stored is not None and not _well_formed(path, stored):
                return stopped(empty, _CORRUPT)
            found = _lstat(path)
            now = found if isinstance(found, os.stat_result) else None
            if now is None and stored is not None and not os.path.lexists(path):
                # Gone since it was listed: a removal adds no link.
                continue
            current = stored
            if (
                current is None
                or current.unlistable
                or now is None
                or current.identity != _identity(now)
                or now.st_ctime_ns + racy_ns >= current.listed_at_ns
            ):
                relisted += 1
                if relisted > VERIFY_RELIST_CAP:
                    return stopped(empty, _STALE)
                current = _list(path, now)
            seen[path] = current
            if len(seen) > BUILD_DIRECTORY_CAP:
                self._overflowed = True
                return stopped(empty, _OVERFLOWED)
            if current.unlistable or current.links:
                holding.append(path)
            # What lies under a directory that cannot be listed is unknown, and bash
            # can still move through it (Plan 00623 review): the result is stopped.
            unlisted = unlisted or current.unlistable
            for link in current.links:
                kind = _link_kind(link)
                if kind is _LinkKind.UNKNOWN:
                    unclassified = True
                elif kind is _LinkKind.DIRECTORY:
                    directory_links.append(link)
            queue.extend(current.children)
        self._listings = seen
        result = LinkScanResult(tuple(holding), tuple(directory_links))
        if unlisted:
            return stopped(result, _UNLISTED)
        return stopped(result, _UNCLASSIFIED) if unclassified else finished(result)

    def age_for_tests(self, *, seconds: float) -> None:
        """Pretend every directory was listed ``seconds`` later than its ctime (tests only)."""
        shift = int(seconds * _NANOSECONDS)
        self._listings = {
            path: _Listing(
                listing.identity,
                listing.listed_at_ns + shift,
                listing.children,
                listing.links,
                listing.unlistable,
            )
            for path, listing in self._listings.items()
        }

    def corrupt_for_tests(self) -> None:
        """Store a child outside its parent (tests only)."""
        listing = self._listings[self.root]
        self._listings[self.root] = _Listing(
            listing.identity,
            listing.listed_at_ns,
            (*listing.children, "/elsewhere"),
            listing.links,
            listing.unlistable,
        )


def _well_formed(path: str, listing: _Listing) -> bool:
    """Does ``listing`` keep the index's invariants: every entry directly under ``path``."""
    prefix = path.rstrip("/") + "/"
    return all(
        entry.startswith(prefix) and "/" not in entry[len(prefix) :]
        for entry in (*listing.children, *listing.links)
    )


def build_link_index(root: str) -> LinkIndex:
    """List every directory under ``root`` (not entering ``.git``, not following links)."""
    root = os.path.normpath(root)
    deadline = time.monotonic() + BUILD_DEADLINE_SECONDS
    listings: dict[str, _Listing] = {}
    queue: deque[str] = deque([root])
    while queue:
        if len(listings) >= BUILD_DIRECTORY_CAP or time.monotonic() > deadline:
            return LinkIndex(root, {}, overflowed=True)
        path = queue.popleft()
        found = _lstat(path)
        listing = _list(path, found if isinstance(found, os.stat_result) else None)
        listings[path] = listing
        queue.extend(listing.children)
    return LinkIndex(root, listings, overflowed=False)


# ── Cache, built in the background ──────────────────────────────────────────

_lock = threading.Lock()
_indexes: OrderedDict[str, LinkIndex] = OrderedDict()
_building: dict[str, threading.Thread] = {}
_retry_after: dict[str, float] = {}


def link_scan_for(root: str) -> Bounded[LinkScanResult] | None:
    """The verified scan of ``root``'s index; None while there is none (a build is started)."""
    key = os.path.normpath(root)
    with _lock:
        held = _indexes.get(key)
        if held is not None:
            _indexes.move_to_end(key)
    if held is None:
        _start_build(key)
        return None
    result = held.verify()
    if not result.complete and result.reason in (_OVERFLOWED, _STALE, _DEADLINE, _CORRUPT):
        _start_build(key)
    return result


def prewarm(root: str) -> None:
    """Start building ``root``'s index now; never waits for it."""
    key = os.path.normpath(root)
    with _lock:
        held = key in _indexes
    if not held:
        _start_build(key)


def _start_build(key: str) -> None:
    now = time.monotonic()
    with _lock:
        if key in _building or now < _retry_after.get(key, 0.0):
            return
        thread = threading.Thread(
            target=_build_and_remember, args=(key,), name="link-index-build", daemon=True
        )
        _building[key] = thread
    thread.start()


def _build_and_remember(key: str) -> None:
    try:
        built = build_link_index(key)
        with _lock:
            _indexes[key] = built
            _indexes.move_to_end(key)
            while len(_indexes) > MAX_INDEXES:
                _indexes.popitem(last=False)
            if built.overflowed:
                _retry_after[key] = time.monotonic() + RETRY_AFTER_SECONDS
    except Exception as exc:
        # A thread's uncaught exception goes to stderr, which nothing reads.
        logger.warning("link index for %s could not be built: %s", key, type(exc).__name__)
        with _lock:
            _retry_after[key] = time.monotonic() + RETRY_AFTER_SECONDS
    finally:
        with _lock:
            _building.pop(key, None)


def wait_for_link_index(timeout: float) -> None:
    """Block until the builds in flight finish; for tests and the comparison harness."""
    with _lock:
        threads = list(_building.values())
    for thread in threads:
        thread.join(timeout=timeout)


def reset_link_indexes() -> None:
    """Forget every index (tests)."""
    wait_for_link_index(timeout=BUILD_DEADLINE_SECONDS)
    with _lock:
        _indexes.clear()
        _retry_after.clear()
