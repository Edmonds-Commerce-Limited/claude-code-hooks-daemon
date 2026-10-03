"""Where a ``git commit`` runs, judged against the project's own repository."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.git_commit_parsing import CommitReading
from claude_code_hooks_daemon.utils.git_facts import commit_directory
from claude_code_hooks_daemon.utils.git_repo import GitRepo


def commit_runs_in_foreign_repo(
    reading: CommitReading, cwd: str | Path | None, project_root: Path
) -> bool:
    """True when the commit runs in a repository other than the project's.

    Ledger 00474 N300/N305: a nested worktree or another checkout owns its own
    index. Where the commit runs is the hook's ``cwd`` after any ``cd``/``-C``
    move before it; a move this reading cannot state is judged against this
    project. A ``cd`` that may not have taken effect leaves two places the
    commit could run, and it stands down only when BOTH are another repository.
    """
    if not cwd:
        return False
    moved = commit_directory(reading, cwd)
    places = [moved if moved is not None else Path(cwd)]
    if not reading.moves_certain:
        places.append(Path(cwd))
    for place in places:
        repo = GitRepo.resolve_for(place)
        if repo is None or repo.root == project_root:
            return False
    return True
