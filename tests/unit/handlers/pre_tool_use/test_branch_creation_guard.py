"""Tests for the branch_creation_guard PreToolUse handler (Plan 00558 Task 4.2)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    BranchDuplicatesConfig,
    BranchesConfig,
    BranchParkedConfig,
    BranchWipConfig,
)
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.core.branch_creation import LABELS_RELATIVE_PATH, write_labels
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.branch_creation_guard import (
    BranchCreationGuardHandler,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _branch(repo: Path, name: str) -> None:
    tree = _git(repo, "rev-parse", "main^{tree}").strip()
    sha = _git(repo, "commit-tree", tree, "-p", "main", "-m", name).strip()
    _git(repo, "update-ref", f"refs/heads/{name}", sha)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _branch(root, "one")
    _branch(root, "two")
    return root


@pytest.fixture
def handler(repo: Path) -> BranchCreationGuardHandler:
    guard = BranchCreationGuardHandler()
    guard._branches = BranchesConfig(
        default="main",
        wip=BranchWipConfig(cap=2, mode="block"),
        duplicates=BranchDuplicatesConfig(mode="warn"),
    )
    guard._project_root_override = repo
    return guard


def _bash(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _agent(cwd: Path, **tool_input: Any) -> dict[str, Any]:
    return {"tool_name": "Agent", "tool_input": tool_input, "cwd": str(cwd)}


class TestMatches:
    def test_bash_creation_matches(self, handler: BranchCreationGuardHandler, repo: Path) -> None:
        assert handler.matches(_bash("git switch -c fresh", repo)) is True

    def test_bash_non_creation_does_not_match(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        assert handler.matches(_bash("git switch one", repo)) is False

    def test_isolated_agent_matches(self, handler: BranchCreationGuardHandler, repo: Path) -> None:
        assert handler.matches(_agent(repo, isolation="worktree", name="x")) is True
        task = {"tool_name": "Task", "tool_input": {"isolation": "worktree"}, "cwd": str(repo)}
        assert handler.matches(task) is True

    def test_plain_agent_does_not_match(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        assert handler.matches(_agent(repo, prompt="x")) is False

    def test_other_tool_does_not_match(self, handler: BranchCreationGuardHandler) -> None:
        assert handler.matches({"tool_name": "Read", "tool_input": {}}) is False


class TestHandle:
    def test_creation_at_cap_is_denied(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        result = handler.handle(_bash("git checkout -b fresh", repo))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith("BLOCKED [R-BRANCH-WIP-CAP]")
        assert "one" in result.reason and BRANCH_LIMIT_PRINCIPLE in result.reason

    def test_wip_cap_deny_demands_finishing_not_continuing(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        result = handler.handle(_bash("git checkout -b fresh", repo))
        assert result.reason is not None
        assert "continue in one" not in result.reason
        assert "Finish (merge)" in result.reason
        assert "park" in result.reason and "proves nothing is lost" in result.reason

    def test_a_full_parked_pool_is_denied_under_its_own_rule(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        tree = _git(repo, "rev-parse", "main^{tree}").strip()
        message = "park\n\nParked-Reason: waiting\nParked-By: t\n"
        sha = _git(repo, "commit-tree", tree, "-p", "main", "-m", message).strip()
        _git(repo, "update-ref", "refs/heads/held", sha)
        handler._branches = handler._branches.model_copy(
            update={
                "wip": BranchWipConfig(cap=9, mode="block"),
                "parked": BranchParkedConfig(cap=1),
            }
        )
        result = handler.handle(_bash("git checkout -b fresh", repo))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith("BLOCKED [R-BRANCH-PARKED-POOL]")
        assert "branch-park held --clear" in result.reason

    def test_dash_c_directory_is_judged(
        self, handler: BranchCreationGuardHandler, repo: Path, tmp_path: Path
    ) -> None:
        result = handler.handle(_bash(f"git -C {repo} switch -c fresh", tmp_path))
        assert result.decision == Decision.DENY

    def test_reset_of_existing_branch_is_allowed(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        result = handler.handle(_bash("git checkout -B one main", repo))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_under_cap_allows(self, handler: BranchCreationGuardHandler, repo: Path) -> None:
        handler._branches = handler._branches.model_copy(
            update={"wip": BranchWipConfig(cap=5, mode="block")}
        )
        result = handler.handle(_bash("git switch -c fresh", repo))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_warn_mode_allows_with_context(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        handler._branches = handler._branches.model_copy(
            update={"wip": BranchWipConfig(cap=2, mode="warn")}
        )
        result = handler.handle(_bash("git switch -c fresh", repo))
        assert result.decision == Decision.ALLOW
        assert any("Open work branches" in line for line in result.context)

    def test_git_failure_allows_with_advisory(
        self, handler: BranchCreationGuardHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_bash("git switch -c fresh", tmp_path / "gone"))
        assert result.decision == Decision.ALLOW
        assert any("could not judge" in line for line in result.context)

    def test_labels_snapshot_orders_the_list(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        write_labels(
            repo / LABELS_RELATIVE_PATH,
            [{"name": "two", "group": "contained-nowhere", "action": "git push -u origin two"}],
        )
        result = handler.handle(_bash("git switch -c fresh", repo))
        assert result.reason is not None
        assert "git push -u origin two" in result.reason

    @pytest.mark.parametrize(
        "command",
        [
            "git switch -c fresh",
            "git switch -C fresh",
            "git switch --create fresh",
            "git checkout -b fresh",
            "git checkout -B fresh",
            "git branch fresh",
            "git branch fresh main",
            "git worktree add -b fresh ../wt-fresh",
            "git worktree add -B fresh ../wt-fresh",
            "git worktree add ../wt-fresh",
        ],
    )
    def test_every_bash_creation_route_is_denied_listing_the_open_branches(
        self, handler: BranchCreationGuardHandler, repo: Path, command: str
    ) -> None:
        result = handler.handle(_bash(command, repo))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith("BLOCKED [R-BRANCH-WIP-CAP]")
        assert "one" in result.reason and "two" in result.reason
        assert BRANCH_LIMIT_PRINCIPLE in result.reason

    @pytest.mark.parametrize("tool_name", ["Agent", "Task"])
    def test_every_isolated_dispatch_route_is_denied_listing_the_open_branches(
        self, handler: BranchCreationGuardHandler, repo: Path, tool_name: str
    ) -> None:
        hook_input = {
            "tool_name": tool_name,
            "tool_input": {"isolation": "worktree", "name": "fresh"},
            "cwd": str(repo),
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "one" in result.reason and "two" in result.reason

    def test_isolated_agent_at_cap_is_denied(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        result = handler.handle(_agent(repo, isolation="worktree", name="one"))
        assert result.decision == Decision.DENY

    def test_isolated_agent_duplicate_warns(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        handler._branches = handler._branches.model_copy(
            update={"wip": BranchWipConfig(cap=5, mode="block")}
        )
        result = handler.handle(_agent(repo, isolation="worktree", name="one-2"))
        assert result.decision == Decision.ALLOW
        assert any("continue there" in line for line in result.context)


class TestBranchPracticeAdvisories:
    """Recovery-copy names and nested worktrees draw an advisory, never a deny."""

    @pytest.fixture
    def roomy(self, handler: BranchCreationGuardHandler) -> BranchCreationGuardHandler:
        handler._branches = handler._branches.model_copy(
            update={"wip": BranchWipConfig(cap=50, mode="block")}
        )
        return handler

    def test_recovery_shaped_branch_draws_the_archive_advice(
        self, roomy: BranchCreationGuardHandler, repo: Path
    ) -> None:
        result = roomy.handle(_bash("git switch -c rescue/plan-9", repo))
        assert result.decision == Decision.ALLOW
        assert any("refs/archive/rescue/plan-9" in line for line in result.context)

    def test_ordinary_branch_draws_no_archive_advice(
        self, roomy: BranchCreationGuardHandler, repo: Path
    ) -> None:
        result = roomy.handle(_bash("git switch -c fresh", repo))
        assert not any("refs/archive" in line for line in result.context)

    def test_recovery_advice_does_not_hide_the_cap_deny(
        self, handler: BranchCreationGuardHandler, repo: Path
    ) -> None:
        result = handler.handle(_bash("git switch -c backup/x", repo))
        assert result.decision == Decision.DENY

    def test_nested_worktree_names_the_main_checkout(
        self, roomy: BranchCreationGuardHandler, repo: Path, tmp_path: Path
    ) -> None:
        linked = tmp_path / "linked"
        _git(repo, "worktree", "add", "-q", "-b", "three", str(linked))
        result = roomy.handle(_bash("git worktree add -b four inner", linked))
        assert result.decision == Decision.ALLOW
        assert any(
            "never nested" in line and str(repo.resolve()) in line for line in result.context
        )

    def test_worktree_from_the_main_checkout_draws_no_nesting_advice(
        self, roomy: BranchCreationGuardHandler, repo: Path
    ) -> None:
        result = roomy.handle(_bash("git worktree add -b four .claude/worktrees/four", repo))
        assert not any("never nested" in line for line in result.context)

    def test_guidance_states_the_practice(self, handler: BranchCreationGuardHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "refs/archive" in guidance and "never nested" in guidance


def test_rules_guidance_and_acceptance_tests(handler: BranchCreationGuardHandler) -> None:
    assert [rule.rule_id for rule in handler.get_rules()] == [
        "R-BRANCH-WIP-CAP",
        "R-BRANCH-DORMANT",
        "R-BRANCH-PARKED-POOL",
        "R-BRANCH-MERGED-POOL",
    ]
    guidance = handler.get_claude_md()
    assert guidance is not None and "wip.cap" in guidance
    assert handler.get_acceptance_tests()
