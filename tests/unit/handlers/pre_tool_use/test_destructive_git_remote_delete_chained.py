"""Niggle N578: a merged branch's remote delete is judged the same when chained.

`git worktree remove <wt> && ... && git push -q origin --delete <b>` matches the
worktree-removal rule as well as the remote-delete rule. The remote delete must still be
judged on its own proof, and every deny of it must name the branch and the reason.
"""

from pathlib import Path
from typing import Any

import pytest
from tests.support.git_fixtures import run_git

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    """The disclosure tracker is a process-wide singleton; isolate each test."""
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone whose `merged` and `unmerged` branches are pushed, each with a clean worktree."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    run_git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    run_git(tmp_path, "init", "--initial-branch=main", str(work))
    run_git(work, "config", "user.email", "t@example.invalid")
    run_git(work, "config", "user.name", "Tester")
    run_git(work, "config", "commit.gpgsign", "false")
    run_git(work, "remote", "add", "origin", str(origin))
    run_git(work, "commit", "--allow-empty", "-m", "base")
    run_git(work, "push", "-u", "origin", "main")
    run_git(work, "remote", "set-head", "origin", "main")
    run_git(work, "branch", "merged")
    run_git(work, "push", "-u", "origin", "merged")
    run_git(work, "worktree", "add", str(tmp_path / "wt-merged"), "merged")
    run_git(work, "worktree", "add", "-b", "unmerged", str(tmp_path / "wt-unmerged"))
    run_git(tmp_path / "wt-unmerged", "commit", "--allow-empty", "-m", "only on unmerged")
    run_git(tmp_path / "wt-unmerged", "push", "-u", "origin", "unmerged")
    run_git(work, "fetch", "origin")
    return work


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _chain(clone: Path, branch: str) -> list[str]:
    worktree = clone.parent / f"wt-{branch}"
    delete = f"bin/hooks-daemon delete-branch {branch} --protected-ref main"
    push = f"git push -q origin --delete {branch}"
    return [
        f"git worktree remove {worktree} && {delete} && {push}",
        f"git worktree remove {worktree} && {push}",
        f"git worktree remove {worktree} && git branch -D {branch} && {push}",
        f"git worktree remove {worktree}; {delete}; {push}",
    ]


@pytest.mark.parametrize("index", range(4))
def test_a_merged_remote_delete_is_allowed_when_chained_after_cleanup(
    handler: DestructiveGitHandler, clone: Path, index: int
) -> None:
    command = _chain(clone, "merged")[index]
    hook_input = _input(command, clone)
    assert handler.matches(hook_input) is True
    result = handler.handle(hook_input)
    assert result.decision == "allow", result.reason


@pytest.mark.parametrize("index", range(4))
def test_an_unmerged_remote_delete_chained_after_cleanup_names_its_reason(
    handler: DestructiveGitHandler, clone: Path, index: int
) -> None:
    result = handler.handle(_input(_chain(clone, "unmerged")[index], clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert RuleID.GIT_PUSH_DELETE_REMOTE in result.reason
    assert "`unmerged` is not merged into `main`" in result.reason


def test_a_denied_push_delete_chained_with_a_destructive_rule_names_its_reason(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    command = "git reset --hard && git push origin --delete unmerged"
    result = handler.handle(_input(command, clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert RuleID.GIT_RESET_HARD in result.reason
    assert "`unmerged` is not merged into `main`" in result.reason


def test_a_merged_push_delete_cannot_ride_along_with_a_destructive_rule(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    command = "git reset --hard && git push origin --delete merged"
    assert handler.handle(_input(command, clone)).decision == "deny"


def test_a_lossy_worktree_removal_chained_with_a_merged_delete_stays_denied(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    (clone.parent / "wt-merged" / "dirty.txt").write_text("unsaved")
    command = f"git worktree remove {clone.parent / 'wt-merged'} && git push origin --delete merged"
    result = handler.handle(_input(command, clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert RuleID.GIT_WORKTREE_REMOVE_FORCE in result.reason


def test_tags_mirror_and_prune_stay_denied_when_chained(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    worktree = clone.parent / "wt-merged"
    for tail in (
        "git push origin --delete v1",
        "git push --mirror origin",
        "git push --prune origin",
    ):
        result = handler.handle(_input(f"git worktree remove {worktree} && {tail}", clone))
        assert result.decision == "deny", tail
