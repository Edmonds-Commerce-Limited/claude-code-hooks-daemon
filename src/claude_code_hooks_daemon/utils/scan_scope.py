"""Scope helpers shared by the QA checks that walk the tree (00466 N26).

Two rules every walker follows:

- An exclusion by directory NAME is judged on the path's components BELOW the
  scan root, never on its absolute path. Every agent worktree lives under
  ``untracked/worktrees/``, so an absolute-path test for ``untracked`` or
  ``worktrees`` excludes the whole checkout.
- A walk never enters a directory git ignores (a plugin marketplace, a vendored
  cache): that is not this project's content. When git cannot say what is ignored
  the walk fails instead of listing everything.
- A check that examined nothing has not passed, whether its exclusions dropped
  every candidate or its scan root is missing or empty. It reports a failure
  instead, so a broken discovery cannot look like a clean tree.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess  # nosec B404 - only ever runs the trusted system git binary
from pathlib import Path

#: The entry git keeps a checkout's metadata in: a directory, or in a linked
#: worktree or submodule a file pointing at it.
_GIT_ENTRY = ".git"


class WalkError(OSError):
    """A directory below the scan root could not be listed.

    ``os.walk`` drops such a directory silently, so a walker would report the
    files in it clean without having read them. A scan that cannot read part
    of its tree has not passed.
    """


def _refuse_unlistable(error: OSError) -> None:
    """``os.walk`` ``onerror`` hook: fail the walk instead of skipping the directory."""
    raise WalkError(
        f"cannot list {error.filename}: {error.strerror or error}; "
        "the files in it were not scanned, so this is not a pass"
    ) from error


#: ``git`` exit status for "not a git repository"; a tree outside one has no ignore rules.
_NOT_A_REPOSITORY = 128
#: Variables that would point git at a repository other than ``root``'s own.
_RELOCATING_VARIABLES = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"})
#: Generous: ``--directory`` keeps the listing small, so this only bounds a wedged git.
_IGNORED_LISTING_TIMEOUT_SECONDS = 120


def _git_ignored(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """``(directories, files)`` below ``root`` that an ignore rule excludes, relative to it.

    ``--directory`` reports an ignored directory as ONE entry instead of listing
    every file in it, so a large ignored install costs one line. Files git tracks
    are never listed (``--others``). A tree that is not a git repository has no
    ignore rules and yields nothing.

    Raises:
        WalkError: git is missing, timed out or failed: what is ignored is then
            unknown, and treating it as "nothing" is how an untracked tree got scanned.
    """
    environment = {k: v for k, v in os.environ.items() if k not in _RELOCATING_VARIABLES}
    argv = [
        "git",
        "-C",
        str(root),
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--directory",
        "-z",
    ]
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell, trusted binary
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_IGNORED_LISTING_TIMEOUT_SECONDS,
            env=environment,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WalkError(
            f"cannot ask git what {root} ignores: {exc}; "
            "an ignored tree might have been scanned, so this is not a pass"
        ) from exc
    if result.returncode == _NOT_A_REPOSITORY:
        return frozenset(), frozenset()
    if result.returncode != 0:
        raise WalkError(
            f"git ls-files failed in {root} (exit {result.returncode}): "
            f"{result.stderr.strip()}; what it ignores is unknown, so this is not a pass"
        )
    directories: set[str] = set()
    files: set[str] = set()
    for entry in result.stdout.split("\0"):
        if entry.endswith("/"):
            directories.add(entry.rstrip("/"))
        elif entry:
            files.add(entry)
    return frozenset(directories), frozenset(files)


def walk_files(root: Path, pattern: str = "*") -> list[Path]:
    """Every file below ``root`` whose name matches ``pattern``, sorted.

    Unlike ``root.rglob(pattern)`` this never descends into ``.git``, and it
    skips a nested checkout entirely: any directory below the root holding a
    ``.git`` entry is a worktree, submodule or clone of some other project.
    ``git ls-files`` lists neither, so a walker that meant "this project's
    files" reads the same set whichever way it enumerates. For the same reason
    it leaves out what a ``.gitignore`` rule excludes; a tracked file stays.
    Symlinked
    directories are not followed, as with ``rglob``.

    Args:
        root: The directory to walk; a missing one yields nothing.
        pattern: An ``fnmatch`` pattern for the file NAME, as ``rglob`` takes.

    Raises:
        WalkError: A directory below the root could not be listed, or git could
            not say which paths are ignored.
    """
    found: list[Path] = []
    if not root.is_dir():
        return found
    ignored_dirs, ignored_files = _git_ignored(root)
    for directory, dirnames, filenames in os.walk(root, onerror=_refuse_unlistable):
        here = Path(directory)
        if here != root and (_GIT_ENTRY in dirnames or _GIT_ENTRY in filenames):
            dirnames.clear()
            continue
        below = here.relative_to(root).as_posix()
        prefix = "" if below == "." else f"{below}/"
        dirnames[:] = [
            name
            for name in dirnames
            if name != _GIT_ENTRY and f"{prefix}{name}" not in ignored_dirs
        ]
        found.extend(
            here / name
            for name in filenames
            if name != _GIT_ENTRY
            and f"{prefix}{name}" not in ignored_files
            and fnmatch.fnmatchcase(name, pattern)
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
    below = _parts_below(path, root)
    if below is not None:
        return below
    resolved = path.resolve()
    below = _parts_below(resolved, root.resolve())
    if below is not None:
        return below
    return resolved.parts[1:]


def _parts_below(path: Path, root: Path) -> tuple[str, ...] | None:
    """``path.relative_to(root).parts``, or None when ``path`` is not under ``root``.

    Compares ``parts`` once. From Python 3.12 the stdlib's ``relative_to``
    walks every parent and costs O(depth^2) (Plan 00466 N106). This module
    must stay stdlib-only, so it cannot import ``utils.path_containment``.
    """
    prefix = root.parts
    if path.anchor != root.anchor or path.parts[: len(prefix)] != prefix:
        return None
    return path.parts[len(prefix) :]


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
