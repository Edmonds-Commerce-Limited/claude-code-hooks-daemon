"""Plan 00594 Task 3.2: the remote-delete guard accepts every offline kind of merge proof.

The guard uses the same proof as ``branch-sweep --clean --remote`` (ancestry, then
patch-id, then tree containment), so an agent may delete a remote branch that was
squash-merged or cherry-picked, and still may not delete one carrying work the
default never took.
"""

from pathlib import Path
from typing import Any

import pytest
from tests.support.git_fixtures import run_git

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _commit_file(work: Path, name: str) -> None:
    (work / name).write_text(f"{name}\n", encoding="utf-8")
    run_git(work, "add", name)
    run_git(work, "commit", "-m", f"add {name}")


def _topic(work: Path, name: str, files: list[str]) -> None:
    run_git(work, "checkout", "-b", name, "main")
    for filename in files:
        _commit_file(work, filename)
    run_git(work, "push", "-u", "origin", name)
    run_git(work, "checkout", "main")


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    run_git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    run_git(tmp_path, "init", "--initial-branch=main", str(work))
    run_git(work, "config", "user.email", "t@example.invalid")
    run_git(work, "config", "user.name", "Tester")
    run_git(work, "config", "commit.gpgsign", "false")
    run_git(work, "remote", "add", "origin", str(origin))
    _commit_file(work, "base.txt")
    run_git(work, "push", "-u", "origin", "main")
    run_git(work, "remote", "set-head", "origin", "main")
    _topic(work, "squashed", ["s1.txt", "s2.txt", "s3.txt"])
    _topic(work, "picked", ["p1.txt", "p2.txt"])
    _topic(work, "extra", ["e1.txt", "e2.txt"])
    run_git(work, "merge", "--squash", "squashed")
    run_git(work, "commit", "-m", "squash the topic")
    _commit_file(work, "unrelated.txt")
    run_git(work, "cherry-pick", "main..picked")
    # `extra` is taken only up to its first commit, squashed.
    run_git(work, "merge", "--squash", "extra~1")
    run_git(work, "commit", "-m", "squash the first commit of extra")
    run_git(work, "push", "origin", "main")
    return work


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


@pytest.mark.parametrize("branch", ["squashed", "picked"])
def test_a_squash_merged_or_cherry_picked_remote_branch_may_be_deleted(
    handler: DestructiveGitHandler, clone: Path, branch: str
) -> None:
    assert handler.handle(_input(f"git push origin --delete {branch}", clone)).decision == "allow"


def test_a_remote_branch_with_one_commit_main_never_took_is_denied(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    result = handler.handle(_input("git push origin --delete extra", clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert "not merged" in result.reason
