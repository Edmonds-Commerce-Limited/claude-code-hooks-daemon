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
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.git_repo import run_git


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

    def is_ignored(self, relpath: str) -> bool:
        """True when an ignore rule matches ``relpath``, tracked or not."""
        return relpath in self.ignored_untracked or relpath in self.ignored_tracked


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
    ignored_tracked = _git_paths(project_root, "--cached", "--ignored", "--exclude-standard")
    if ignored_tracked is None:
        return None
    return GitFileStates(
        tracked=tracked,
        ignored_untracked=ignored_untracked,
        ignored_tracked=ignored_tracked,
        all_paths=tracked | visible | ignored_untracked,
    )


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
