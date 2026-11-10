"""Advisories for two branch practices a command can be seen breaking.

Recovery copies go to a bundle or ``refs/archive/<name>``, never to a branch (the
pools count only branches), and a worktree is created from the main checkout,
never inside another worktree. The practice itself is written once in
``CLAUDE/core/Worktree.core.md``; these lines only point the agent at it.
Advisory only: neither function ever denies.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.branch_guard import RECOVERY_COPY_PATTERNS
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to

_WORKTREE_PREFIX: Final[str] = "worktree "


def recovery_copy_advisory(name: str) -> str | None:
    """Advice to archive instead, when ``name`` is shaped like a recovery copy."""
    if not any(fnmatchcase(name, pattern) for pattern in RECOVERY_COPY_PATTERNS):
        return None
    return (
        f"`{name}` looks like a recovery copy. Branches count against the work-branch "
        f"cap, so keep a recovery copy as `git update-ref refs/archive/{name} <sha>` "
        "or as a `git bundle create`, not as a branch."
    )


def _worktree_paths(directory: Path) -> list[Path] | None:
    """Registered worktree paths, main checkout first; ``None`` when git cannot say."""
    result = run_git(directory, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return None
    return [
        Path(line.removeprefix(_WORKTREE_PREFIX)).resolve()
        for line in result.stdout.splitlines()
        if line.startswith(_WORKTREE_PREFIX)
    ]


def nested_worktree_advisory(directory: Path, target: str) -> str | None:
    """Advice to create from the main checkout, when ``target`` is inside a linked worktree.

    ``target`` is read relative to ``directory``, the directory the git run acts
    in. A target under the main checkout (``.claude/worktrees/``) is the normal
    place and draws nothing.
    """
    paths = _worktree_paths(directory)
    if not paths:
        return None
    resolved = (directory / target).resolve()
    main, linked = paths[0], paths[1:]
    holder = next((path for path in linked if path_is_relative_to(resolved, path)), None)
    if holder is None:
        return None
    return (
        f"`{resolved}` is inside the worktree `{holder}`; worktrees are created from the "
        f"main checkout `{main}`, never nested. Run `git -C {main} worktree add ...`."
    )
