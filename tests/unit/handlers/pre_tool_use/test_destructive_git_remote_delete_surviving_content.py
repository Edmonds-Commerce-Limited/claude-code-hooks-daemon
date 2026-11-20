"""R-GIT-PUSH-DELETE-REMOTE: an unmerged branch whose every file exists on main is deletable.

The proof is the shared `prove_remote_merged` surviving-content tier. A branch with a
file found nowhere else stays human-only, and a branch deleted in the same command
(or in a chained second push) never vouches for another's content.
"""

from pathlib import Path
from typing import Any

import pytest
from tests.support.git_fixtures import run_git

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """`dup` and `novel` are unmerged; main holds dup's file but not novel's."""
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
    for name in ("dup", "novel"):
        run_git(work, "checkout", "-q", "-b", name, "main")
        (work / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
        run_git(work, "add", f"{name}.txt")
        run_git(work, "commit", "-m", name)
        run_git(work, "push", "-u", "origin", name)
        run_git(work, "checkout", "-q", "main")
    # Main gets dup's file by an independent commit (not a merge of dup).
    (work / "dup.txt").write_text("dup\n", encoding="utf-8")
    run_git(work, "add", "dup.txt")
    run_git(work, "commit", "-m", "same file, independent commit")
    run_git(work, "push", "origin", "main")
    run_git(work, "fetch", "origin")
    return work


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def test_an_unmerged_branch_whose_file_exists_on_main_is_allowed(clone: Path) -> None:
    result = DestructiveGitHandler().handle(_input("git push origin --delete dup", clone))
    assert result.decision == "allow", result.reason


@pytest.fixture
def line_clone(clone: Path) -> Path:
    """`release/1` and `feat` both hold `shared.txt`, which main does not."""
    for name in ("release/1", "feat"):
        run_git(clone, "checkout", "-q", "-b", name, "main")
        (clone / "shared.txt").write_text("shared\n", encoding="utf-8")
        run_git(clone, "add", "shared.txt")
        run_git(clone, "commit", "-m", f"{name} has shared")
        run_git(clone, "push", "-u", "origin", name)
        run_git(clone, "checkout", "-q", "main")
    run_git(clone, "fetch", "origin")
    return clone


def _lines_handler() -> DestructiveGitHandler:
    handler = DestructiveGitHandler()
    handler._branches = BranchesConfig(integration_lines=["release/*"])
    return handler


def test_a_line_holding_the_file_vouches_when_it_is_not_deleted(line_clone: Path) -> None:
    result = _lines_handler().handle(_input("git push origin --delete feat", line_clone))
    assert result.decision == "allow", result.reason


def test_chained_pushes_deleting_a_branch_and_its_vouching_line_are_denied(
    line_clone: Path,
) -> None:
    """Each push is judged alone it would pass; together neither copy of `shared.txt` survives."""
    command = "git push origin :feat && git push origin :release/1"
    result = _lines_handler().handle(_input(command, line_clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert "shared.txt" in result.reason


def test_a_branch_with_a_file_found_nowhere_else_is_denied_naming_the_file(clone: Path) -> None:
    result = DestructiveGitHandler().handle(_input("git push origin --delete novel", clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert "novel.txt" in result.reason
    assert "surviving ref" in result.reason
