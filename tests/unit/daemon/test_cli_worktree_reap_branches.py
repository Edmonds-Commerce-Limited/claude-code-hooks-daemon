"""Orphaned branches are reported by the command that removed their siblings.

Plan 00352 Task 1.2 decided the surface: `worktree-reap` REPORTS branches with
no worktree, because the moment a human needs to know is the moment they finish
reaping — three branches going quiet is invisible unless the thing that just
removed their siblings says so. Acting on them needs `--reap-branches`, a
separate flag, because widening `--reap` would change what an existing scripted
invocation does without anyone re-reading it.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap

_LISTING = """worktree /repo
HEAD aaa
branch refs/heads/main

worktree /repo/.claude/worktrees/agent-attached-1
HEAD bbb
branch refs/heads/agent-attached-1
"""

_ALL_BRANCHES = "agent-attached-1\nagent-orphan-2\nagent-orphan-3\n"
_MERGED_BRANCHES = "agent-attached-1\nagent-orphan-2\n"


class _FakeGit:
    """One clean attached worktree, plus a merged and an unmerged orphan."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] == "worktree" and args[1] == "list":
            return subprocess.CompletedProcess([], 0, _LISTING, "")
        if args[0] == "status":
            return subprocess.CompletedProcess([], 0, "", "")
        if args[0] == "rev-list":
            return subprocess.CompletedProcess([], 0, "0\n", "")
        if args[0] == "cherry":
            return subprocess.CompletedProcess([], 0, "", "")
        if args[0] == "branch" and "--merged" in args:
            return subprocess.CompletedProcess([], 0, _MERGED_BRANCHES, "")
        if args[0] == "branch" and "--list" in args:
            return subprocess.CompletedProcess([], 0, _ALL_BRANCHES, "")
        # worktree remove / branch -d
        return subprocess.CompletedProcess([], 0, "", "")

    @property
    def branch_deletions(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] == "branch" and "-d" in call]


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "project_root": "/repo",
        "base_branch": "main",
        "reap": False,
        "only": None,
        "reap_branches": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def git() -> _FakeGit:
    return _FakeGit()


class TestTheReportNamesThem:
    def test_an_orphaned_branch_appears(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(), run_fn=git)
        assert "agent-orphan-2" in capsys.readouterr().out

    def test_a_branch_that_still_has_a_worktree_is_not_called_orphaned(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(), run_fn=git)
        out = capsys.readouterr().out
        orphan_lines = [line for line in out.splitlines() if "ORPHAN" in line]
        assert not any("agent-attached-1" in line for line in orphan_lines)

    def test_the_unmerged_one_is_reported_with_its_reason(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """One that silently vanishes from the report looks handled."""
        cmd_worktree_reap(_args(), run_fn=git)
        out = capsys.readouterr().out
        assert "agent-orphan-3" in out
        assert "not fully merged" in out


class TestReapDoesNotTouchBranches:
    def test_the_worktree_flag_alone_deletes_no_standalone_branch(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Widening --reap would change what an existing caller does."""
        cmd_worktree_reap(_args(reap=True), run_fn=git)
        deleted = [call[2] for call in git.branch_deletions]
        assert "agent-orphan-2" not in deleted
        assert "agent-orphan-3" not in deleted


class TestActingOnBranchesNeedsItsOwnFlag:
    def test_the_merged_orphan_is_deleted(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(reap_branches=True), run_fn=git)
        assert ("branch", "-d", "agent-orphan-2") in git.branch_deletions

    def test_the_unmerged_orphan_gets_no_git_command(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(reap_branches=True), run_fn=git)
        assert ("branch", "-d", "agent-orphan-3") not in git.branch_deletions

    def test_no_branch_is_ever_deleted_with_capital_d(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(reap_branches=True), run_fn=git)
        assert not any("-D" in call for call in git.calls)


class TestNarrowingToOneWorktree:
    def test_only_suppresses_the_branch_report(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--only` names a worktree, so branches are not what was asked about."""
        cmd_worktree_reap(_args(only="agent-attached-1"), run_fn=git)
        assert "ORPHAN" not in capsys.readouterr().out
