"""WorktreeCreate under host load: a timed-out add is undone cleanly and says why."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.handlers.worktree_create.worktree_create_handler import (
    WorktreeCreateHandler,
    _WorktreeAddError,
)
from claude_code_hooks_daemon.utils.git_repo import GIT_TIMED_OUT
from claude_code_hooks_daemon.utils.git_repo import run_git as real_run_git

_HANDLER_MODULE = "claude_code_hooks_daemon.handlers.worktree_create.worktree_create_handler"
_LOADAVG = "claude_code_hooks_daemon.utils.load_scaling.os.getloadavg"

_RunGit = Callable[..., "subprocess.CompletedProcess[str]"]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    return root


def _timed_out_add(cwd: Path, *args: str, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    """Stand in for git killed part-way through populating a checkout."""
    if args[:2] == ("worktree", "add"):
        target = Path(args[-1])
        target.mkdir(parents=True)
        (target / "partial.txt").write_text("x", encoding="utf-8")
        return subprocess.CompletedProcess(["git", *args], GIT_TIMED_OUT, "", "timed out")
    return real_run_git(cwd, *args, timeout=timeout)


def _recording_failure(budgets: list[float]) -> _RunGit:
    def record(cwd: Path, *args: str, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "add"):
            budgets.append(timeout)
        return subprocess.CompletedProcess(["git", *args], 1, "", "boom")

    return record


class TestAddBudgetFollowsHostLoad:
    def test_a_heavily_loaded_host_gets_the_ceiling(self, repo: Path) -> None:
        budgets: list[float] = []
        with (
            patch(f"{_HANDLER_MODULE}.run_git", side_effect=_recording_failure(budgets)),
            patch(_LOADAVG, return_value=(700.0, 700.0, 700.0)),
            pytest.raises(subprocess.CalledProcessError),
        ):
            WorktreeCreateHandler._git_worktree_add(str(repo), repo / "w", "b")
        assert budgets == [Timeout.GIT_WORKTREE_ADD_MAX]

    def test_an_idle_host_keeps_the_base_budget(self, repo: Path) -> None:
        budgets: list[float] = []
        with (
            patch(f"{_HANDLER_MODULE}.run_git", side_effect=_recording_failure(budgets)),
            patch(_LOADAVG, return_value=(0.1, 0.1, 0.1)),
            pytest.raises(subprocess.CalledProcessError),
        ):
            WorktreeCreateHandler._git_worktree_add(str(repo), repo / "w", "b")
        assert budgets == [Timeout.GIT_WORKTREE]


class TestTimedOutAdd:
    def _run(self, repo: Path) -> tuple[Path, subprocess.CalledProcessError]:
        path = repo / ".claude" / "worktrees" / "w"
        path.parent.mkdir(parents=True)
        with (
            patch(f"{_HANDLER_MODULE}.run_git", side_effect=_timed_out_add),
            pytest.raises(subprocess.CalledProcessError) as excinfo,
        ):
            WorktreeCreateHandler._git_worktree_add(str(repo), path, "wb")
        return path, excinfo.value

    def test_leaves_no_directory_and_no_branch(self, repo: Path) -> None:
        path, error = self._run(repo)
        assert not path.exists()
        branches = subprocess.run(
            ["git", "-C", str(repo), "branch", "--format=%(refname:short)"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert "wb" not in branches
        assert "worktree left behind" not in str(error)

    def test_the_error_names_the_timeout_the_load_and_the_retry(self, repo: Path) -> None:
        _, error = self._run(repo)
        text = str(error)
        assert "timed out" in text
        assert "load average" in text
        assert "retry" in text
        assert isinstance(error, _WorktreeAddError)
        assert error.deny_detail == text

    def test_the_timeout_is_logged_with_the_load_average(
        self, repo: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            self._run(repo)
        assert any(
            "timed out" in r.getMessage() and "load average" in r.getMessage()
            for r in caplog.records
        )


class TestUnregisteredPartialDirectory:
    """git does not know a half-made checkout, so the handler deletes the one it created."""

    def test_is_removed(self, repo: Path) -> None:
        path = repo / ".claude" / "worktrees" / "w"
        path.mkdir(parents=True)
        (path / "partial.txt").write_text("x", encoding="utf-8")

        assert WorktreeCreateHandler._undo_failed_add(str(repo), path, "wb", False) == ""
        assert not path.exists()

    def test_one_that_cannot_be_deleted_is_named_as_left_behind(self, repo: Path) -> None:
        path = repo / ".claude" / "worktrees" / "w"
        path.mkdir(parents=True)
        with patch(f"{_HANDLER_MODULE}.shutil.rmtree", side_effect=OSError("busy")):
            left = WorktreeCreateHandler._undo_failed_add(str(repo), path, "wb", False)
        assert str(path) in left

    def test_a_missing_directory_is_not_an_error(self, repo: Path) -> None:
        path = repo / ".claude" / "worktrees" / "never-made"
        assert WorktreeCreateHandler._undo_failed_add(str(repo), path, "wb", False) == ""


class TestChainDenyNamesTheCause:
    def test_a_crash_with_a_deny_detail_puts_it_in_the_reason(self, repo: Path) -> None:
        class Boom(RuntimeError):
            deny_detail = "timed out under load; retry once it drops"

        chain = HandlerChain()
        chain.add(WorktreeCreateHandler())
        with patch.object(WorktreeCreateHandler, "handle", side_effect=Boom("x")):
            result = chain.execute({"cwd": str(repo)}, strict_mode=True)
        assert "timed out under load" in str(result.result.reason)
