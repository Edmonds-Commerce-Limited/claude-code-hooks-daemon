"""Lossless force removal (Plan 00558 DESIGN section 11, Task 4.1).

`git branch -D` is allowed when ANY surviving ref (branch, tag or
remote-tracking ref) contains the tip, and `git worktree remove` is judged on
what the removal would lose: dirty files, ignored content outside the
regenerable globs and, when forced, a HEAD no surviving ref holds. Real
throwaway repositories throughout.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, force_removal
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


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`inner` is held by `outer`; `solo` by nothing else; `tagged` by tag `v1`.

    Linked worktree `wt` is on branch `lane` (one unique commit), and
    `.gitignore` ignores `untracked/`.
    """
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(repo))
    (repo / ".gitignore").write_text("untracked/\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "solo")
    _commit(repo, "solo")
    _git(repo, "checkout", "-b", "inner", "main")
    _commit(repo, "inner")
    _git(repo, "checkout", "-b", "outer")
    _commit(repo, "outer")
    _git(repo, "checkout", "-b", "tagged", "main")
    _commit(repo, "tagged")
    _git(repo, "tag", "v1")
    _git(repo, "checkout", "main")
    _git(repo, "worktree", "add", "-b", "lane", str(tmp_path / "wt"))
    _commit(tmp_path / "wt", "lane")
    return repo


@pytest.fixture
def wt(repo: Path) -> Path:
    return repo.parent / "wt"


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _allowed(handler: DestructiveGitHandler, command: str, cwd: Path) -> bool:
    hook_input = _input(command, cwd)
    assert handler.matches(hook_input) is True
    return handler.handle(hook_input).decision == Decision.ALLOW


def _deny(handler: DestructiveGitHandler, command: str, cwd: Path) -> tuple[str, str]:
    hook_input = _input(command, cwd)
    assert handler.matches(hook_input) is True
    result = handler.handle(hook_input)
    assert result.decision == Decision.DENY
    return result.rule or "", result.reason or ""


class TestBranchDeleteHeldElsewhere:
    @pytest.mark.parametrize(
        "command",
        [
            "git branch -D inner",
            "git branch -d --force inner",
            "git update-ref -d refs/heads/inner",
            "git branch -D tagged",
        ],
    )
    def test_a_tip_another_local_ref_holds_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        assert _allowed(handler, command, repo)

    def test_deleting_the_holder_in_the_same_command_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        rule, reason = _deny(handler, "git branch -D inner outer", repo)
        assert rule == RuleID.GIT_BRANCH_FORCE_DELETE
        assert "`inner`" in reason and "`outer`" in reason
        assert BRANCH_LIMIT_PRINCIPLE in reason

    def test_split_across_invocations_is_judged_as_a_whole(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _rule, reason = _deny(handler, "git branch -D inner && git branch -D outer", repo)
        assert "`inner`" in reason

    def test_the_deny_states_the_commit_count(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _rule, reason = _deny(handler, "git branch -D solo", repo)
        assert "1 commit" in reason
        assert BRANCH_LIMIT_PRINCIPLE in reason

    def test_containment_failure_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 128, "", "boom")

        monkeypatch.setattr(force_removal, "run_git", broken)
        _rule, reason = _deny(handler, "git branch -D inner", repo)
        assert "boom" in reason

    def test_mode_off_trusts_only_remote_tracking_refs(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        handler._branches = BranchesConfig.model_validate({"force_removal": {"mode": "off"}})
        _rule, reason = _deny(handler, "git branch -D inner", repo)
        assert "inner" in reason


class TestWorktreeRemoveForce:
    @pytest.mark.parametrize("flags", ["--force", "-f", "-f -f", "--force --force"])
    def test_clean_worktree_on_a_branch_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path, flags: str
    ) -> None:
        assert _allowed(handler, f"git worktree remove {flags} {wt}", repo)

    def test_relative_path_from_dash_c(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        assert _allowed(handler, f"git -C {repo} worktree remove -f ../wt", wt.parent)

    def test_dirty_worktree_is_denied_listing_paths(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        (wt / "notes.txt").write_text("work")
        rule, reason = _deny(handler, f"git worktree remove --force {wt}", repo)
        assert rule == RuleID.GIT_WORKTREE_REMOVE_FORCE
        assert "notes.txt" in reason
        assert BRANCH_LIMIT_PRINCIPLE in reason

    def test_detached_head_with_unique_commits_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        _git(wt, "checkout", "--detach")
        _commit(wt, "orphan")
        rule, reason = _deny(handler, f"git worktree remove -f {wt}", repo)
        assert rule == RuleID.GIT_WORKTREE_REMOVE_FORCE
        assert "1 commit" in reason

    def test_unforced_removal_of_detached_head_with_unique_commits_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        _git(wt, "checkout", "--detach")
        _commit(wt, "orphan")
        rule, reason = _deny(handler, f"git worktree remove {wt}", repo)
        assert rule == RuleID.GIT_WORKTREE_REMOVE_FORCE
        assert "1 commit" in reason

    def test_unforced_removal_of_detached_head_a_branch_holds_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        _git(wt, "checkout", "--detach")
        assert _allowed(handler, f"git worktree remove {wt}", repo)

    def test_unforced_removal_on_a_branch_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        assert _allowed(handler, f"git worktree remove {wt}", repo)

    def test_detached_head_a_branch_holds_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        _git(wt, "checkout", "--detach")
        assert _allowed(handler, f"git worktree remove -f {wt}", repo)

    def test_removing_and_deleting_its_branch_together_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        rule, reason = _deny(
            handler, f"git worktree remove --force {wt} && git branch -D lane", repo
        )
        assert rule == RuleID.GIT_WORKTREE_REMOVE_FORCE
        assert "lane" in reason

    def test_unknown_flag_is_unverifiable(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        rule, _reason = _deny(handler, f"git worktree remove --force --bogus {wt}", repo)
        assert rule == RuleID.GIT_WORKTREE_REMOVE_FORCE

    def test_a_missing_worktree_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        _deny(handler, f"git worktree remove -f {tmp_path / 'nope'}", repo)

    def test_mode_off_does_not_judge_worktree_removal(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        handler._branches = BranchesConfig.model_validate({"force_removal": {"mode": "off"}})
        (wt / "notes.txt").write_text("work")
        assert handler.matches(_input(f"git worktree remove -f {wt}", repo)) is True
        assert handler.handle(_input(f"git worktree remove -f {wt}", repo)).decision == (
            Decision.ALLOW
        )


class TestWorktreeRemoveIgnoredContent:
    def test_unforced_removal_with_scratch_notes_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        (wt / "untracked" / "scratch").mkdir(parents=True)
        (wt / "untracked" / "scratch" / "plan.md").write_text("notes")
        rule, reason = _deny(handler, f"git worktree remove {wt}", repo)
        assert rule == RuleID.GIT_WORKTREE_REMOVE_FORCE
        assert "untracked/scratch/" in reason
        assert BRANCH_LIMIT_PRINCIPLE in reason

    def test_regenerable_ignored_content_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        (wt / "untracked" / "qa").mkdir(parents=True)
        (wt / "untracked" / "qa" / "report.json").write_text("{}")
        assert _allowed(handler, f"git worktree remove {wt}", repo)
        assert _allowed(handler, f"git worktree remove --force {wt}", repo)

    def test_more_than_ten_blockers_are_previewed_with_a_count(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        for index in range(13):
            (wt / f"stray{index:02d}.txt").write_text("x")
        _rule, reason = _deny(handler, f"git worktree remove {wt}", repo)
        assert "and 3 more" in reason
        assert "13 path" in reason


class TestRuleRegistration:
    def test_rule_is_listed_with_guidance(self, handler: DestructiveGitHandler) -> None:
        rule = next(r for r in handler.get_rules() if r.rule_id == RuleID.GIT_WORKTREE_REMOVE_FORCE)
        assert "worktree remove" in rule.blocked
        assert "regenerable" in rule.verbose

    def test_acceptance_test_covers_the_rule(self, handler: DestructiveGitHandler) -> None:
        titles = [t.title.lower() for t in handler.get_acceptance_tests()]
        assert any("worktree remove" in title for title in titles)
