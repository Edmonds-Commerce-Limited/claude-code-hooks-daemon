"""Does a recursive search under a root read a protected file? (ledger 00483 N130, 00474 N348)

A recursive search reads every file of its tree without naming one, so a guard
has to examine the tree. The one rule here: an unfinished examination is never
answered as "no". :func:`find_protected_in_tree` returns None only when it
examined the whole view; past :data:`TREE_SCAN_MAX_ENTRIES` entries it raises
``TooManyToEnumerateError`` and past its deadline ``TimeoutError``, which the
guards deny as an incomplete scan.

What the tree *is* depends on the tool (:class:`TreeView`), and asking git for
it wherever the tool follows git's rules keeps the cost near the size of the
non-ignored tree rather than of everything on disk (node_modules, virtualenvs,
sibling worktrees):

- ``ALL`` (``grep -r``, ``ack``, ``rg --no-ignore``): every entry, by an
  iterative ``os.scandir`` walk with a literal screen in front of the glob
  matcher.
- ``TRACKED`` (``git grep``): ``git ls-files --cached``, untruncated.
- ``UNIGNORED`` (``rg``, ``ag`` defaults): ``git ls-files -co --exclude-standard``,
  with the tool's own skips applied, and a walk where git cannot answer.
"""

import logging
import os
import posixpath
import stat
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from subprocess import CompletedProcess
from typing import Final

from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.git_repo import GIT_TIMED_OUT, run_git
from claude_code_hooks_daemon.utils.path_exclusion import (
    first_matching_glob,
    literal_screen,
    resolve_project_root,
)
from claude_code_hooks_daemon.utils.shell_expansion import TooManyToEnumerateError

logger = logging.getLogger(__name__)

#: Entries one scan may visit (directories included) before it fails closed.
#: Measured: the screened walk costs 1-5 microseconds an entry warm, so this is
#: about 0.25-1.2 s of the 5 s scan deadline, which stays as the backstop.
TREE_SCAN_MAX_ENTRIES: Final[int] = 250_000

#: The deadline is read once per this many entries; a clock read per entry would
#: cost more than the screen.
_DEADLINE_STRIDE: Final[int] = 1024


class TreeView(StrEnum):
    """Which files a search tool reads under its root."""

    ALL = "all"
    UNIGNORED = "unignored"
    TRACKED = "tracked"


SkipHook = Callable[[str, bool], bool]
ExemptHook = Callable[[str], bool]


class _Budget:
    """The entries and time one scan may spend; spending past either raises."""

    def __init__(self, root: str, max_entries: int, deadline: float | None) -> None:
        self._root = root
        self._max_entries = max_entries
        self._deadline = deadline
        self._used = 0

    def spend(self, count: int = 1) -> None:
        """Account for ``count`` more entries visited."""
        before = self._used
        self._used += count
        if self._used > self._max_entries:
            raise TooManyToEnumerateError(
                f"a recursive search under {self._root!r} visits more than "
                f"{self._max_entries} entries",
                limit=self._max_entries,
                tree_walk=True,
            )
        if self._deadline is not None and (
            before == 0 or before // _DEADLINE_STRIDE != self._used // _DEADLINE_STRIDE
        ):
            self.remaining()

    def remaining(self) -> float | None:
        """Seconds left to the deadline (None when there is none); raises once it has passed."""
        if self._deadline is None:
            return None
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(f"the scan of {self._root!r} passed its deadline")
        return left


def find_protected_in_tree(
    root: str,
    patterns: tuple[str, ...],
    *,
    view: TreeView,
    skip: SkipHook | None = None,
    is_exempt: ExemptHook | None = None,
    deadline: float | None = None,
    max_entries: int | None = None,
) -> str | None:
    """First protected glob matched under ``root`` as ``view`` reads it, else None.

    None means the whole view was examined and nothing matched. Raises
    ``TooManyToEnumerateError`` past ``max_entries`` (default
    :data:`TREE_SCAN_MAX_ENTRIES`, read at call time) and ``TimeoutError`` past
    ``deadline`` (a ``time.monotonic()`` instant); neither is ever answered
    as None.

    ``skip(path, is_dir)`` drops an entry the searching tool would not read (a
    hidden entry, an excluded directory); a skipped directory is not descended
    into. ``is_exempt`` skips a protected file the caller has confirmed safe to
    read (encrypted at rest), so a tree holding only such files is not flagged
    while a plaintext one beside them still is.
    """
    if not patterns:
        return None
    if view is not TreeView.TRACKED and not Path(root).is_dir():
        return None
    budget = _Budget(root, TREE_SCAN_MAX_ENTRIES if max_entries is None else max_entries, deadline)
    if view is TreeView.TRACKED:
        return _tracked(root, patterns, skip, is_exempt, budget)
    if view is TreeView.UNIGNORED:
        return _unignored(root, patterns, skip, is_exempt, budget)
    return _walk(root, patterns, skip, is_exempt, budget)


def directory_contains_protected(
    directory: str,
    patterns: tuple[str, ...],
    max_entries: int | None = None,
    is_exempt: ExemptHook | None = None,
    skip: SkipHook | None = None,
    deadline: float | None = None,
) -> str | None:
    """:func:`find_protected_in_tree` over the ``ALL`` view, for a caller wanting only the answer."""
    return find_protected_in_tree(
        directory,
        patterns,
        view=TreeView.ALL,
        skip=skip,
        is_exempt=is_exempt,
        deadline=deadline,
        max_entries=max_entries,
    )


def _walk(
    root: str,
    patterns: tuple[str, ...],
    skip: SkipHook | None,
    is_exempt: ExemptHook | None,
    budget: _Budget,
) -> str | None:
    """Every entry under ``root``, symlinked directories not followed (as ``grep -r``)."""
    project_root = resolve_project_root()
    screen = literal_screen(patterns)
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            listing = os.scandir(directory)
        except OSError as exc:
            # A directory the walk cannot list is one the search cannot read either.
            logger.debug("protected_tree_scan: cannot list a directory (%s)", type(exc).__name__)
            continue
        with listing:
            for entry in listing:
                budget.spend()
                path = entry.path
                is_dir = entry.is_dir()
                if skip is not None and skip(path, is_dir):
                    continue
                if is_dir:
                    if not entry.is_symlink():
                        pending.append(path)
                    continue
                if screen is not None and not screen(path):
                    continue
                matched = first_matching_glob(path, patterns, project_root=project_root)
                if matched is None or (is_exempt is not None and is_exempt(path)):
                    continue
                return matched
    return None


def _git(directory: str, budget: _Budget, *args: str) -> CompletedProcess[str]:
    """``git -C directory args``, bounded by the scan deadline; a timeout raises."""
    timeout = budget.remaining()
    if timeout is None:
        result = run_git(Path(directory), *args)
    else:
        result = run_git(Path(directory), *args, timeout=timeout)
    if result.returncode == GIT_TIMED_OUT:
        raise TimeoutError(f"git did not answer for {directory!r} within the scan deadline")
    return result


def _listing(directory: str, budget: _Budget, *args: str) -> list[str] | None:
    """Names ``git ls-files`` lists (relative to ``directory``), or None when git cannot answer."""
    result = _git(directory, budget, "ls-files", "-z", *args)
    if result.returncode != 0:
        return None
    names = [name for name in result.stdout.split("\0") if name]
    budget.spend(len(names))
    return names


def _is_skipped(base: str, name: str, skip: SkipHook, decided: dict[str, bool]) -> bool:
    """Is the listed ``name`` (relative to ``base``) skipped at any of its path components?"""
    parts = name.rstrip("/").split("/")
    current = base
    for index, part in enumerate(parts):
        current = posixpath.join(current, part)
        is_dir = index < len(parts) - 1 or name.endswith("/")
        if not is_dir:
            return skip(current, False)
        if current not in decided:
            decided[current] = skip(current, True)
        if decided[current]:
            return True
    return False


def _first_protected(
    paths: list[str], patterns: tuple[str, ...], is_exempt: ExemptHook | None
) -> str | None:
    """First protected glob among listed ``paths``, past any the caller confirmed safe."""
    for path in sfm.protected_among(paths, patterns):
        if is_exempt is not None and is_exempt(path):
            continue
        pattern = sfm.protecting_pattern(path, patterns)
        if pattern is not None:
            return pattern
    return None


def _tracked(
    root: str,
    patterns: tuple[str, ...],
    skip: SkipHook | None,
    is_exempt: ExemptHook | None,
    budget: _Budget,
) -> str | None:
    """Protected files in the index under ``root``: what ``git grep`` reads.

    Outside a work tree git cannot answer, and neither can ``git grep``.
    """
    base, spec = (root, ".") if Path(root).is_dir() else posixpath.split(root)
    names = _listing(base, budget, "--cached", "--", spec)
    if names is None:
        return None
    decided: dict[str, bool] = {}
    paths = [
        posixpath.join(base, name)
        for name in names
        if skip is None or not _is_skipped(base, name, skip, decided)
    ]
    return _first_protected(paths, patterns, is_exempt)


def _unignored(
    root: str,
    patterns: tuple[str, ...],
    skip: SkipHook | None,
    is_exempt: ExemptHook | None,
    budget: _Budget,
) -> str | None:
    """Protected files git does not ignore under ``root``: what ``rg`` and ``ag`` read.

    The walk answers instead when git cannot (outside a repository), and when
    the root is one the tool reads although git's listing leaves it out: an
    ignored root, or one under a hidden directory, named outright.
    """
    if _root_is_read_despite_ignore(root, budget):
        return _walk(root, patterns, skip, is_exempt, budget)
    names = _listing(root, budget, "-co", "--exclude-standard", "--", ".")
    if names is None:
        return _walk(root, patterns, skip, _also_git_ignored(is_exempt), budget)
    decided: dict[str, bool] = {}
    files: list[str] = []
    nested: list[str] = []
    for name in names:
        if skip is not None and _is_skipped(root, name, skip, decided):
            continue
        path = posixpath.join(root, name.rstrip("/"))
        if name.endswith("/") or _is_real_directory(path):
            nested.append(path)
        else:
            files.append(path)
    found = _first_protected(files, patterns, is_exempt)
    if found is not None:
        return found
    # A nested repository (listed as `dir/`) or a submodule (a gitlink) is read
    # by the tool although git's listing stops at its door.
    for directory in nested:
        found = _walk(directory, patterns, skip, _also_git_ignored(is_exempt), budget)
        if found is not None:
            return found
    return None


def _is_real_directory(path: str) -> bool:
    """A directory, not a symlink to one (`rg` does not follow links); a vanished path is not."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _root_is_read_despite_ignore(root: str, budget: _Budget) -> bool:
    """Is ``root`` ignored by git, or under a hidden directory of its repository?

    Naming such a root outright makes the tool read it, while git's listing of
    non-ignored files has nothing under it.
    """
    top = _git(root, budget, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return False
    try:
        relative = Path(os.path.realpath(root)).relative_to(os.path.realpath(top.stdout.strip()))
    except ValueError:
        return True  # a root git places outside its own toplevel is walked, not trusted.
    if any(part.startswith(".") for part in relative.parts):
        return True
    return _git(root, budget, "check-ignore", "-q", "--", os.path.realpath(root)).returncode == 0


def _also_git_ignored(is_exempt: ExemptHook | None) -> ExemptHook:
    """``is_exempt`` widened to a file git ignores, which an ignore-aware tool never opens.

    Only a file ``git check-ignore`` reports counts: outside a repository, or on
    any git failure, the file is read as before (fail closed).
    """

    def exempt(path: str) -> bool:
        if is_exempt is not None and is_exempt(path):
            return True
        result = run_git(Path(posixpath.dirname(path)), "check-ignore", "-q", "--", path)
        return result.returncode == 0

    return exempt
