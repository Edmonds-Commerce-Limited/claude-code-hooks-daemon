"""Which files git tracks, and which an ignore rule matches (Plan 00459).

``secret_file_hygiene_checker`` and ``gitignore_safety_checker`` both judge
protected files by these states, so they read them from ONE scan here rather
than each running its own ``git ls-files`` variants.

Git-native, not a filesystem walk (Plan 00272 code review): a capped walk can
exhaust its cap in an unrelated subtree and then report the tree clean, while
``git ls-files`` answers each state directly from the index and the exclude
rules. Git also evaluates negations (``!path``) and rule order exactly as it
will when the file is added, which a hand-rolled gitignore matcher would not.
"""

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.secret_file_matching import protected_among


@dataclass(frozen=True)
class GitFileStates:
    """Repository-relative paths, one set per state git reports.

    ``ignored_tracked`` holds TRACKED files an ignore rule matches: git keeps
    tracking them, but the rule would stop them being added again after a
    rename or an untrack, so for a file that must stay tracked it is a
    problem too. ``--others`` never lists these.
    """

    tracked: frozenset[str]
    ignored_untracked: frozenset[str]
    ignored_tracked: frozenset[str]
    all_paths: frozenset[str]
    # Verdicts already reached, keyed by project root and pattern set (N289b).
    _protected: dict[tuple[str, tuple[str, ...]], list[str]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def is_ignored(self, relpath: str) -> bool:
        """True when an ignore rule matches ``relpath``, tracked or not."""
        return relpath in self.ignored_untracked or relpath in self.ignored_tracked

    def protected_relpaths(self, project_root: Path, patterns: tuple[str, ...]) -> list[str]:
        """The sorted relative paths here that a protected glob covers.

        Judging every path is the expensive part of a sweep, and the two
        SessionStart sweeps each need the same answer for the same scan, so the
        verdict is kept on the scan and computed once per pattern set.
        """
        key = (str(project_root), patterns)
        cached = self._protected.get(key)
        if cached is None:
            relpaths = sorted(self.all_paths)
            absolutes = [str(project_root / relpath) for relpath in relpaths]
            hits = set(protected_among(absolutes, patterns))
            cached = [r for r, a in zip(relpaths, absolutes, strict=True) if a in hits]
            self._protected[key] = cached
        return list(cached)


def scan_git_file_states(project_root: Path) -> GitFileStates | None:
    """The file states of the repository at ``project_root``, or ``None``.

    ``None`` means git could not answer (not a repository, or git missing).
    Callers must treat that as "unknown", never as "nothing is ignored".
    """
    tracked = _git_paths(project_root, "--cached")
    if tracked is None:
        return None
    visible = _git_paths(project_root, "--others", "--exclude-standard")
    if visible is None:
        return None
    ignored_untracked = _git_paths(project_root, "--others", "--ignored", "--exclude-standard")
    if ignored_untracked is None:
        return None
    ignored_untracked = _without_foreign_trees(ignored_untracked)
    ignored_tracked = _git_paths(project_root, "--cached", "--ignored", "--exclude-standard")
    if ignored_tracked is None:
        return None
    return GitFileStates(
        tracked=tracked,
        ignored_untracked=ignored_untracked,
        ignored_tracked=ignored_tracked,
        all_paths=tracked | visible | ignored_untracked,
    )


_event_scan: tuple[object, str, GitFileStates | None] | None = None
_event_scan_lock = threading.Lock()


def scan_git_file_states_for_event(project_root: Path, event: object) -> GitFileStates | None:
    """:func:`scan_git_file_states`, shared by every handler of ONE event dispatch.

    The chain hands the same ``event`` object to each handler it runs, so two
    handlers asking with that object get one scan between them instead of
    scanning the repository twice (N289b). A different ``event`` -- the next
    dispatch -- or another ``project_root`` always rescans, so a result is never
    older than the dispatch that asked for it. Only the most recent scan is
    kept.
    """
    global _event_scan
    key = str(project_root)
    with _event_scan_lock:
        held = _event_scan
        if held is not None and held[0] is event and held[1] == key:
            return held[2]
    scan = scan_git_file_states(project_root)
    with _event_scan_lock:
        _event_scan = (event, key, scan)
    return scan


#: A file whose presence marks its directory as a virtualenv.
_VENV_MARKER_FILE: Final[str] = "pyvenv.cfg"
#: A path component that is a package manager's install tree.
_PACKAGE_TREE_COMPONENT: Final[str] = "node_modules"


def _without_foreign_trees(ignored_untracked: frozenset[str]) -> frozenset[str]:
    """``ignored_untracked`` minus the files of trees that are not this project's.

    A gitignored virtualenv (a directory holding ``pyvenv.cfg``), a package
    manager's ``node_modules`` are other people's files, and in a working copy
    that keeps several of them they outnumber the project's own by orders of
    magnitude -- judging each one is what made the SessionStart sweeps overrun
    their budget (N289b). Recognised by structure, so a client project's own
    layout is covered. A nested git checkout needs no rule here: git itself
    reports it as ONE directory entry and never lists its files. Only UNTRACKED
    ignored files are dropped: a file git tracks is the project's own whatever
    directory it sits in, and an ignored directory with none of these markers is
    still judged in full.
    """
    foreign_roots: set[str] = set()
    for path in ignored_untracked:
        directory, _, name = path.rpartition("/")
        if name == _VENV_MARKER_FILE and directory:
            foreign_roots.add(directory)
        parts = path.split("/")
        for depth, component in enumerate(parts[:-1]):
            if component == _PACKAGE_TREE_COMPONENT:
                foreign_roots.add("/".join(parts[: depth + 1]))
                break
    if not foreign_roots:
        return ignored_untracked
    return frozenset(path for path in ignored_untracked if not _under_any(path, foreign_roots))


def _under_any(path: str, roots: set[str]) -> bool:
    """Whether ``path`` is one of ``roots`` or inside one."""
    candidate = path
    while candidate:
        if candidate in roots:
            return True
        candidate = candidate.rpartition("/")[0]
    return False


#: Characters gitignore reads as pattern syntax inside a name.
_GITIGNORE_SPECIAL_RE: Final[re.Pattern[str]] = re.compile(r"([\\*?\[])")

_UNIGNORE_ADVICE: Final[str] = (
    "remove the .gitignore rule that matches it, or add `{negation}` after that "
    "rule (`git check-ignore -v {relpath}` names it; git cannot re-include a file "
    "whose parent DIRECTORY is ignored, so narrow such a rule instead)"
)


def gitignore_negation(relpath: str) -> str:
    """A root ``.gitignore`` line that re-includes exactly ``relpath``.

    Anchored with a leading ``/`` so it cannot also re-include a same-named
    file elsewhere in the tree, and with pattern characters escaped so the
    name is matched literally.
    """
    escaped = _GITIGNORE_SPECIAL_RE.sub(r"\\\1", relpath)
    stripped = escaped.rstrip(" ")
    escaped = stripped + "\\ " * (len(escaped) - len(stripped))
    return f"!/{escaped}"


def unignore_advice(relpath: str) -> str:
    """The one wording both handlers use to take ``relpath`` out of ignore rules."""
    return _UNIGNORE_ADVICE.format(negation=gitignore_negation(relpath), relpath=relpath)


def _git_paths(project_root: Path, *flags: str) -> frozenset[str] | None:
    result = run_git(project_root, "ls-files", *flags)
    if result.returncode != 0:
        return None
    return frozenset(line for line in result.stdout.splitlines() if line)
