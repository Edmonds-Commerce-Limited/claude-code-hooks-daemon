"""Tests for the cleanup_after_merge PostToolUse handler (Plan 00558 Task 3.1).

Real repositories: the subject is a real merge and git's own reachability.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.cleanup_after_merge import (
    CleanupAfterMergeHandler,
    merge_operands,
)

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


def _branches(repo: Path) -> set[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    return {line.removeprefix("refs/heads/") for line in out.splitlines() if line}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-m", "Initial commit")
    return path


def _merge(repo: Path, name: str) -> str:
    _git(repo, "checkout", "-b", name)
    (repo / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", f"{name}.txt")
    _git(repo, "commit", "-m", f"Add {name}")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "-m", f"Merge {name}", name)
    return _git(repo, "rev-parse", f"refs/heads/{name}").strip()


def _handler(mode: str = "act") -> CleanupAfterMergeHandler:
    handler = CleanupAfterMergeHandler()
    handler._branches = BranchesConfig.model_validate(
        {"default": "main", "cleanup_after_merge": {"mode": mode}}
    )
    return handler


def _input(command: str, cwd: Path | None = None, tool: str = "Bash") -> dict[str, Any]:
    hook_input: dict[str, Any] = {"tool_name": tool, "tool_input": {"command": command}}
    if cwd is not None:
        hook_input["cwd"] = str(cwd)
    return hook_input


class TestIdentity:
    def test_identity_priority_and_non_terminal(self) -> None:
        handler = CleanupAfterMergeHandler()
        assert handler.handler_id == HandlerID.CLEANUP_AFTER_MERGE
        assert handler.priority == Priority.CLEANUP_AFTER_MERGE
        assert handler.terminal is False

    def test_guidance_and_acceptance_test(self) -> None:
        handler = CleanupAfterMergeHandler()
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "cleanup_after_merge" in guidance
        tests = handler.get_acceptance_tests()
        assert len(tests) == 1
        assert tests[0].harness_cannot_produce


class TestMergeOperands:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("git merge feat", ["feat"]),
            ("git merge --no-ff -m 'Merge feat' feat", ["feat"]),
            ("git merge -s ort -X theirs a b", ["a", "b"]),
            ("git merge --message=done --no-edit feat", ["feat"]),
            ("git -C /x merge feat && git push", ["feat"]),
            ("git merge --squash feat", []),
            ("git merge --abort", []),
            ("git merge --continue", []),
            ("git merge --no-commit feat", []),
            ("git status", []),
            ("echo git merge feat", []),
            ("git status && git merge feat", ["feat"]),
            ("git pull origin main", []),
        ],
    )
    def test_operands(self, command: str, expected: list[str]) -> None:
        assert merge_operands(command) == expected


class TestMatches:
    def test_matches_a_merge(self) -> None:
        assert _handler().matches(_input("git merge --no-ff feat")) is True

    def test_ignores_a_squash_and_other_tools(self) -> None:
        assert _handler().matches(_input("git merge --squash feat")) is False
        assert _handler().matches(_input("git merge feat", tool="Read")) is False
        assert _handler().matches(_input("")) is False

    def test_off_never_matches(self) -> None:
        assert _handler("off").matches(_input("git merge feat")) is False


class TestHandle:
    def test_act_deletes_the_merged_branch_and_prints_the_restore_line(self, repo: Path) -> None:
        tip = _merge(repo, "feat")
        result = _handler("act").handle(_input("git merge --no-ff feat", repo))
        assert result.decision == Decision.ALLOW
        assert "feat" not in _branches(repo)
        text = "\n".join(result.context)
        assert f"git branch feat {tip}" in text
        assert "Deleted branch(es): feat" in text

    def test_advise_keeps_the_branch_and_prints_the_delete_command(self, repo: Path) -> None:
        _merge(repo, "feat")
        result = _handler("advise").handle(_input("git merge feat", repo))
        assert "feat" in _branches(repo)
        assert "delete-branch feat" in "\n".join(result.context)

    def test_a_merge_into_a_work_branch_earns_nothing(self, repo: Path) -> None:
        _merge(repo, "feat")
        _git(repo, "checkout", "-b", "other")
        result = _handler("act").handle(_input("git merge feat", repo))
        assert result.context == []
        assert "feat" in _branches(repo)

    def test_a_non_branch_operand_is_ignored(self, repo: Path) -> None:
        tip = _merge(repo, "feat")
        result = _handler("act").handle(_input(f"git merge {tip}", repo))
        assert result.context == []
        assert "feat" in _branches(repo)

    def test_a_detached_head_earns_nothing(self, repo: Path) -> None:
        _merge(repo, "feat")
        _git(repo, "checkout", "--detach")
        assert _handler("act").handle(_input("git merge feat", repo)).context == []

    def test_outside_a_repository_is_silent(self, tmp_path: Path) -> None:
        assert _handler("act").handle(_input("git merge feat", tmp_path)).context == []

    def test_off_reached_directly_is_silent(self, repo: Path) -> None:
        _merge(repo, "feat")
        assert _handler("off").handle(_input("git merge feat", repo)).context == []
        assert "feat" in _branches(repo)

    def test_no_cwd_is_silent(self) -> None:
        assert _handler("act").handle(_input("git merge feat")).context == []

    def test_a_merge_placed_by_git_dash_c_is_cleaned_there(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _merge(repo, "feat")
        result = _handler("act").handle(_input(f"git -C {repo} merge feat", tmp_path))
        assert "feat" not in _branches(repo)
        assert result.context

    def test_a_git_failure_is_reported_not_raised(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _merge(repo, "feat")
        from claude_code_hooks_daemon.handlers.post_tool_use import cleanup_after_merge as module

        def boom(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("git worktree list failed: boom")

        monkeypatch.setattr(module, "cleanup_after_merge", boom)
        result = _handler("act").handle(_input("git merge feat", repo))
        assert result.decision == Decision.ALLOW
        assert "boom" in "\n".join(result.context)
        assert "feat" in _branches(repo)


class TestPoolClearCommandAfterMerge:
    """Plan 00594 Task 4.2: after a merge the advisory names the command that clears the pool."""

    def test_full_merged_pool_names_the_sweep_command(self, repo: Path) -> None:
        _git(repo, "branch", "old-done", "main")
        _merge(repo, "feat")
        handler = CleanupAfterMergeHandler()
        handler._branches = BranchesConfig.model_validate(
            {"default": "main", "cleanup_after_merge": {"mode": "advise"}, "merged": {"cap": 1}}
        )
        result = handler.handle(_input("git merge --no-ff feat", repo))
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "branch-sweep" in text
        assert "--clean" in text

    def test_no_pool_line_when_the_merged_pool_has_room(self, repo: Path) -> None:
        _merge(repo, "feat")
        result = _handler("advise").handle(_input("git merge --no-ff feat", repo))
        assert "branch-sweep" not in "\n".join(result.context)
