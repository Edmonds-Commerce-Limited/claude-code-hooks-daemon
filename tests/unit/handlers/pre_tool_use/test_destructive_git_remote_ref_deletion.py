"""Plan 00483 Task 2.2, owner ruling A6: deleting a ref on the REMOTE is human-only.

`git push --delete <name>` and `git push <remote> :<name>` remove a branch or tag
from the shared repository, where no local reflog can bring it back. The local
siblings (`git tag -d`, `git reset --keep`) stay allowed.
"""

from typing import Any

import pytest

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


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.mark.parametrize(
    "command",
    [
        "git push origin --delete feature",
        "git push --delete origin feature",
        "git push -d origin feature",
        "git push origin :feature",
        "git push origin :refs/tags/v1.0.0",
        "git -C /srv/repo push origin --delete feature",
        "git fetch && git push origin :feature",
        "bash -c 'git push origin --delete feature'",
        "git push -ud origin feature",
    ],
)
def test_remote_ref_deletion_is_denied(handler: DestructiveGitHandler, command: str) -> None:
    hook_input = _bash(command)
    assert handler.matches(hook_input) is True
    result = handler.handle(hook_input)
    assert result.decision == "deny"
    assert RuleID.GIT_PUSH_DELETE_REMOTE in result.reason


@pytest.mark.parametrize(
    "command",
    [
        "git push --mirror origin",
        "git push origin --mirror",
        "git push --prune origin 'refs/heads/*:refs/heads/*'",
        "git push origin --prune 'refs/heads/*:refs/heads/*'",
        "git -C /srv/repo push --mirror origin",
        "git fetch && git push --mirror backup",
        "bash -c 'git push --prune origin refs/heads/*:refs/heads/*'",
    ],
)
def test_mirror_and_prune_pushes_delete_remote_refs_so_they_are_human_only(
    handler: DestructiveGitHandler, command: str
) -> None:
    hook_input = _bash(command)
    assert handler.matches(hook_input) is True
    result = handler.handle(hook_input)
    assert result.decision == "deny"
    assert RuleID.GIT_PUSH_DELETE_REMOTE in result.reason


@pytest.mark.parametrize(
    "command",
    [
        "git push --delete --mirror origin merged",
        "git push --prune --delete origin merged",
    ],
)
def test_the_merged_branch_allowance_never_covers_mirror_or_prune(
    handler: DestructiveGitHandler, command: str
) -> None:
    result = handler.handle(_bash(command))
    assert result.decision == "deny"
    assert "could not be verified" in result.reason


@pytest.mark.parametrize(
    "command",
    [
        "git fetch --prune origin",
        "git remote prune origin",
        "git push origin --mirror-not-a-flag",
        "git push origin prune-branch",
        "git push origin main; echo --mirror",
        "echo 'git push --mirror origin'",
    ],
)
def test_prune_and_mirror_neighbours_stay_allowed(
    handler: DestructiveGitHandler, command: str
) -> None:
    assert handler.matches(_bash(command)) is False


def test_the_denial_says_a_human_runs_it_and_offers_no_hatch(
    handler: DestructiveGitHandler,
) -> None:
    reason = handler.handle(_bash("git push origin --delete feature")).reason
    assert reason is not None
    assert "ask the human" in reason.lower()
    assert "MUST_" not in reason


def test_the_force_push_rule_still_wins_when_both_apply(handler: DestructiveGitHandler) -> None:
    result = handler.handle(_bash("git push --force origin --delete feature"))
    assert result.decision == "deny"


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git push -u origin feature",
        "git push origin feature:feature",
        "git push origin HEAD:refs/heads/feature",
        "git push --follow-tags origin main",
        "git push origin feature-d",
        "git push origin my-delete-branch",
        "git tag -d v1",
        "git branch -d merged-feature",
        "git reset --keep HEAD~1",
        "git reset --merge",
        "git push origin main; echo --delete",
        "git push origin main && grep -d skip notes.txt",
        "echo 'git push origin --delete feature'",
        "git commit -m 'document git push origin --delete feature'",
        "grep -n 'push origin :feature' notes.md",
        "cat <<'EOF'\ngit push origin :feature\nEOF",
    ],
)
def test_ordinary_neighbours_and_prose_are_allowed(
    handler: DestructiveGitHandler, command: str
) -> None:
    assert handler.matches(_bash(command)) is False


def test_the_rule_is_declared_and_points_at_the_human(handler: DestructiveGitHandler) -> None:
    rule = {r.rule_id: r for r in handler.get_rules()}[RuleID.GIT_PUSH_DELETE_REMOTE]
    assert "git push" in rule.blocked
    assert "human" in rule.fix.lower()
