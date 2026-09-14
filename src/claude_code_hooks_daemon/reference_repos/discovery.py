"""Enumerate the git checkouts a project governs as reference repositories.

Discovery decides the blast radius for everything downstream, and both failure
directions are silent. Enumerate too little and a stale clone stays ungoverned,
which is the whole defect: the agent reads a weeks-old checkout and its
reasoning looks exactly like correct reasoning. Enumerate too much and the
report fills with submodules, vendored trees and unrelated checkouts, which a
reader learns to skip — a report nobody reads governs nothing either.

Two boundaries carry that weight:

``a checkout is not descended into``
    A ``.git`` inside a ``.git``, or a submodule inside a clone, belongs to its
    parent. Reporting it separately would double-count the same staleness and
    invite pulling a submodule its parent pins deliberately.

``the walk is bounded``
    A root is configuration, and configuration can say ``/``. The depth bound is
    what keeps a misconfigured root from becoming a filesystem-wide walk — the
    same failure the daemon's own root-recursion guard exists to prevent. A
    non-positive bound finds nothing rather than everything, so the nonsense
    value fails closed.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.path_exclusion import is_path_excluded

#: Depth in path segments BELOW a root. ``untracked/repos/<owner>/<repo>`` is
#: two, so the default leaves headroom for a deeper organising convention
#: without inviting an unbounded walk.
DEFAULT_MAX_DEPTH: Final[int] = 4

#: The entry that marks a checkout. Tested for EXISTENCE, never for being a
#: directory: a worktree and a submodule both carry a ``.git`` FILE, and an
#: ``is_dir()`` test would silently skip exactly those.
#: What marks a directory as a checkout. Public because the PreToolUse gate
#: asks the same question of a path the walk never reached -- and a second
#: spelling of ".git" is exactly the drift this package exists to avoid.
GIT_ENTRY: Final[str] = ".git"
_GIT_ENTRY: Final[str] = GIT_ENTRY


def _is_checkout(path: Path) -> bool:
    """Return True when ``path`` carries a ``.git`` entry of either kind."""
    return (path / _GIT_ENTRY).exists()


def _child_directories(directory: Path) -> list[Path]:
    """Return ``directory``'s immediate subdirectories, skipping ``.git``.

    An unreadable directory yields nothing rather than raising. One unreadable
    subtree must not cost the caller every other repository in the sweep — a
    freshness report that aborts on the first permission error reports on
    nothing, which is strictly worse than reporting on the rest.

    Symlinks are not followed, which keeps a looping link from turning the walk
    into a non-terminating one.
    """
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return []

    children: list[Path] = []
    for entry in entries:
        if entry.name == _GIT_ENTRY:
            continue
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        children.append(Path(entry.path))
    return children


def discover_reference_repos(
    roots: Iterable[Path],
    *,
    exclude_globs: Sequence[str] | None = None,
    project_root: Path | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[Path]:
    """Return every governed checkout beneath ``roots``, sorted.

    Args:
        roots: Directories to sweep. A root that is missing, or is not a
            directory, is skipped silently — the default root does not exist in
            a project that has not adopted the convention, and raising there
            would make every consumer fail closed for the majority of projects.
        exclude_globs: Patterns in the project's single glob dialect
            (:mod:`utils.path_exclusion`), so a project learns the syntax once.
        project_root: Enables project-relative and anchored glob matching.
        max_depth: Maximum segments below a root to search. Non-positive finds
            nothing.

    Returns:
        Sorted absolute paths of governed checkouts. Sorted rather than
        walk-ordered so a report and its diff do not churn between runs for
        reasons that are really just filesystem ordering.
    """
    found: set[Path] = set()

    for root in roots:
        if max_depth <= 0 or not root.is_dir():
            continue

        pending: list[tuple[Path, int]] = [(root, 0)]
        while pending:
            directory, depth = pending.pop()
            if depth >= max_depth:
                continue
            for child in _child_directories(directory):
                if _is_checkout(child):
                    # Deliberately not descended into: see the module docstring.
                    if not is_path_excluded(str(child), exclude_globs, project_root=project_root):
                        found.add(child)
                    continue
                pending.append((child, depth + 1))

    return sorted(found)
