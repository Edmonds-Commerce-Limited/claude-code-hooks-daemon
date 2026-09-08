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

from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap

_LISTING = """worktree /repo
HEAD aaa

worktree /repo/.claude/worktrees/agent-clean-1
HEAD bbb

worktree /repo/.claude/worktrees/agent-dirty-2
HEAD ccc
"""


class _FakeGit:
    """A repo with one reapable worktree and one the predicate refuses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cwd: Path, *args: str, **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        dirty = "agent-dirty-2" in str(cwd)
        if args[0] == "worktree" and args[1] == "list":
            return subprocess.CompletedProcess([], 0, _LISTING, "")
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
        return [
            call
            for call in self.calls
            if call[0] == "branch" or (call[0] == "worktree" and call[1] == "remove")
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


@pytest.fixture
def git() -> _FakeGit:
    return _FakeGit()


class TestTheDefaultChangesNothing:
    def test_no_worktree_or_branch_is_removed_without_the_flag(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(), run_fn=git)
        assert git.mutations == []

    def test_it_still_says_what_it_would_do(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(), run_fn=git)
        out = capsys.readouterr().out
        assert "agent-clean-1" in out
        assert "would remove" in out.lower()

    def test_it_explains_each_refusal_rather_than_just_omitting_it(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A worktree that silently vanishes from the report looks handled."""
        cmd_worktree_reap(_args(), run_fn=git)
        out = capsys.readouterr().out
        assert "agent-dirty-2" in out
        assert "not safe to reap" in out


class TestActingRequiresTheFlag:
    def test_only_the_cleared_worktree_is_removed(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(reap=True), run_fn=git)
        removed = [call for call in git.mutations if call[0] == "worktree"]
        assert len(removed) == 1
        assert "agent-clean-1" in removed[0][2]

    def test_the_refused_worktree_gets_no_git_command(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(reap=True), run_fn=git)
        assert not any("agent-dirty-2" in " ".join(call) for call in git.mutations)

    def test_its_branch_goes_too(self, git: _FakeGit, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_worktree_reap(_args(reap=True), run_fn=git)
        assert any(call[0] == "branch" and "-d" in call for call in git.mutations)


class TestActingOnOneWorktree:
    """Without this, a human wanting rid of ONE must take all fifteen."""

    def test_only_the_named_worktree_is_removed(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(reap=True, only="agent-clean-1"), run_fn=git)
        removed = [call for call in git.mutations if call[0] == "worktree"]
        assert len(removed) == 1
        assert "agent-clean-1" in removed[0][2]

    def test_naming_a_worktree_the_predicate_refuses_removes_nothing(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Naming one is a choice of TARGET, never an override of the check."""
        cmd_worktree_reap(_args(reap=True, only="agent-dirty-2"), run_fn=git)
        assert git.mutations == []

    def test_an_unknown_name_is_an_error_not_a_silent_no_op(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A typo that quietly does nothing reads exactly like success."""
        exit_code = cmd_worktree_reap(_args(reap=True, only="agent-typo-9"), run_fn=git)
        assert exit_code != 0
        assert git.mutations == []
        assert "agent-typo-9" in capsys.readouterr().out

    def test_the_report_narrows_too(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_worktree_reap(_args(only="agent-clean-1"), run_fn=git)
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

        assert cmd_worktree_reap(_args(), run_fn=_AllClean()) == 0

    def test_nonzero_when_something_needs_a_human(
        self, git: _FakeGit, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The refusals are the actionable output, so they must be visible."""
        assert cmd_worktree_reap(_args(), run_fn=git) == 1
