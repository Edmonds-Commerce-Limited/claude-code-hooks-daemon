"""Where the protected files are, found once and looked up in memory (Plan 00483 A2).

A recursive search (``grep -r .``) or a glob (``cat keys/*``) reads protected
files without naming them. Answering "does it reach one?" by walking the
filesystem on every call meant caps and deadlines, and verdicts that changed
with the size of the tree and the load on the host. The owner ruled that out:
the answer comes from an index of the protected files that exist, built off the
hot path and consulted in memory.

The index is built from ``git ls-files`` (:mod:`git_file_states`), the same scan
the SessionStart hygiene sweep already makes, so a protected file carries what
the search tools need to know: whether git tracks it and whether an ignore rule
covers it. It is kept per ``(project root, patterns)`` and rebuilt in the
background once it is older than :data:`REFRESH_AFTER_SECONDS`; a call never
waits for a build. With no index yet (the daemon has only just started, or the
project is not a git repository) a lookup has nothing to judge against and the
caller allows with an advisory.

What the index deliberately does not cover: a protected file created after the
last build is found at the next one, and a file inside a nested checkout or a
git worktree is a separate repository's business.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import run_git

if TYPE_CHECKING:
    from claude_code_hooks_daemon.utils.git_file_states import GitFileStates

logger = logging.getLogger(__name__)

#: A built index is rebuilt in the background once it is this old.
REFRESH_AFTER_SECONDS: Final[float] = 600.0

#: A build that failed is tried again after this long, not after a whole refresh
#: interval: the usual cause is a busy host, and a guard with no index can only advise.
RETRY_AFTER_FAILURE_SECONDS: Final[float] = 30.0

#: Indexes kept at once (one per project and pattern set; a daemon serves one project).
MAX_CACHED_INDEXES: Final[int] = 8

_HIDDEN_PREFIX: Final[str] = "."
_RECURSIVE_COMPONENT: Final[str] = "**"
_WILDCARD_ONLY: Final[re.Pattern[str]] = re.compile(r"[*?]+")

#: A glob with this many wildcard-only components names no particular place.
_NAMELESS_DEPTH: Final[int] = 2


class TreeView(StrEnum):
    """Which files a search tool reads under its root."""

    ALL = "all"
    UNIGNORED = "unignored"
    TRACKED = "tracked"


@runtime_checkable
class IndexPrewarmer(Protocol):
    """A handler that reads an index and can start building it ahead of its first call."""

    def prewarm_index(self) -> None:
        """Start the background build; never wait for it."""


SkipHook = Callable[[str, bool], bool]
ExemptHook = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class IndexedFile:
    """One protected file: where it is, the glob that protects it, and its git state."""

    relpath: str
    pattern: str
    tracked: bool
    ignored: bool


@dataclass(frozen=True)
class ProtectedFileIndex:
    """The protected files of one project, as of ``built_at`` (a monotonic instant)."""

    project_root: str
    patterns: tuple[str, ...]
    files: tuple[IndexedFile, ...]
    built_at: float = field(default_factory=time.monotonic)

    def _absolute(self, entry: IndexedFile) -> str:
        return f"{self.project_root}/{entry.relpath}"

    def _roots(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.project_root, os.path.realpath(self.project_root))))

    def find_under(
        self,
        root: str,
        *,
        view: TreeView = TreeView.ALL,
        skip: SkipHook | None = None,
        is_exempt: ExemptHook | None = None,
    ) -> str | None:
        """The protected glob of the first indexed file a search of ``root`` reads, else None.

        ``view`` is which files the tool reads (:class:`TreeView`); ``skip(path, is_dir)``
        drops an entry it would not read, such as a hidden or an excluded directory;
        ``is_exempt`` skips a file the caller confirmed safe (encrypted at rest). A file
        the tool is handed by name is read whatever it skips and ignores.
        """
        bases = tuple(dict.fromkeys((os.path.normpath(root), os.path.realpath(root))))
        for entry in self.files:
            absolute = self._absolute(entry)
            base = next((candidate for candidate in bases if _is_under(absolute, candidate)), None)
            if base is None:
                continue
            if view is TreeView.TRACKED and not entry.tracked:
                continue
            named_outright = absolute == base
            if not named_outright and skip is not None and _skipped_below(base, absolute, skip):
                continue
            if (
                view is TreeView.UNIGNORED
                and entry.ignored
                and not named_outright
                and not self._root_defeats_ignore(base)
            ):
                continue
            if is_exempt is not None and is_exempt(absolute):
                continue
            return entry.pattern
        return None

    def glob_matches(self, token: str, bases: Sequence[str] = ()) -> str | None:
        """The protected glob of the first indexed file the shell glob ``token`` matches.

        A relative ``token`` is read from each of ``bases``. Matching follows the
        shell: ``*`` and ``?`` stay inside one path component and never match a
        leading dot, and ``**`` spans directories. A glob that starts, below the
        directory it is read from, with a wildcard-only component and has another
        after it (``*/*``, ``**/*``, ``*/dir/*``) names no place: reading whatever
        sits that deep is not reading a protected file, and judging it would deny
        ``ls */*/*`` in every tree that has one visible protected file. A glob
        anchored by a literal directory (``dir/*``, ``dir/**/*``) or ending in one
        wildcard (``*``) names a place and is judged.
        """
        if not token or "\0" in token:
            return None
        absolute_tokens = (
            [os.path.normpath(token)]
            if token.startswith("/")
            else [os.path.normpath(Path(base) / token) for base in dict.fromkeys(bases)]
        )
        for absolute_token in absolute_tokens:
            if self._names_no_place(token, absolute_token):
                continue
            glob_parts = _components(absolute_token)
            for entry in self.files:
                for root in self._roots():
                    if _segments_match(_components(f"{root}/{entry.relpath}"), glob_parts):
                        return entry.pattern
        return None

    def _names_no_place(self, token: str, absolute_token: str) -> bool:
        """Is the glob, read relative to the project, wildcard-only from its first component?"""
        below_project = (
            _relative_to(absolute_token, self._roots()) if token.startswith("/") else None
        )
        components = _components(token if below_project is None else below_project)
        wildcards = [bool(_WILDCARD_ONLY.fullmatch(part)) for part in components]
        return bool(wildcards) and wildcards[0] and sum(wildcards) >= _NAMELESS_DEPTH

    def _root_defeats_ignore(self, base: str) -> bool:
        """Does naming ``base`` outright make an ignore-honouring tool read ignored files?

        It does when ``base`` is itself ignored by git, or sits under a hidden
        directory of the project: the tool is told to search it, and what it skips
        is judged only below it.
        """
        relative = _relative_to(base, self._roots())
        if relative is None:
            return False
        if any(part.startswith(_HIDDEN_PREFIX) for part in relative.split("/") if part):
            return True
        result = run_git(Path(self.project_root), "check-ignore", "-q", "--", base)
        return result.returncode == 0


def _components(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _is_under(path: str, base: str) -> bool:
    """Is ``path`` the directory or file ``base``, or inside it?"""
    return path == base or path.startswith(base.rstrip("/") + "/")


def _relative_to(path: str, roots: Sequence[str]) -> str | None:
    for root in roots:
        if _is_under(path, root):
            return path[len(root) :].lstrip("/")
    return None


def _skipped_below(base: str, absolute: str, skip: SkipHook) -> bool:
    """Is ``absolute`` skipped at any component between ``base`` and itself?"""
    parts = absolute[len(base) :].strip("/").split("/")
    current = base
    for position, part in enumerate(parts):
        current = f"{current.rstrip('/')}/{part}"
        if skip(current, position < len(parts) - 1):
            return True
    return False


def _segments_match(path: Sequence[str], glob: Sequence[str]) -> bool:
    """Do the components of ``path`` match those of ``glob``, as the shell would?"""
    if not glob:
        return not path
    head, rest = glob[0], glob[1:]
    if head == _RECURSIVE_COMPONENT:
        return any(_segments_match(path[skip:], rest) for skip in range(len(path) + 1))
    if not path:
        return False
    name = path[0]
    if name.startswith(_HIDDEN_PREFIX) and not head.startswith(_HIDDEN_PREFIX):
        return False
    return fnmatch.fnmatchcase(name, head) and _segments_match(path[1:], rest)


# ── Build and cache ─────────────────────────────────────────────────────────

_Key = tuple[str, tuple[str, ...]]

_lock = threading.Lock()
_cache: OrderedDict[_Key, ProtectedFileIndex] = OrderedDict()
_building: dict[_Key, threading.Thread] = {}
_failed_at: dict[_Key, float] = {}


def _key(project_root: Path | str, patterns: tuple[str, ...]) -> _Key:
    return (os.path.normpath(str(project_root)), tuple(patterns))


def build_index(project_root: Path, patterns: tuple[str, ...]) -> ProtectedFileIndex | None:
    """Index the protected files of the repository at ``project_root``.

    ``None`` means git could not answer (not a repository, or no git): there is no
    index, which is different from an index that lists nothing.

    Git is asked only for the paths a protected glob can select
    (:func:`~claude_code_hooks_daemon.utils.protected_pathspecs.git_pathspecs`):
    listing every ignored file of a working copy that keeps virtualenvs and
    worktrees under an ignored directory took longer than the build's timeout, so
    the index never built (N355). A pattern set no pathspec can express soundly
    is listed in full.
    """
    from claude_code_hooks_daemon.utils.git_file_states import scan_git_file_states
    from claude_code_hooks_daemon.utils.protected_pathspecs import git_pathspecs

    states = scan_git_file_states(
        project_root,
        timeout=Timeout.INDEX_BUILD_GIT,
        pathspecs=git_pathspecs(patterns, project_root),
    )
    if states is None:
        return None
    return index_from_states(project_root, patterns, states)


def index_from_states(
    project_root: Path, patterns: tuple[str, ...], states: GitFileStates
) -> ProtectedFileIndex:
    """The index of an already-made git scan; the SessionStart sweep passes its own."""
    from claude_code_hooks_daemon.utils import secret_file_matching as sfm

    files = []
    for relpath in states.protected_relpaths(project_root, patterns):
        pattern = sfm.protecting_pattern(str(project_root / relpath), patterns)
        if pattern is not None:
            files.append(
                IndexedFile(
                    relpath=relpath,
                    pattern=pattern,
                    tracked=relpath in states.tracked,
                    ignored=states.is_ignored(relpath),
                )
            )
    return ProtectedFileIndex(
        project_root=os.path.normpath(str(project_root)),
        patterns=tuple(patterns),
        files=tuple(files),
    )


def remember(index: ProtectedFileIndex) -> None:
    """Serve ``index`` from now on for its project and patterns."""
    key = _key(index.project_root, index.patterns)
    with _lock:
        _cache[key] = index
        _cache.move_to_end(key)
        while len(_cache) > MAX_CACHED_INDEXES:
            _cache.popitem(last=False)
        _failed_at.pop(key, None)


def cached_index(project_root: Path | str, patterns: tuple[str, ...]) -> ProtectedFileIndex | None:
    """The index held for these, without ever starting a build."""
    with _lock:
        return _cache.get(_key(project_root, patterns))


def index_for(project_root: Path | str, patterns: tuple[str, ...]) -> ProtectedFileIndex | None:
    """The index for these, or None when there is none yet; never waits for a build.

    A missing index starts a background build, and a stale one is served while a
    fresh one is built. A build that fails is not retried until the refresh
    interval has passed, so a project that is not a git repository costs nothing
    after the first call.
    """
    key = _key(project_root, patterns)
    now = time.monotonic()
    with _lock:
        held = _cache.get(key)
        stale = held is None or now - held.built_at > REFRESH_AFTER_SECONDS
        failed_recently = (
            now - _failed_at.get(key, -RETRY_AFTER_FAILURE_SECONDS) < RETRY_AFTER_FAILURE_SECONDS
        )
        if not stale or key in _building or failed_recently:
            return held
        thread = threading.Thread(
            target=_build_and_remember,
            args=(key, Path(key[0]), key[1]),
            name="protected-file-index-build",
            daemon=True,
        )
        _building[key] = thread
    thread.start()
    return held


def prewarm(project_root: Path | str, patterns: tuple[str, ...]) -> None:
    """Start the background build now, so the first search after a restart can be judged.

    Cheap and non-blocking: it is :func:`index_for` with the answer discarded.
    """
    index_for(project_root, patterns)


def _build_and_remember(key: _Key, project_root: Path, patterns: tuple[str, ...]) -> None:
    try:
        built = build_index(project_root, patterns)
        if built is None:
            logger.warning(
                "protected-file index for %s could not be built (git gave no answer); "
                "recursive searches are allowed with an advisory, retrying in %gs",
                project_root,
                RETRY_AFTER_FAILURE_SECONDS,
            )
            with _lock:
                _failed_at[key] = time.monotonic()
        else:
            remember(built)
    except Exception as exc:
        # A thread's uncaught exception goes to stderr, which nothing reads.
        logger.warning(
            "protected-file index for %s could not be built: %s; retrying in %gs",
            project_root,
            type(exc).__name__,
            RETRY_AFTER_FAILURE_SECONDS,
        )
        with _lock:
            _failed_at[key] = time.monotonic()
    finally:
        with _lock:
            _building.pop(key, None)


def wait_for_builds(timeout: float) -> None:
    """Block until the builds in flight finish; for tests and for shutdown."""
    with _lock:
        threads = list(_building.values())
    for thread in threads:
        thread.join(timeout=timeout)


def reset_index_cache() -> None:
    """Forget every index and failure; for tests."""
    wait_for_builds(timeout=Timeout.INDEX_BUILD_WAIT)
    with _lock:
        _cache.clear()
        _failed_at.clear()
