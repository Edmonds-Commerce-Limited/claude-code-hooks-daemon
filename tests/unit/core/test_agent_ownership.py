"""Tests for the signals that mark a worktree or branch as a live agent's."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.core.agent_ownership import (
    RunningHolds,
    ownership_refusal,
    running_holds,
)
from claude_code_hooks_daemon.utils.work_queue import WORK_QUEUE_FILENAME, add_record


def _record(untracked: Path, name: str, branch: str, worktree: str) -> None:
    add_record(
        untracked / WORK_QUEUE_FILENAME,
        name,
        worktree=worktree,
        branch=branch,
        brief="b",
        brief_file=None,
        last_sha="s",
        now=1.0,
    )


class TestRunningHolds:
    def test_missing_queue_holds_nothing(self, tmp_path: Path) -> None:
        assert running_holds(tmp_path) == RunningHolds(frozenset(), frozenset())

    def test_collects_branches_and_worktrees_of_running_records(self, tmp_path: Path) -> None:
        _record(tmp_path, "a", "br-a", "/w/a")
        holds = running_holds(tmp_path)
        assert holds.branches == {"br-a"}
        assert holds.worktrees == {"/w/a"}

    def test_unreadable_queue_holds_nothing(self, tmp_path: Path) -> None:
        (tmp_path / WORK_QUEUE_FILENAME).write_text("not json", encoding="utf-8")
        assert running_holds(tmp_path) == RunningHolds(frozenset(), frozenset())


class TestOwnershipRefusal:
    def test_free_worktree_has_no_refusal(self) -> None:
        holds = RunningHolds(frozenset(), frozenset())
        assert ownership_refusal("b", Path("/x/y"), locked=False, holds=holds) is None

    def test_harness_directory(self) -> None:
        holds = RunningHolds(frozenset(), frozenset())
        reason = ownership_refusal("b", Path("/r/.claude/worktrees/b"), locked=False, holds=holds)
        assert reason is not None and ".claude/worktrees" in reason

    def test_locked(self) -> None:
        holds = RunningHolds(frozenset(), frozenset())
        reason = ownership_refusal("b", Path("/x/y"), locked=True, holds=holds)
        assert reason is not None and "locked" in reason

    def test_branch_only_without_a_worktree(self) -> None:
        holds = RunningHolds(frozenset({"b"}), frozenset())
        reason = ownership_refusal("b", None, locked=False, holds=holds)
        assert reason is not None and "running" in reason
