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

import logging
import os
import re
import string
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.load_scaling import scaled_timeout
from claude_code_hooks_daemon.utils.path_predicates import path_is_dir
from claude_code_hooks_daemon.utils.resolution_failure import fails_closed

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

#: POSIX bracket classes (``[[:alpha:]]``) as the characters they hold in the C locale.
_POSIX_CLASSES: Final[dict[str, str]] = {
    "alpha": string.ascii_letters,
    "digit": string.digits,
    "alnum": string.ascii_letters + string.digits,
    "upper": string.ascii_uppercase,
    "lower": string.ascii_lowercase,
    "space": " \t\n\r\f\v",
    "blank": " \t",
    "punct": string.punctuation,
    "print": " " + string.ascii_letters + string.digits + string.punctuation,
    "graph": string.ascii_letters + string.digits + string.punctuation,
    "cntrl": "".join(chr(code) for code in (*range(32), 127)),
    "xdigit": string.hexdigits,
}
# bash negates a bracket expression with ``!`` or ``^``; fnmatch knows only ``!``.
_BRACKET_NEGATIONS: Final[str] = "!^"
_GLOB_CHARACTERS: Final[str] = "*?[\\"

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

    def _leads_out(self, lexical: str, real: str) -> bool:
        """Does a link turn ``lexical``, a path in the project, into ``real``, one outside it?

        A path outside the project as spelled is judged as before: the index never
        claimed to cover it, and denying every such path would deny ordinary reads.
        """
        if real == lexical or not any(_is_under(lexical, root) for root in self._roots()):
            return False
        return not _is_under(real, os.path.realpath(self.project_root))

    def _link_out_directory(self, token: str, absolute_token: str) -> str | None:
        """The directory a glob spells before its first wildcard, when a link leads it out.

        Plan 00614: ``dlink/*`` reads what ``dlink`` points at. :func:`_glob_parts`
        already matches the glob with that directory resolved, but a target outside
        the project holds files this index never listed, so the glob is not vouched
        for. Only a glob whose own text names a directory costs a filesystem call.
        """
        directory = _literal_directory(token, absolute_token)
        if directory is None:
            return None
        return directory if self._leads_out(directory, os.path.realpath(directory)) else None

    def _wildcard_links(
        self, token: str, absolute_token: str, *, include_last: bool
    ) -> list[tuple[str, str, bool]]:
        """``(link, glob read through it, leads out)`` for each directory link the first wildcard component names.

        Review F2: ``dl*/*`` reads what ``dlink`` points at, but no literal directory
        precedes the wildcard for :meth:`_link_out_directory` to resolve. The literal
        parent is listed once and each link matching that component is judged. A
        glob whose first component is wildcards only (``*/*``) names no place and is
        not expanded; nor is a last component, unless ``include_last`` (a recursive
        reader descends into it).
        """
        below = _relative_to(absolute_token, self._roots()) if token.startswith("/") else None
        spelled = _components(token if below is None else below)
        if not spelled or _WILDCARD_ONLY.fullmatch(spelled[0]):
            return []
        parts = _components(absolute_token)
        first = next((depth for depth, part in enumerate(parts) if _has_glob_syntax(part)), None)
        if first is None or (first == len(parts) - 1 and not include_last):
            return []
        # Resolved as :func:`_glob_parts` resolves the literal prefix.
        parent = os.path.realpath("/" + "/".join(parts[:first]))
        # One the shell cannot stat it cannot list either, so it expands no link.
        if not path_is_dir(parent, unreadable_means=False):
            return []
        try:
            with os.scandir(parent) as listing:
                names = [entry.name for entry in listing if entry.is_symlink()]
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="a directory that cannot be listed cannot be glob-expanded by the shell either, so the wildcard reads no link in it",
                level=logging.DEBUG,
            )
            return []
        hits: list[tuple[str, str, bool]] = []
        for name in names:
            if not _segments_match([name], [parts[first]]):
                continue
            link = f"{parent.rstrip('/')}/{name}"
            real = os.path.realpath(link)
            # A target that cannot be stat-ed may be a directory: judged as one.
            if not path_is_dir(real, unreadable_means=True):
                continue
            through = "/".join(
                [*(_escape_glob(part) for part in _components(real)), *parts[first + 1 :]]
            )
            hits.append((link, "/" + through, self._leads_out(link, real)))
        return hits

    def _glob_link_out(self, token: str, absolute_token: str, *, include_last: bool) -> str | None:
        """The link out of the project a glob reads through, by its literal or its wildcard directory."""
        literal = self._link_out_directory(token, absolute_token)
        if literal is not None:
            return literal
        hits = self._wildcard_links(token, absolute_token, include_last=include_last)
        return next((link for link, _through, leads_out in hits if leads_out), None)

    @fails_closed
    def link_out_of(self, token: str, bases: Sequence[str] = ()) -> str | None:
        """The link to a directory outside the project that reading ``token`` goes through, else None.

        ``token`` is a path, a search root or a glob, placed from each of ``bases``
        when relative. The same test the decisions above use: a deny message names
        this link as its cause (review F4).
        """
        if not token or "\0" in token:
            return None
        for absolute_token in _absolute_tokens(token, bases):
            if _has_glob_syntax(token):
                found = self._glob_link_out(token, absolute_token, include_last=True)
                if found is not None:
                    return found
                continue
            real = os.path.realpath(absolute_token)
            if self._leads_out(absolute_token, real) and path_is_dir(real, unreadable_means=True):
                return absolute_token
        return None

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

        A ``root`` inside the project that is a link to a directory outside it holds
        files this index never listed (another checkout, Plan 00614), so the search
        is not vouched for: the first pattern is answered, as for a protected file.
        """
        lexical = os.path.normpath(root)
        real = _realpath_or_lexical(root)
        # An unreadable target is not vouched for either: it fails closed.
        if self._leads_out(lexical, real) and path_is_dir(real, unreadable_means=True):
            return self.patterns[0] if self.patterns else None
        bases = tuple(dict.fromkeys((lexical, real)))
        # Whether naming a base defeats git's ignore depends on the base alone, so
        # each is asked of git at most once however many ignored files lie below it.
        defeats_ignore: dict[str, bool] = {}
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
            if view is TreeView.UNIGNORED and entry.ignored and not named_outright:
                if base not in defeats_ignore:
                    defeats_ignore[base] = self._root_defeats_ignore(base)
                if not defeats_ignore[base]:
                    continue
            if is_exempt is not None and is_exempt(absolute):
                continue
            return entry.pattern
        return None

    @fails_closed
    def glob_matches(
        self, token: str, bases: Sequence[str] = (), *, default_expansion: bool = False
    ) -> str | None:
        """The protected glob of the first indexed file the shell glob ``token`` matches.

        A relative ``token`` is read from each of ``bases``. Matching follows the
        shell: ``*`` and ``?`` stay inside one path component and never match a
        leading dot, and ``**`` spans directories. ``default_expansion`` says the
        shell runs with ``globstar`` and ``dotglob`` off (bash's defaults), where a
        ``**`` component is read like ``*``: one level, no dot names. A glob that starts, below the
        directory it is read from, with a wildcard-only component and has another
        after it (``*/*``, ``**/*``, ``*/dir/*``) names no place: reading whatever
        sits that deep is not reading a protected file, and judging it would deny
        ``ls */*/*`` in every tree that has one visible protected file. A glob
        anchored by a literal directory (``dir/*``, ``dir/**/*``) or ending in one
        wildcard (``*``) names a place and is judged.

        A ``token`` ending in ``/`` expands to directories only, so it never
        names a file at its own level and matches none here. A tool that
        recurses into those directories is judged over each of them by
        :meth:`find_under`, as for a literal directory argument.
        """
        if not token or "\0" in token or token.endswith("/"):
            return None
        for absolute_token in _absolute_tokens(token, bases):
            if self._link_out_directory(token, absolute_token) is not None:
                return self.patterns[0] if self.patterns else None
            if self._names_no_place(token, absolute_token):
                continue
            readings = [absolute_token]
            for _link, through, leads_out in self._wildcard_links(
                token, absolute_token, include_last=False
            ):
                if leads_out:
                    return self.patterns[0] if self.patterns else None
                readings.append(through)
            for reading in readings:
                glob_parts, _ = _glob_parts(reading, default_expansion)
                for entry in self.files:
                    for root in self._roots():
                        if _segments_match(_components(f"{root}/{entry.relpath}"), glob_parts):
                            return entry.pattern
        return None

    @fails_closed
    def directories_matching(
        self, token: str, bases: Sequence[str] = (), *, default_expansion: bool = False
    ) -> tuple[str, ...]:
        """The directories holding a protected file that the shell glob ``token`` names.

        ``token`` is a glob a recursive reader searches, with or without a trailing
        ``/``. Each directory returned is an ancestor directory of an indexed file, matched component by component
        with the matcher :meth:`glob_matches` uses (so ``*`` skips dot names and
        ``default_expansion`` reads ``**`` like ``*``), but never against the file
        itself. A search that recurses into those directories reads the file, exactly
        as it does for a directory named literally. A glob that names no place
        (``*/``) is still resolved: the tool reads whatever lies below.
        """
        if not token or "\0" in token:
            return ()
        found: dict[str, None] = {}
        for absolute_token in _absolute_tokens(token, bases):
            link_out = self._glob_link_out(token, absolute_token, include_last=True)
            if link_out is not None:
                # The link's own directory: searching it is judged by find_under,
                # which does not vouch for a link out of the project.
                found[link_out] = None
                continue
            glob_parts, literal = _glob_parts(absolute_token, default_expansion)
            # A directory read through a wildcard link is reported as the link spells it.
            throughs = [
                (_glob_parts(through, default_expansion)[0], os.path.realpath(link), link)
                for link, through, _out in self._wildcard_links(
                    token, absolute_token, include_last=True
                )
            ]
            for entry in self.files:
                for root in self._roots():
                    parts = _components(f"{root}/{entry.relpath}")
                    for depth in range(1, len(parts)):
                        directory = "/" + "/".join(parts[:depth])
                        if _segments_match(parts[:depth], glob_parts):
                            found[directory] = None
                        for through_parts, real, link in throughs:
                            if _segments_match(parts[:depth], through_parts):
                                found[link + directory[len(real) :]] = None
            if literal == len(glob_parts) - 1:
                for link in self._matching_symlinked_directories(glob_parts):
                    found[link] = None
        return tuple(found)

    def _matching_symlinked_directories(self, glob_parts: Sequence[str]) -> list[str]:
        """Symlinks to a directory holding a protected file that the glob's last component names.

        The index holds real paths, so a symlink to a protected directory is no
        ancestor of any indexed file. The shell still expands the glob to it, and a
        recursive reader follows it as it does a literal ``link/``. Only the one
        directory the glob's literal parent names is listed (``os.scandir``, a single
        level): a parent that is itself a glob is not expanded, so a symlink matched
        only below a wildcard directory stays unjudged, which keeps the cost of a
        call independent of the size of the tree.
        """
        last = glob_parts[-1]
        if last == _RECURSIVE_COMPONENT:
            return []
        # The literal parent is already a real path (:func:`_glob_parts`), its glob characters escaped.
        parent = re.sub(r"\\(.)", r"\1", "/" + "/".join(glob_parts[:-1]))
        real_files = [f"{root}/{entry.relpath}" for entry in self.files for root in self._roots()]
        try:
            with os.scandir(parent) as listing:
                names = [item.name for item in listing if item.is_symlink()]
        except OSError:
            return []
        links: list[str] = []
        for name in names:
            if not _segments_match([name], [last]):
                continue
            link = f"{parent.rstrip('/')}/{name}"
            target = os.path.realpath(link)
            if path_is_dir(target, unreadable_means=True) and any(
                _is_under(path, target) for path in real_files
            ):
                links.append(link)
        return links

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


def _realpath_or_lexical(path: str) -> str:
    """``realpath(path)``; a path the filesystem cannot encode cannot exist, and is its own."""
    try:
        return os.path.realpath(path)
    except ValueError as exc:
        log_and_continue(
            logger,
            exc,
            reason="a path that cannot be encoded for the filesystem names nothing on disk, so no link moves it",
            level=logging.DEBUG,
        )
        return os.path.normpath(path)


def _components(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _literal_directory(token: str, absolute_token: str) -> str | None:
    """The directory ``absolute_token`` spells before its first glob component.

    None unless ``token`` itself names a directory before its first wildcard
    (``dlink/*``, ``/abs/*``): a bare ``*.py`` is read from a cwd that the
    caller placed, not one the glob spells.
    """
    wildcards = [token.find(char) for char in _GLOB_CHARACTERS if char in token]
    if not wildcards or "/" not in token[: min(wildcards)]:
        return None
    parts = absolute_token.split("/")
    literal = next(
        (depth for depth, part in enumerate(parts) if any(c in part for c in _GLOB_CHARACTERS)),
        len(parts),
    )
    return "/".join(parts[:literal]) or "/"


def _absolute_tokens(token: str, bases: Sequence[str]) -> list[str]:
    """``token`` placed under each base (or as it is, when absolute), normalised."""
    if token.startswith("/"):
        return [os.path.normpath(token)]
    return [os.path.normpath(Path(base) / token) for base in dict.fromkeys(bases)]


def _glob_parts(absolute_token: str, default_expansion: bool) -> tuple[list[str], int]:
    """The glob's components and how many leading ones are the resolved literal prefix.

    The index holds real paths, so the literal directories before the first wildcard
    component are replaced by their ``realpath`` (a symlinked parent such as
    ``up/di?/`` is then matched where the shell actually reads). A resolved name that
    itself holds glob characters is escaped to stay literal. Under bash's defaults a
    ``**`` component is read like ``*``.
    """
    parts = _components(absolute_token)
    literal = 0
    while literal < len(parts) and not _has_glob_syntax(parts[literal]):
        literal += 1
    if literal:
        resolved = _components(os.path.realpath("/" + "/".join(parts[:literal])))
        parts = [_escape_glob(part) for part in resolved] + parts[literal:]
        literal = len(resolved)
    if default_expansion:
        parts = ["*" if part == _RECURSIVE_COMPONENT else part for part in parts]
    return parts, literal


def _escape_glob(component: str) -> str:
    return "".join(f"\\{char}" if char in _GLOB_CHARACTERS else char for char in component)


def _has_glob_syntax(component: str) -> bool:
    return any(char in component for char in _GLOB_CHARACTERS)


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
    return _component_pattern(head).fullmatch(name) is not None and _segments_match(path[1:], rest)


@lru_cache(maxsize=1024)
def _component_pattern(glob: str) -> re.Pattern[str]:
    """One glob component as a regex, read as bash reads it.

    ``*`` and ``?`` match within the component, ``[!x]`` and ``[^x]`` both negate,
    and ``[[:alpha:]]`` and the other POSIX classes hold their characters, which
    ``fnmatch`` does not know. A ``[`` with no closing ``]`` is a literal.

    Like CPython's ``fnmatch``, each ``*`` that has another ``*`` after it is
    emitted with the fixed-length run that follows it as one atomic group
    (``(?>.*?run)``): the leftmost match of a fixed-length run leaves the most
    input for the rest, so nothing needs to backtrack into it. Only the final
    ``*`` stays a plain ``.*``, so matching is linear in the number of stars.
    """
    segments: list[list[str]] = [[]]
    position = 0
    while position < len(glob):
        char = glob[position]
        position += 1
        if char == "*":
            segments.append([])
        elif char == "?":
            segments[-1].append(".")
        elif char == "\\" and position < len(glob):
            segments[-1].append(re.escape(glob[position]))
            position += 1
        elif char == "[":
            parsed = _bracket_expression(glob, position)
            if parsed is None:
                segments[-1].append(re.escape(char))
            else:
                segments[-1].append(parsed[0])
                position = parsed[1]
        else:
            segments[-1].append(re.escape(char))
    out = ["".join(segments[0])]
    for run in segments[1:-1]:
        if run:
            out.append(f"(?>.*?{''.join(run)})")
    if len(segments) > 1:
        out.append(".*" + "".join(segments[-1]))
    return re.compile("".join(out), re.DOTALL)


def _bracket_expression(glob: str, start: int) -> tuple[str, int] | None:
    """The regex class for the bracket expression opened just before ``start``.

    Returns it with the position after its ``]``, or None when it never closes.
    """
    position = start
    negate = position < len(glob) and glob[position] in _BRACKET_NEGATIONS
    if negate:
        position += 1
    members: list[str] = []
    first = True
    while position < len(glob):
        char = glob[position]
        if char == "]" and not first:
            if not members:  # only reversed ranges: the set holds nothing (or, negated, anything)
                return ("." if negate else "(?!)"), position + 1
            return f"[{'^' if negate else ''}{''.join(members)}]", position + 1
        first = False
        if glob.startswith("[:", position):
            close = glob.find(":]", position + 2)
            name = glob[position + 2 : close] if close != -1 else ""
            if name in _POSIX_CLASSES:
                members.append(re.escape(_POSIX_CLASSES[name]))
                position = close + 2
                continue
        if char == "\\" and position + 1 < len(glob):
            position += 1
            char = glob[position]
        if glob.startswith("-", position + 1) and glob[position + 2 : position + 3] not in (
            "",
            "]",
        ):
            high = glob[position + 2]
            if char <= high:  # a reversed range holds nothing, as in bash
                members.append(f"{re.escape(char)}-{re.escape(high)}")
            position += 3
            continue
        members.append(re.escape(char))
        position += 1
    return None


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
        timeout=scaled_timeout(Timeout.INDEX_BUILD_GIT, Timeout.INDEX_BUILD_GIT_MAX),
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
    fresh one is built. A build that fails is not retried until
    :data:`RETRY_AFTER_FAILURE_SECONDS` has passed (a short wait, so a build that
    only timed out is tried again soon, not after the refresh interval), so a
    project that is not a git repository costs one attempt per that wait.
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
