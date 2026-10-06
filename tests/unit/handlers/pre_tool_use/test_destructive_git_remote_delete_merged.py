"""Owner ruling D11 (niggle N362): deleting a MERGED remote branch is lossless.

`git push <remote> --delete <branch>` and `git push <remote> :<branch>` are allowed
when the branch's remote-tracking ref is an ancestor of the default branch, judged
from local git facts. Every other case -- unmerged, missing ref, tag, the default
branch itself, a doubt of any kind -- stays denied (human only).
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
    """A clone of a bare origin whose `main` holds one commit and `merged` is merged into it."""
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
    # merged: same tip as main (ancestor of it); unmerged: carries a commit main lacks.
    run_git(work, "push", "origin", "main:refs/heads/merged")
    run_git(work, "checkout", "-b", "unmerged")
    run_git(work, "commit", "--allow-empty", "-m", "only on unmerged")
    run_git(work, "push", "-u", "origin", "unmerged")
    run_git(work, "checkout", "main")
    run_git(work, "fetch", "origin")
    run_git(work, "tag", "v1")
    run_git(work, "push", "origin", "v1")
    return work


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


@pytest.mark.parametrize(
    "command",
    [
        "git push origin --delete merged",
        "git push --delete origin merged",
        "git push origin :merged",
        "git push -d origin merged",
        "git push origin --delete refs/heads/merged",
    ],
)
def test_deleting_a_merged_remote_branch_is_allowed(
    handler: DestructiveGitHandler, clone: Path, command: str
) -> None:
    hook_input = _input(command, clone)
    assert handler.matches(hook_input) is True
    assert handler.handle(hook_input).decision == "allow"


@pytest.mark.parametrize(
    "command", ["git push origin --delete unmerged", "git push origin :unmerged"]
)
def test_deleting_an_unmerged_remote_branch_is_denied_and_says_so(
    handler: DestructiveGitHandler, clone: Path, command: str
) -> None:
    result = handler.handle(_input(command, clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert RuleID.GIT_PUSH_DELETE_REMOTE in result.reason
    assert "unmerged" in result.reason
    assert "not merged" in result.reason
    assert "may be deleted" in result.reason
    assert "ask the human" in result.reason.lower()


@pytest.mark.parametrize(
    "command",
    [
        "git push origin --delete nonesuch",
        "git push origin :nonesuch",
        "git push nowhere --delete merged",
    ],
)
def test_a_missing_remote_tracking_ref_is_denied(
    handler: DestructiveGitHandler, clone: Path, command: str
) -> None:
    assert handler.handle(_input(command, clone)).decision == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "git push origin --delete v1",
        "git push origin :v1",
        "git push origin --delete refs/tags/v1",
        "git push origin :refs/tags/v1",
    ],
)
def test_deleting_a_tag_stays_denied(
    handler: DestructiveGitHandler, clone: Path, command: str
) -> None:
    assert handler.handle(_input(command, clone)).decision == "deny"


def test_a_branch_sharing_its_name_with_a_tag_is_denied(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    run_git(clone, "tag", "merged")
    assert handler.handle(_input("git push origin --delete merged", clone)).decision == "deny"


def test_the_default_branch_is_never_deletable(handler: DestructiveGitHandler, clone: Path) -> None:
    assert handler.handle(_input("git push origin --delete main", clone)).decision == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "git push origin --delete merged unmerged",
        "git push origin :merged :unmerged",
        "git push origin --delete merged v1",
    ],
)
def test_every_ref_must_be_merged(
    handler: DestructiveGitHandler, clone: Path, command: str
) -> None:
    assert handler.handle(_input(command, clone)).decision == "deny"


def test_several_merged_refs_are_allowed(handler: DestructiveGitHandler, clone: Path) -> None:
    run_git(clone, "push", "origin", "main:refs/heads/also-merged")
    run_git(clone, "fetch", "origin")
    result = handler.handle(_input("git push origin --delete merged also-merged", clone))
    assert result.decision == "allow"


def test_a_merged_delete_cannot_carry_a_force_push_along(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    result = handler.handle(_input("git push --force origin --delete merged", clone))
    assert result.decision == "deny"


def test_a_merged_delete_chained_with_an_unmerged_one_is_denied(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    command = "git push origin --delete merged && git push origin --delete unmerged"
    assert handler.handle(_input(command, clone)).decision == "deny"


def test_a_substitution_is_not_trusted(handler: DestructiveGitHandler, clone: Path) -> None:
    result = handler.handle(_input("git push origin --delete $(echo unmerged)", clone))
    assert result.decision == "deny"


def test_an_unknown_directory_is_denied(handler: DestructiveGitHandler, tmp_path: Path) -> None:
    assert handler.handle(_input("git push origin --delete merged", tmp_path)).decision == "deny"


def _push_from_second_clone(clone: Path, branch: str) -> None:
    """Advance origin's ``branch`` from another clone, leaving ``clone``'s tracking ref stale."""
    origin = clone.parent / "origin.git"
    other = clone.parent / "other"
    run_git(clone.parent, "clone", "-q", str(origin), str(other))
    run_git(other, "config", "user.email", "t@example.invalid")
    run_git(other, "config", "user.name", "Tester")
    run_git(other, "config", "commit.gpgsign", "false")
    run_git(other, "checkout", branch)
    run_git(other, "commit", "--allow-empty", "-m", "pushed after our last fetch")
    run_git(other, "push", "origin", branch)


@pytest.mark.parametrize("command", ["git push origin --delete merged", "git push origin :merged"])
def test_a_stale_tracking_ref_is_denied_and_says_to_fetch(
    handler: DestructiveGitHandler, clone: Path, command: str
) -> None:
    _push_from_second_clone(clone, "merged")
    result = handler.handle(_input(command, clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert "could not be confirmed as merged" in result.reason
    assert "git fetch" in result.reason


def test_a_fetched_tracking_ref_that_is_now_unmerged_is_denied(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    _push_from_second_clone(clone, "merged")
    run_git(clone, "fetch", "origin")
    assert handler.handle(_input("git push origin --delete merged", clone)).decision == "deny"


def test_a_branch_already_gone_from_the_remote_is_denied(
    handler: DestructiveGitHandler, clone: Path
) -> None:
    run_git(clone.parent / "origin.git", "branch", "-D", "merged")
    result = handler.handle(_input("git push origin --delete merged", clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert "git fetch" in result.reason


def test_an_unreachable_remote_is_denied(handler: DestructiveGitHandler, clone: Path) -> None:
    run_git(clone, "remote", "set-url", "origin", str(clone.parent / "nowhere.git"))
    result = handler.handle(_input("git push origin --delete merged", clone))
    assert result.decision == "deny"
    assert result.reason is not None
    assert "could not be confirmed as merged" in result.reason


def test_the_rule_documentation_describes_the_merged_exception(
    handler: DestructiveGitHandler,
) -> None:
    claude_md = handler.get_claude_md() or ""
    assert "already merged" in claude_md
    rule = next(r for r in handler.get_rules() if r.rule_id == RuleID.GIT_PUSH_DELETE_REMOTE)
    assert "merged" in rule.blocked.lower() or "merged" in rule.fix.lower()
