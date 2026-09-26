"""Scope helpers shared by the QA checks that walk the tree (00466 N26).

Two rules every walker follows:

- An exclusion by directory NAME is judged on the path's components BELOW the
  scan root, never on its absolute path. Every agent worktree lives under
  ``untracked/worktrees/``, so an absolute-path test for ``untracked`` or
  ``worktrees`` excludes the whole checkout.
- A check that examined nothing has not passed, whether its exclusions dropped
  every candidate or its scan root is missing or empty. It reports a failure
  instead, so a broken discovery cannot look like a clean tree.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

#: The entry git keeps a checkout's metadata in: a directory, or in a linked
#: worktree or submodule a file pointing at it.
_GIT_ENTRY = ".git"


def walk_files(root: Path, pattern: str = "*") -> list[Path]:
    """Every file below ``root`` whose name matches ``pattern``, sorted.

    Unlike ``root.rglob(pattern)`` this never descends into ``.git``, and it
    skips a nested checkout entirely: any directory below the root holding a
    ``.git`` entry is a worktree, submodule or clone of some other project.
    ``git ls-files`` lists neither, so a walker that meant "this project's
    files" reads the same set whichever way it enumerates. Symlinked
    directories are not followed, as with ``rglob``.

    Args:
        root: The directory to walk; a missing one yields nothing.
        pattern: An ``fnmatch`` pattern for the file NAME, as ``rglob`` takes.
    """
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        here = Path(directory)
        if here != root and (_GIT_ENTRY in dirnames or _GIT_ENTRY in filenames):
            dirnames.clear()
            continue
        dirnames[:] = [name for name in dirnames if name != _GIT_ENTRY]
        found.extend(
            here / name
            for name in filenames
            if name != _GIT_ENTRY and fnmatch.fnmatchcase(name, pattern)
        )
    return sorted(found)


def relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    """``path``'s components below ``root``, for matching directory names.

    A relative ``path`` is taken as already relative to the root. Both sides
    are resolved first, so a symlinked root still matches. A path outside the
    root keeps its own components without the filesystem anchor: it cannot be
    rescued, but it must not pick up a stray match on ``/``.
    """
    if not path.is_absolute():
        return path.parts
    if path.is_relative_to(root):
        return path.relative_to(root).parts
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved.is_relative_to(resolved_root):
        return resolved.relative_to(resolved_root).parts
    return resolved.parts[1:]


def vacuous_scan_failure(
    *, examined: int, noun: str, candidates: int | None = None, root: Path | None = None
) -> str | None:
    """A failure message when a scan examined nothing, else None.

    Every walker scans a tree that is never empty in a sound checkout, so a
    missing or empty scan root is a failure too: a check pointed at the wrong
    place would otherwise report a clean tree of 0 files.

    Args:
        examined: How many items the check actually examined.
        noun: What the items are, for the message (``"files"``).
        candidates: How many items its discovery found before exclusions;
            defaults to ``examined`` for a walker with no exclusion stage.
        root: The scan root, named in the message when given.

    Returns:
        None for a scan that examined something; otherwise a message naming
        the gap.
    """
    if examined:
        return None
    found = examined if candidates is None else candidates
    if found:
        return (
            f"examined 0 of {found} {noun}: the discovery or its exclusions "
            "are broken, so this is not a pass"
        )
    if root is None:
        return (
            f"found no {noun} to examine: the scan root is missing or empty, so this is not a pass"
        )
    if not root.is_dir():
        return f"scan root {root} does not exist or is not a directory, so this is not a pass"
    return f"found no {noun} under {root}: the scan root is empty, so this is not a pass"
