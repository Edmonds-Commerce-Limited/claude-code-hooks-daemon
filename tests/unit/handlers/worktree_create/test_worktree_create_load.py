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


class _AddScript:
    """A ``run_git`` stand-in whose Nth ``worktree add`` follows a script.

    Each entry is ``"timeout"`` (killed part-way, leaving a partial directory),
    ``"error"`` (git refuses) or ``"real"`` (the real add). The load average
    reads ``loads[n]`` for the Nth add, so a test can make the host busy for
    the first attempt and idle for the retry.
    """

    def __init__(self, script: list[str], loads: list[float]) -> None:
        self.script = script
        self.loads = loads
        self.budgets: list[float] = []
        self.load = loads[0]

    def loadavg(self) -> tuple[float, float, float]:
        return (self.load, self.load, self.load)

    def __call__(
        self, cwd: Path, *args: str, timeout: float = 5.0
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] != ("worktree", "add"):
            return real_run_git(cwd, *args, timeout=timeout)
        attempt = len(self.budgets)
        self.budgets.append(timeout)
        if attempt + 1 < len(self.loads):
            self.load = self.loads[attempt + 1]
        step = self.script[attempt]
        if step == "real":
            return real_run_git(cwd, *args, timeout=timeout)
        if step == "error":
            return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: refused")
        return _timed_out_add(cwd, *args, timeout=timeout)


def _add_with(
    repo: Path, script: _AddScript, **options: float
) -> tuple[Path, subprocess.CalledProcessError | None]:
    path = repo / ".claude" / "worktrees" / "w"
    path.parent.mkdir(parents=True)
    raised: subprocess.CalledProcessError | None = None
    with (
        patch(f"{_HANDLER_MODULE}.run_git", side_effect=script),
        patch(_LOADAVG, side_effect=script.loadavg),
    ):
        try:
            WorktreeCreateHandler._git_worktree_add(str(repo), path, "wb", **options)
        except subprocess.CalledProcessError as exc:
            raised = exc
    return path, raised


class TestOneRetryOfATimedOutAdd:
    def test_a_timeout_is_retried_once_and_the_retry_can_succeed(self, repo: Path) -> None:
        script = _AddScript(["timeout", "real"], [0.1, 0.1])
        path, error = _add_with(repo, script)
        assert error is None
        assert len(script.budgets) == 2
        assert (path / "README.md").is_file()

    def test_the_retry_budget_comes_from_a_fresh_load_reading(self, repo: Path) -> None:
        script = _AddScript(["timeout", "real"], [700.0, 0.1])
        _add_with(repo, script)
        assert script.budgets == [Timeout.GIT_WORKTREE_ADD_MAX, Timeout.GIT_WORKTREE]

    def test_the_failed_attempt_is_undone_before_the_retry(self, repo: Path) -> None:
        seen: list[bool] = []

        class Probe(_AddScript):
            def __call__(
                self, cwd: Path, *args: str, timeout: float = 5.0
            ) -> subprocess.CompletedProcess[str]:
                if args[:2] == ("worktree", "add") and self.budgets:
                    seen.append((Path(args[-1]) / "partial.txt").exists())
                return super().__call__(cwd, *args, timeout=timeout)

        _add_with(repo, Probe(["timeout", "real"], [0.1, 0.1]))
        assert seen == [False]

    def test_another_git_error_is_never_retried(self, repo: Path) -> None:
        script = _AddScript(["error", "real"], [0.1, 0.1])
        _, error = _add_with(repo, script)
        assert error is not None
        assert len(script.budgets) == 1
        assert "retry was already made" not in str(error)

    def test_a_timeout_whose_undo_left_something_behind_is_not_retried(self, repo: Path) -> None:
        script = _AddScript(["timeout", "real"], [0.1, 0.1])
        with patch(f"{_HANDLER_MODULE}.shutil.rmtree", side_effect=OSError("busy")):
            _, error = _add_with(repo, script)
        assert error is not None
        assert len(script.budgets) == 1
        assert "left behind" in str(error)

    def test_two_timeouts_deny_saying_one_retry_was_already_made(self, repo: Path) -> None:
        script = _AddScript(["timeout", "timeout"], [0.1, 0.1])
        path, error = _add_with(repo, script)
        assert error is not None
        assert len(script.budgets) == 2
        assert "one automatic retry was already made" in str(error)
        assert "timed out" in str(error)
        assert not path.exists()

    def test_a_retry_that_fails_otherwise_still_says_it_was_made(self, repo: Path) -> None:
        script = _AddScript(["timeout", "error"], [0.1, 0.1])
        _, error = _add_with(repo, script)
        assert error is not None
        assert "one automatic retry was already made" in str(error)
        assert "refused" in str(error)


class TestAddBudgetOptions:
    def test_defaults_equal_the_constants(self) -> None:
        handler = WorktreeCreateHandler()
        assert handler._add_base_seconds == Timeout.GIT_WORKTREE
        assert handler._add_ceiling_seconds == Timeout.GIT_WORKTREE_ADD_MAX

    def test_the_configured_base_and_ceiling_are_used(self, repo: Path) -> None:
        busy = _AddScript(["error"], [700.0])
        _add_with(repo, busy, base=7, ceiling=9)
        assert busy.budgets == [9]

    def test_the_configured_base_is_used_on_an_idle_host(self, repo: Path) -> None:
        idle = _AddScript(["error"], [0.1])
        _add_with(repo, idle, base=7, ceiling=9)
        assert idle.budgets == [7]

    def test_handle_passes_its_options_to_the_add(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        handler._add_base_seconds = 11
        handler._add_ceiling_seconds = 13
        with (
            patch.object(WorktreeCreateHandler, "_git_worktree_add") as add,
            patch.object(WorktreeCreateHandler, "_judge_branch_cap"),
            patch(f"{_HANDLER_MODULE}.write_creator"),
        ):
            handler.handle({"cwd": str(repo), "name": "x", "prompt_id": "p", "session_id": "s"})
        assert add.call_args.kwargs == {"base": 11, "ceiling": 13}

    @pytest.mark.parametrize(
        ("options", "bad_keys"),
        [
            ({}, set()),
            ({"add_base_seconds": 10, "add_ceiling_seconds": 60}, set()),
            ({"add_base_seconds": 0}, {"add_base_seconds"}),
            ({"add_ceiling_seconds": -5}, {"add_ceiling_seconds"}),
            ({"add_base_seconds": "30"}, {"add_base_seconds"}),
            ({"add_base_seconds": True}, {"add_base_seconds"}),
            ({"add_base_seconds": 90, "add_ceiling_seconds": 60}, {"add_base_seconds"}),
            ({"add_ceiling_seconds": 10}, {"add_ceiling_seconds"}),
            ({"add_base_seconds": 500}, {"add_base_seconds"}),
            ({"add_ceiling_seconds": Timeout.GIT_WORKTREE_ADD_MAX + 1}, {"add_ceiling_seconds"}),
        ],
    )
    def test_validation(self, options: dict[str, object], bad_keys: set[str]) -> None:
        assert set(WorktreeCreateHandler.validate_options(options)) == bad_keys


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
