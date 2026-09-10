"""The command that lets a human act on the worktree report.

Plan 00349 Task 2.1 decided: report and offer, never reap automatically. This
is the "offer" — and the property that makes it safe to run without thinking is
that **doing nothing is the default**. Acting requires `--reap` on the command
line, so a curious `worktree-reap` shows you the situation and changes nothing.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.worktree_reaping import RunGit
from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap

_LISTING = """worktree /repo
HEAD aaa
branch refs/heads/main

worktree /repo/.claude/worktrees/agent-clean-1
HEAD bbb
branch refs/heads/agent-clean-1

worktree /repo/.claude/worktrees/agent-dirty-2
HEAD ccc
branch refs/heads/agent-dirty-2
"""

#: The second sanctioned root (`core/worktree_paths.WORKTREE_DIR_PATTERNS`),
#: with a branch whose name does not match its directory.
_UNTRACKED_ROOT_LISTING = """worktree /repo
HEAD aaa
branch refs/heads/main

worktree /repo/untracked/worktrees/agent-clean-1
HEAD bbb
branch refs/heads/wip/renamed-branch
"""


class _FakeGit:
    """A repo with one reapable worktree and one the predicate refuses."""

    def __init__(self, listing: str = _LISTING) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._listing = listing

    def __call__(self, cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        dirty = "agent-dirty-2" in str(cwd)
        if args[0] == "worktree" and args[1] == "list":
            return subprocess.CompletedProcess([], 0, self._listing, "")
        if args[0] == "status":
            return subprocess.CompletedProcess([], 0, "A  x.py\n" if dirty else "", "")
        if args[0] == "rev-list":
            return subprocess.CompletedProcess([], 0, "9\n" if dirty else "0\n", "")
        if args[0] == "cherry":
            return subprocess.CompletedProcess([], 0, "+ abc s\n" if dirty else "", "")
        # worktree remove / branch -d
        return subprocess.CompletedProcess([], 0, "", "")

    @property
    def mutations(self) -> list[tuple[str, ...]]:
        """Only the git calls that CHANGE something.

        `branch` alone is too broad: the orphaned-branch report (Plan 00352)
        reads `branch --list` and `branch --merged`, which remove nothing. A
        predicate that counted those would fail on a command that had done
        exactly what it promised.
        """
        return [
            call
            for call in self.calls
            if (call[0] == "branch" and ("-d" in call or "-D" in call))
            or (call[0] == "worktree" and call[1] == "remove")
        ]


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "project_root": "/repo",
        "base_branch": "main",
        "reap": False,
        "only": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _old_enough(_path: Path) -> float:
    return 999_999.0


def _nobody_home() -> dict[int, Path]:
    return {}


def _reap(args: argparse.Namespace, *, run_fn: RunGit) -> int:
    """`cmd_worktree_reap` with Plan 00372's age/process axis held old/empty.

    This file's subject is CLI wiring and report formatting, not that axis —
    held old/empty by default so it stays silent and every assertion here
    keeps isolating what it always meant to.
    """
    return cmd_worktree_reap(args, run_fn=run_fn, age_fn=_old_enough, process_cwds_fn=_nobody_home)


@pytest.fixture
def git() -> _FakeGit:
    return _FakeGit()


class TestTheDefaultChangesNothing:
    def test_no_worktree_or_branch_is_removed_without_the_flag(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _reap(_args(), run_fn=git)
        assert git.mutations == []

    def test_it_still_says_what_it_would_do(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _reap(_args(), run_fn=git)
        out = capsys.readouterr().out
        assert "agent-clean-1" in out
        assert "would remove" in out.lower()

    def test_it_explains_each_refusal_rather_than_just_omitting_it(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A worktree that silently vanishes from the report looks handled."""
        _reap(_args(), run_fn=git)
        out = capsys.readouterr().out
        assert "agent-dirty-2" in out
        assert "not safe to reap" in out


class TestActingRequiresTheFlag:
    def test_only_the_cleared_worktree_is_removed(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _reap(_args(reap=True), run_fn=git)
        removed = [call for call in git.mutations if call[0] == "worktree"]
        assert len(removed) == 1
        assert "agent-clean-1" in removed[0][2]

    def test_the_refused_worktree_gets_no_git_command(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _reap(_args(reap=True), run_fn=git)
        assert not any("agent-dirty-2" in " ".join(call) for call in git.mutations)

    def test_its_branch_goes_too(self, git: _FakeGit, capsys: pytest.CaptureFixture[str]) -> None:
        _reap(_args(reap=True), run_fn=git)
        assert any(call[0] == "branch" and "-d" in call for call in git.mutations)


class TestTheWorktreeIsAddressedWhereGitSaidItIs:
    """`untracked/worktrees/` is sanctioned too, so the root cannot be assumed."""

    def test_a_worktree_under_the_untracked_root_is_removed_by_its_real_path(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        git = _FakeGit(listing=_UNTRACKED_ROOT_LISTING)
        _reap(_args(reap=True), run_fn=git)
        removed = [call for call in git.mutations if call[0] == "worktree"]
        assert [call[2] for call in removed] == ["/repo/untracked/worktrees/agent-clean-1"]

    def test_the_dry_run_report_names_the_path_that_exists(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A report naming a path that is not there reads as a failed reap."""
        _reap(_args(), run_fn=_FakeGit(listing=_UNTRACKED_ROOT_LISTING))
        out = capsys.readouterr().out
        assert "/repo/untracked/worktrees/agent-clean-1" in out
        assert "/repo/.claude/worktrees/agent-clean-1" not in out

    def test_the_branch_deleted_is_the_one_the_worktree_had_checked_out(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        git = _FakeGit(listing=_UNTRACKED_ROOT_LISTING)
        _reap(_args(reap=True), run_fn=git)
        deleted = [call for call in git.mutations if call[0] == "branch"]
        assert [call[-1] for call in deleted] == ["wip/renamed-branch"]


class TestARepositoryWithNoAgentWorktrees:
    """The ordinary case for anyone who has never dispatched one."""

    @staticmethod
    def _no_worktrees(cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
        if args[0] == "worktree":
            return subprocess.CompletedProcess([], 0, "worktree /repo\nHEAD aaa\n", "")
        # The orphaned-branch listing (Plan 00352) is asked for even here,
        # because a repository can hold branches after its worktrees are gone —
        # that IS the case that plan exists for. Empty means none.
        if args[0] == "branch" and "-d" not in args and "-D" not in args:
            return subprocess.CompletedProcess([], 0, "", "")
        raise AssertionError(f"nothing that changes state should be asked: {args}")

    def test_it_says_so_and_succeeds(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = _reap(_args(), run_fn=self._no_worktrees)
        assert exit_code == 0
        assert "No agent worktrees found" in capsys.readouterr().out


class TestActingOnOneWorktree:
    """Without this, a human wanting rid of ONE must take all fifteen."""

    def test_only_the_named_worktree_is_removed(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _reap(_args(reap=True, only="agent-clean-1"), run_fn=git)
        removed = [call for call in git.mutations if call[0] == "worktree"]
        assert len(removed) == 1
        assert "agent-clean-1" in removed[0][2]

    def test_naming_a_worktree_the_predicate_refuses_removes_nothing(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Naming one is a choice of TARGET, never an override of the check."""
        _reap(_args(reap=True, only="agent-dirty-2"), run_fn=git)
        assert git.mutations == []

    def test_an_unknown_name_is_an_error_not_a_silent_no_op(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A typo that quietly does nothing reads exactly like success."""
        exit_code = _reap(_args(reap=True, only="agent-typo-9"), run_fn=git)
        assert exit_code != 0
        assert git.mutations == []
        assert "agent-typo-9" in capsys.readouterr().out

    def test_the_report_narrows_too(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _reap(_args(only="agent-clean-1"), run_fn=git)
        out = capsys.readouterr().out
        assert "agent-clean-1" in out
        assert "agent-dirty-2" not in out


class TestTheExitCode:
    def test_zero_when_nothing_is_refused(self, capsys: pytest.CaptureFixture[str]) -> None:
        class _AllClean(_FakeGit):
            def __call__(
                self, cwd: Path, *args: str, **kw: object
            ) -> subprocess.CompletedProcess[str]:
                if args[0] == "status":
                    return subprocess.CompletedProcess([], 0, "", "")
                if args[0] in {"rev-list"}:
                    return subprocess.CompletedProcess([], 0, "0\n", "")
                if args[0] == "cherry":
                    return subprocess.CompletedProcess([], 0, "", "")
                return super().__call__(cwd, *args, **kw)

        assert _reap(_args(), run_fn=_AllClean()) == 0

    def test_nonzero_when_something_needs_a_human(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The refusals are the actionable output, so they must be visible."""
        assert _reap(_args(), run_fn=git) == 1
