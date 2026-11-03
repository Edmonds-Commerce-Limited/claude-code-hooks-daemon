"""Evacuate then destroy, the same-command half (Plan 00558 DESIGN section 13, Task 4.5).

A Bash command that copies a worktree's or branch's work out (git diff,
format-patch, stash show -p, show) to a landing that is not a tracked file,
and then destroys that same worktree or branch, is denied: the evacuated
copy is an untracked file nothing reviews, and the right move is to commit or
push on the lane's branch. Real throwaway repositories throughout.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.evacuation import evacuate_then_destroy
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler

_GIT_IDENTITY = (
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.invalid",
    "-c",
    "commit.gpgsign=false",
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`repo` on `main`, ignoring `untracked/`; linked worktree `wt` on `lane`, one commit."""
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(repo))
    (repo / ".gitignore").write_text("untracked/\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "base")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-b", "lane", str(wt))
    (wt / "lane.txt").write_text("lane")
    _git(wt, "add", "lane.txt")
    _git(wt, "commit", "-m", "lane")
    return repo


@pytest.fixture
def wt(repo: Path) -> Path:
    return repo.parent / "wt"


class TestEvacuateThenDestroy:
    """The core reading: which commands evacuate and then destroy the same work."""

    def test_diff_to_ignored_path_then_worktree_remove(self, repo: Path, wt: Path) -> None:
        command = f"git -C {wt} diff main > {repo}/untracked/lane.patch && git worktree remove {wt}"
        found = evacuate_then_destroy(command, repo)
        assert found is not None
        assert str(wt) in found.destruction
        assert found.landing == str(repo / "untracked" / "lane.patch")

    def test_cd_chain_places_the_evacuation(self, repo: Path, wt: Path) -> None:
        command = f"cd {wt} && git diff main > ../out.patch && cd {repo} && git worktree remove {wt}"
        assert evacuate_then_destroy(command, repo) is not None

    def test_format_patch_output_directory_then_rm(self, repo: Path, wt: Path) -> None:
        command = f"git -C {wt} format-patch -o {repo.parent}/patches main && rm -rf {wt}"
        found = evacuate_then_destroy(command, repo)
        assert found is not None
        assert found.landing == str(repo.parent / "patches")

    def test_tee_landing_then_branch_delete(self, repo: Path, wt: Path) -> None:
        command = f"git -C {wt} show HEAD | tee {repo.parent}/x.patch; git branch -D lane"
        assert evacuate_then_destroy(command, repo) is not None

    def test_named_branch_matches_the_deleted_branch(self, repo: Path) -> None:
        command = f"git diff main...lane > {repo.parent}/x.patch && git branch -d lane"
        assert evacuate_then_destroy(command, repo) is not None

    def test_stash_show_p_counts(self, repo: Path, wt: Path) -> None:
        command = f"git -C {wt} stash show -p > {repo.parent}/s.patch && git worktree remove {wt}"
        assert evacuate_then_destroy(command, repo) is not None

    def test_stash_show_without_patch_is_no_evacuation(self, repo: Path, wt: Path) -> None:
        command = f"git -C {wt} stash show > {repo.parent}/s.txt && git worktree remove {wt}"
        assert evacuate_then_destroy(command, repo) is None

    def test_tracked_landing_is_no_evacuation(self, repo: Path, wt: Path) -> None:
        command = f"git -C {wt} diff main > {repo}/.gitignore && git worktree remove {wt}"
        assert evacuate_then_destroy(command, repo) is None

    def test_other_worktree_evacuation_does_not_match(self, repo: Path, wt: Path) -> None:
        command = f"git -C {repo} diff > {repo.parent}/x.patch && git worktree remove {wt}"
        assert evacuate_then_destroy(command, repo) is None

    def test_evacuation_alone_is_none(self, repo: Path, wt: Path) -> None:
        assert evacuate_then_destroy(f"git -C {wt} diff > {repo.parent}/x.patch", repo) is None

    def test_destruction_alone_is_none(self, repo: Path, wt: Path) -> None:
        assert evacuate_then_destroy(f"git worktree remove {wt}", repo) is None

    def test_diff_stat_is_no_evacuation(self, repo: Path, wt: Path) -> None:
        command = f"git -C {wt} diff --stat > {repo.parent}/x.txt && git worktree remove {wt}"
        assert evacuate_then_destroy(command, repo) is None

    def test_unplaceable_evacuation_fails_closed(self, repo: Path, wt: Path) -> None:
        command = f"cd - && git diff > {repo.parent}/x.patch && git worktree remove {wt}"
        assert evacuate_then_destroy(command, repo) is not None


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


class TestHandler:
    """destructive_git denies the shape, before any lossless allowance."""

    def test_denies_with_rule_right_move_and_principle(self, repo: Path, wt: Path) -> None:
        handler = DestructiveGitHandler()
        hook_input = _input(
            f"git -C {wt} diff main > {repo}/untracked/l.patch && git worktree remove {wt}", repo
        )
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.rule == RuleID.GIT_EVACUATE_THEN_DESTROY
        assert "commit" in result.reason
        assert BRANCH_LIMIT_PRINCIPLE in result.reason

    def test_rm_destruction_alone_still_matched_through_evacuation(
        self, repo: Path, wt: Path
    ) -> None:
        handler = DestructiveGitHandler()
        hook_input = _input(f"git -C {wt} diff main > {repo.parent}/p && rm -r {wt}", repo)
        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).rule == RuleID.GIT_EVACUATE_THEN_DESTROY

    def test_plain_remove_still_allowed(self, repo: Path, wt: Path) -> None:
        handler = DestructiveGitHandler()
        hook_input = _input(f"git worktree remove {wt}", repo)
        assert handler.handle(hook_input).decision == Decision.ALLOW

    def test_warn_mode_allows_with_context(self, repo: Path, wt: Path) -> None:
        handler = DestructiveGitHandler()
        handler._branches = BranchesConfig.model_validate({"evacuation": {"mode": "warn"}})
        hook_input = _input(
            f"git -C {wt} diff main > {repo}/untracked/l.patch && git worktree remove {wt}", repo
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert any(BRANCH_LIMIT_PRINCIPLE in line for line in result.context)

    def test_off_mode_ignores_the_shape(self, repo: Path, wt: Path) -> None:
        handler = DestructiveGitHandler()
        handler._branches = BranchesConfig.model_validate({"evacuation": {"mode": "off"}})
        hook_input = _input(
            f"git -C {wt} diff main > {repo}/untracked/l.patch && git worktree remove {wt}", repo
        )
        assert handler.handle(hook_input).decision == Decision.ALLOW
        rm_input = _input(f"git -C {wt} diff main > {repo.parent}/p && rm -r {wt}", repo)
        assert handler.matches(rm_input) is False
