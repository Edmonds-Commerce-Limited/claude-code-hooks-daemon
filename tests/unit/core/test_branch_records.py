"""Tests for the branch creator and touch records (Plan 00558 Task 4.2 part B)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.branch_records import (
    CREATED_KEY,
    CREATOR_KEY,
    ROUTE_KEY,
    TOUCHED_KEY,
    WORKTREE_CREATE_ROUTE,
    creator_route,
    identity,
    record_creation,
    record_touch,
    touched_branches,
    worktree_branch_deletable,
    write_creator,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _values(repo: Path, name: str, key: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "config", "--get-all", f"branch.{name}.{key}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.split()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    return root


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    path = tmp_path / "untracked"
    path.mkdir()
    return path


class TestIdentity:
    def test_main_thread_has_empty_agent(self) -> None:
        assert identity("s1", None) == "s1:"
        assert identity("s1", "") == "s1:"

    def test_agent_is_appended(self) -> None:
        assert identity("s1", "a9") == "s1:a9"


class TestRecordCreation:
    def test_writes_three_keys_when_ref_exists(self, repo: Path) -> None:
        _git(repo, "branch", "feat/x")
        assert record_creation(
            repo, "feat/x", session_id="s1", agent_id="a1", route="switch", now=1700000000
        )
        assert _values(repo, "feat/x", CREATOR_KEY) == ["s1:a1"]
        assert _values(repo, "feat/x", CREATED_KEY) == ["1700000000"]
        assert _values(repo, "feat/x", ROUTE_KEY) == ["switch"]

    def test_missing_ref_is_not_recorded(self, repo: Path) -> None:
        assert not record_creation(repo, "ghost", session_id="s1", agent_id=None, route="branch")
        assert _values(repo, "ghost", CREATOR_KEY) == []

    def test_existing_creator_is_not_claimed(self, repo: Path) -> None:
        _git(repo, "branch", "old")
        _git(repo, "config", f"branch.old.{CREATOR_KEY}", "s0:")
        assert not record_creation(repo, "old", session_id="s1", agent_id="a1", route="checkout")
        assert _values(repo, "old", CREATOR_KEY) == ["s0:"]

    def test_write_creator_reports_a_failed_write(self, tmp_path: Path) -> None:
        assert not write_creator(tmp_path, "x", "s1:", WORKTREE_CREATE_ROUTE, now=1)


class TestCreatorRoute:
    def test_absent_record_is_none(self, repo: Path) -> None:
        assert creator_route(repo, "nothing") is None

    def test_recorded_route_is_returned(self, repo: Path) -> None:
        _git(repo, "branch", "w")
        assert write_creator(repo, "w", "s1:", WORKTREE_CREATE_ROUTE, now=1)
        assert creator_route(repo, "w") == WORKTREE_CREATE_ROUTE

    def test_unreadable_repository_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / ".git").write_text("gitdir: /nonexistent\n")
        with pytest.raises(RuntimeError):
            creator_route(bad, "w")


class TestWorktreeBranchDeletable:
    NAME_SHAPED = "fix-thing-1a2b3c4d"

    def test_worktree_create_route_is_eligible(self, repo: Path) -> None:
        _git(repo, "branch", "plain-name")
        write_creator(repo, "plain-name", "s1:", WORKTREE_CREATE_ROUTE, now=1)
        assert worktree_branch_deletable(repo, "plain-name")

    def test_no_record_falls_back_to_name_shape(self, repo: Path) -> None:
        assert worktree_branch_deletable(repo, self.NAME_SHAPED)
        assert not worktree_branch_deletable(repo, "plain-name")

    def test_other_route_is_not_eligible_even_with_the_name_shape(self, repo: Path) -> None:
        _git(repo, "branch", self.NAME_SHAPED)
        write_creator(repo, self.NAME_SHAPED, "s1:a1", "switch", now=1)
        assert not worktree_branch_deletable(repo, self.NAME_SHAPED)

    def test_unreadable_record_is_not_eligible(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / ".git").write_text("gitdir: /nonexistent\n")
        assert not worktree_branch_deletable(bad, self.NAME_SHAPED)


class TestRecordTouch:
    def test_adds_identity_once(self, repo: Path, untracked: Path) -> None:
        _git(repo, "branch", "b")
        record_touch(repo, "b", session_id="s1", agent_id="a1", untracked=untracked)
        record_touch(repo, "b", session_id="s1", agent_id="a1", untracked=untracked)
        assert _values(repo, "b", TOUCHED_KEY) == ["s1:a1"]

    def test_deduplicates_across_sessions_state_loss(self, repo: Path, tmp_path: Path) -> None:
        _git(repo, "branch", "b")
        first = tmp_path / "u1"
        second = tmp_path / "u2"
        first.mkdir()
        second.mkdir()
        record_touch(repo, "b", session_id="s1", agent_id=None, untracked=first)
        record_touch(repo, "b", session_id="s1", agent_id=None, untracked=second)
        assert _values(repo, "b", TOUCHED_KEY) == ["s1:"]

    def test_second_toucher_is_added(self, repo: Path, untracked: Path) -> None:
        _git(repo, "branch", "b")
        record_touch(repo, "b", session_id="s1", agent_id=None, untracked=untracked)
        record_touch(repo, "b", session_id="s2", agent_id="a2", untracked=untracked)
        assert _values(repo, "b", TOUCHED_KEY) == ["s1:", "s2:a2"]

    def test_state_remembers_the_branch(self, repo: Path, untracked: Path) -> None:
        _git(repo, "branch", "b")
        record_touch(repo, "b", session_id="s1", agent_id=None, untracked=untracked)
        _git(repo, "config", "--unset-all", f"branch.b.{TOUCHED_KEY}")
        record_touch(repo, "b", session_id="s1", agent_id=None, untracked=untracked)
        assert _values(repo, "b", TOUCHED_KEY) == []

    def test_agent_binds_a_main_thread_worktree_creator(self, repo: Path, untracked: Path) -> None:
        _git(repo, "branch", "w")
        write_creator(repo, "w", "s1:", WORKTREE_CREATE_ROUTE, now=1)
        record_touch(repo, "w", session_id="s1", agent_id="a7", untracked=untracked)
        assert _values(repo, "w", CREATOR_KEY) == ["s1:a7"]

    def test_other_session_creator_is_not_rebound(self, repo: Path, untracked: Path) -> None:
        _git(repo, "branch", "w")
        write_creator(repo, "w", "s0:", WORKTREE_CREATE_ROUTE, now=1)
        record_touch(repo, "w", session_id="s1", agent_id="a7", untracked=untracked)
        assert _values(repo, "w", CREATOR_KEY) == ["s0:"]

    def test_failed_write_logs_and_returns(
        self, tmp_path: Path, untracked: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        record_touch(tmp_path, "b", session_id="s1", agent_id=None, untracked=untracked)
        assert "branch_records" in caplog.text


class TestTouchedBranches:
    def test_lists_branches_touched_by_the_identity(self, repo: Path, untracked: Path) -> None:
        for name in ("a", "feat/b.c", "z"):
            _git(repo, "branch", name)
        record_touch(repo, "feat/b.c", session_id="s1", agent_id="a1", untracked=untracked)
        record_touch(repo, "a", session_id="s1", agent_id="a1", untracked=untracked)
        record_touch(repo, "z", session_id="s1", agent_id=None, untracked=untracked)
        assert touched_branches(repo, "s1", "a1") == ["a", "feat/b.c"]
        assert touched_branches(repo, "s1", None) == ["z"]
        assert touched_branches(repo, "s2", None) == []

    def test_unreadable_repository_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / ".git").write_text("gitdir: /nonexistent\n")
        with pytest.raises(RuntimeError):
            touched_branches(bad, "s1", None)
