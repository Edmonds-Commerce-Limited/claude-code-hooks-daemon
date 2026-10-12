"""Which checkout a path belongs to: this repository, or another one.

One rule for every hook that must not act on another repository's files
(Issues #79, #80): a path below a directory with its own ``.git`` entry that
is not a linked worktree of the project's repository belongs to someone else.
"""

from pathlib import Path

from claude_code_hooks_daemon.core.worktree_paths import nested_git_checkout_root
from claude_code_hooks_daemon.utils.git_repo import is_worktree_of_repo


def owning_checkout(abs_path: str, project_root: Path) -> Path | None:
    """The checkout of THIS repository that ``abs_path`` lives in, else ``None``.

    ``project_root`` itself for an ordinary file. The linked worktree's root for
    a file inside one of this repository's own worktrees, which stays in scope
    and has its own working tree and ignore rules. ``None`` for a file in a
    nested clone, a submodule or a linked worktree of any other repository.
    """
    nested = nested_git_checkout_root(abs_path, project_root)
    if nested is None:
        return project_root
    return nested if is_worktree_of_repo(nested, project_root) else None


def outside_this_repository(abs_path: str, project_root: Path) -> bool:
    """Whether ``abs_path`` belongs to a different repository than ``project_root``."""
    return owning_checkout(abs_path, project_root) is None
