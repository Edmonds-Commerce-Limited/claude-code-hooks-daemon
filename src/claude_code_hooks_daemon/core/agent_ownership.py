"""Which worktrees and branches belong to a live agent, so a sweep leaves them be.

A freshly spawned isolation worktree sits at the default branch's tip with a clean
tree, so containment calls its branch merged and nothing in it looks worth keeping.
Three signals say it is not the sweep's to remove:

- a ``running`` work-queue record names its branch or worktree (the same record the
  stop guard treats as a hand-over);
- it lives under the Claude Code harness's ``.claude/worktrees/`` directory, which
  Claude Code creates for ``isolation: worktree`` agents and cleans itself;
- git reports it ``locked``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.work_queue import (
    WORK_QUEUE_FILENAME,
    WorkQueueError,
    active_records,
    read_queue,
)

logger = logging.getLogger(__name__)

_HARNESS_PARTS = Path(ProjectPath.CLAUDE_WORKTREES_DIR).parts


@dataclass(frozen=True)
class RunningHolds:
    """Branches and worktree paths named by ``running`` work-queue records."""

    branches: frozenset[str]
    worktrees: frozenset[str]


def canonical_path(path: Path | str, project_root: Path) -> str:
    """``path`` as one absolute, symlink-free, separator-trimmed string.

    A relative path is taken relative to ``project_root`` (the work queue records
    it that way); ``Path`` already drops a trailing separator.
    """
    return str((project_root / path).resolve())


def running_holds(untracked: Path, project_root: Path | None = None) -> RunningHolds:
    """The holds of every ``running`` record; empty when the queue is unreadable.

    Worktree holds are stored canonical (see :func:`canonical_path`), so the
    spelling a record was written in does not decide whether it matches.
    ``project_root`` defaults to the parent of ``untracked``.
    """
    root = project_root if project_root is not None else untracked.parent
    try:
        records = active_records(read_queue(untracked / WORK_QUEUE_FILENAME))
    except WorkQueueError as exc:
        log_and_continue(
            logger,
            exc,
            reason="agent_ownership: the work queue is unreadable, so no running agent is "
            "known and only the harness-directory and lock signals apply",
        )
        return RunningHolds(frozenset(), frozenset())
    return RunningHolds(
        branches=frozenset(r.branch for r in records if r.branch),
        worktrees=frozenset(canonical_path(r.worktree, root) for r in records if r.worktree),
    )


def in_harness_directory(path: Path) -> bool:
    """Whether ``path`` is a direct child of a ``.claude/worktrees`` directory."""
    return path.parent.parts[-len(_HARNESS_PARTS) :] == _HARNESS_PARTS


def ownership_refusal(
    branch: str,
    worktree: Path | None,
    *,
    locked: bool,
    holds: RunningHolds,
    harness_directory: bool = True,
) -> str | None:
    """Why ``branch`` and its ``worktree`` must be left alone, or None when they are free.

    ``harness_directory=False`` drops the ``.claude/worktrees/`` signal, for the one
    command (``worktree-reap``) whose job is to reap exactly those worktrees, behind
    its own liveness checks.
    """
    if branch in holds.branches or (
        worktree is not None and canonical_path(worktree, Path("/")) in holds.worktrees
    ):
        return "a running work-queue agent owns it; left alone"
    if worktree is None:
        return None
    if locked:
        return f"the worktree {worktree} is locked by git; left alone"
    if harness_directory and in_harness_directory(worktree):
        return (
            f"the worktree {worktree} is under {ProjectPath.CLAUDE_WORKTREES_DIR}/, "
            "which Claude Code owns; left alone"
        )
    return None
