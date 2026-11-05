"""Recommend ``claudeMdExcludes`` for worktrees kept under the project root (Plan 00563).

A sub-agent working in a worktree that lives under the project root loads the
project's root ``CLAUDE.md`` twice: once from the main checkout and once more
from the worktree's own copy (Plan 00561, GitHub #156), which can cost around
30k tokens. Claude Code's ``claudeMdExcludes`` setting stops the second copy.

The ``optimise`` review SUGGESTS the globs and never writes them; applying is
left to the confirmation that review already asks for.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

from claude_code_hooks_daemon.core.worktree_naming import WORKTREES_SUBDIR
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to, path_relative_to

#: Worktree roots the daemon itself creates, relative to the project root.
#: ``scripts/setup_worktree.sh`` owns the first, the WorktreeCreate handler the
#: second; ``tests/integration/test_worktree_claudemd_excludes.py`` pins both.
SCRIPT_WORKTREES_SUBDIR: str = "untracked/worktrees"
KNOWN_WORKTREE_ROOTS: tuple[str, ...] = (SCRIPT_WORKTREES_SUBDIR, WORKTREES_SUBDIR)

#: Project settings files Claude Code reads ``claudeMdExcludes`` from.
SETTINGS_FILES: tuple[str, ...] = (".claude/settings.json", ".claude/settings.local.json")
#: Where the recommendation tells the user to put the globs (per-machine, untracked).
RECOMMENDED_SETTINGS_FILE: str = ".claude/settings.local.json"

_EXCLUDES_KEY: str = "claudeMdExcludes"
_SAMPLE_WORKTREE: str = "example-worktree"


def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Translate a glob over absolute paths: ``**`` crosses directories, ``*`` does not.

    ``?`` matches one non-separator character. Character classes (``[ab]``) and
    braces (``{a,b}``) are NOT supported: they match themselves literally, so a
    glob that relies on them is reported as uncovering the worktree root.
    """
    parts: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            parts.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            parts.append(".*")
            i += 2
        elif glob[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(parts) + r"\Z")


def git_worktree_paths(project_root: Path) -> list[Path]:
    """Return every worktree path ``git worktree list --porcelain`` reports.

    Not a repository, no ``git`` on PATH, or a timeout (all a non-zero return
    from :func:`run_git`) means there are no git worktrees to report, so the
    result is empty: this is a probe of optional state, not a requirement of the
    review.
    """
    result = run_git(project_root, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return []
    prefix = "worktree "
    return [
        Path(line[len(prefix) :]) for line in result.stdout.splitlines() if line.startswith(prefix)
    ]


def _has_subdirectory(directory: Path) -> bool:
    return directory.is_dir() and any(child.is_dir() for child in directory.iterdir())


def _worktree_targets(project_root: Path, git_worktrees: Sequence[Path]) -> dict[str, Path]:
    """Map each glob a project needs to a sample CLAUDE.md path that glob must match.

    Worktrees are grouped by the directory holding them, so one glob covers every
    sibling. A worktree directly under the project root has no such directory and
    is excluded by its own name.
    """
    targets: dict[str, Path] = {}
    for root in KNOWN_WORKTREE_ROOTS:
        if _has_subdirectory(project_root / root):
            sample = project_root / root / _SAMPLE_WORKTREE / "CLAUDE.md"
            targets[f"**/{root}/*/CLAUDE.md"] = sample
    for worktree in git_worktrees:
        resolved = worktree.resolve()
        if resolved == project_root or not path_is_relative_to(resolved, project_root):
            continue
        relative = path_relative_to(resolved, project_root)
        if len(relative.parts) == 1:
            targets[f"**/{relative.as_posix()}/CLAUDE.md"] = resolved / "CLAUDE.md"
        else:
            holder = relative.parent.as_posix()
            targets[f"**/{holder}/*/CLAUDE.md"] = (
                project_root / holder / _SAMPLE_WORKTREE / "CLAUDE.md"
            )
    return targets


def _declared_excludes(project_root: Path) -> list[str]:
    """Collect ``claudeMdExcludes`` from the project settings files.

    Raises:
        ValueError: A settings file exists but is unreadable, is not a JSON
            object, or holds a ``claudeMdExcludes`` that is not a list.
    """
    excludes: list[str] = []
    for name in SETTINGS_FILES:
        path = project_root / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read {name}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"cannot read {name}: top level is not a JSON object")
        entries = data.get(_EXCLUDES_KEY, [])
        if not isinstance(entries, list):
            raise ValueError(f"cannot read {name}: {_EXCLUDES_KEY} is not a list")
        excludes.extend(str(entry) for entry in entries)
    return excludes


def suggest_claudemd_excludes(project_root: Path, git_worktrees: Sequence[Path] = ()) -> list[str]:
    """Return recommendation lines for worktree roots no ``claudeMdExcludes`` glob covers.

    Args:
        project_root: The project's root directory.
        git_worktrees: Worktree paths ``git worktree list`` reports (see
            :func:`git_worktree_paths`); those inside the project root count.

    Returns:
        An empty list (silent) when no worktree lives under the root or every
        such root is already covered; otherwise the lines to show the user.
    """
    root = project_root.resolve()
    try:
        targets = _worktree_targets(root, git_worktrees)
    except OSError as exc:
        return [
            f"cannot read a worktree directory under the project root ({exc}); cannot check "
            f"`{_EXCLUDES_KEY}` coverage - fix its permissions and re-run"
        ]
    if not targets:
        return []
    try:
        excludes = _declared_excludes(root)
    except ValueError as exc:
        return [
            f"worktrees live under the project root but {exc}; cannot check "
            f"`{_EXCLUDES_KEY}` coverage - fix that file and re-run"
        ]

    patterns = [glob_to_regex(glob) for glob in excludes]
    uncovered = [
        glob
        for glob, sample in targets.items()
        if not any(pattern.match(sample.as_posix()) for pattern in patterns)
    ]
    if not uncovered:
        return []

    glob_list = ", ".join(f'"{glob}"' for glob in uncovered)
    return [
        f"worktrees live under the project root with no `{_EXCLUDES_KEY}` glob covering them: "
        f"add {glob_list} to `{_EXCLUDES_KEY}` in `{RECOMMENDED_SETTINGS_FILE}`. "
        "Without it a sub-agent working in such a worktree loads the root CLAUDE.md twice "
        "(the worktree's own copy too), up to ~30k tokens."
    ]
