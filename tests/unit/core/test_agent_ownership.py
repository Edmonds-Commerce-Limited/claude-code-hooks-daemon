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

    def test_harness_directory_names_the_command_that_reaps_it(self) -> None:
        """Plan 00571 Phase 4 dogfood: `branch-sweep --clean --remote` skipped
        three merged agent worktrees with "left alone" and no way forward;
        `worktree-reap --reap` is the command whose job they are."""
        holds = RunningHolds(frozenset(), frozenset())
        reason = ownership_refusal("b", Path("/r/.claude/worktrees/b"), locked=False, holds=holds)
        assert reason is not None
        assert "worktree-reap --reap --only b" in reason

    def test_reap_hint_names_the_directory_not_the_branch(self) -> None:
        """`worktree-reap --only` matches the worktree directory name, which git keeps
        separate from the branch name."""
        holds = RunningHolds(frozenset(), frozenset())
        reason = ownership_refusal(
            "worktree-foo", Path("/r/.claude/worktrees/foo"), locked=False, holds=holds
        )
        assert reason is not None
        assert "worktree-reap --reap --only foo`" in reason
        assert "--only worktree-foo" not in reason

    def test_locked(self) -> None:
        holds = RunningHolds(frozenset(), frozenset())
        reason = ownership_refusal("b", Path("/x/y"), locked=True, holds=holds)
        assert reason is not None and "locked" in reason

    def test_branch_only_without_a_worktree(self) -> None:
        holds = RunningHolds(frozenset({"b"}), frozenset())
        reason = ownership_refusal("b", None, locked=False, holds=holds)
        assert reason is not None and "running" in reason


class TestWorktreePathNormalisation:
    """A record's spelling of the path must not decide whether the hold matches."""

    @staticmethod
    def _refusal(untracked: Path, worktree: Path) -> str | None:
        # A branch the record does not name, so only the worktree path can match.
        return ownership_refusal(
            "other-branch", worktree, locked=False, holds=running_holds(untracked)
        )

    def test_absolute_record_matches(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        wt = tmp_path / "wt" / "a"
        wt.mkdir(parents=True)
        _record(untracked, "a", "recorded", str(wt))
        assert self._refusal(untracked, wt) is not None

    def test_relative_record_resolves_against_the_project_root(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        wt = tmp_path / "wt" / "a"
        wt.mkdir(parents=True)
        _record(untracked, "a", "recorded", "wt/a")
        assert self._refusal(untracked, wt) is not None

    def test_trailing_slash_record_matches(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        wt = tmp_path / "wt" / "a"
        wt.mkdir(parents=True)
        _record(untracked, "a", "recorded", f"{wt}/")
        assert self._refusal(untracked, wt) is not None

    def test_symlinked_spelling_matches(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        wt = tmp_path / "real" / "a"
        wt.mkdir(parents=True)
        (tmp_path / "link").symlink_to(tmp_path / "real")
        _record(untracked, "a", "recorded", str(tmp_path / "link" / "a"))
        assert self._refusal(untracked, wt) is not None

    def test_a_different_worktree_does_not_match(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        (tmp_path / "wt" / "a").mkdir(parents=True)
        other = tmp_path / "wt" / "b"
        other.mkdir()
        _record(untracked, "a", "recorded", "wt/a")
        assert self._refusal(untracked, other) is None
