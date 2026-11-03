"""Evacuate then destroy, the same-turn half (Plan 00558 DESIGN section 13, Task 4.5).

The recorder notes each evacuation under the current turn; a destruction in a
later command of the same turn is denied. The main thread's turn advances at
UserPromptSubmit; a sub-agent's turn is its lifetime. Real throwaway repositories.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.evacuation import (
    destroys_recorded,
    evacuations,
)
from claude_code_hooks_daemon.core.evacuation_turns import (
    advance_turn,
    record_evacuations,
    recorded_evacuations,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler

_GIT_IDENTITY = (
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.invalid",
    "-c",
    "commit.gpgsign=false",
)
_SESSION = "s1"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`repo` on `main`, ignoring `untracked/`; linked worktree `wt` on `lane`."""
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


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    return tmp_path / "daemon-untracked"


def _evacuate(repo: Path, wt: Path) -> str:
    return f"git -C {wt} diff main > {repo}/untracked/lane.patch"


class TestEvacuations:
    """The public reading of the evacuation half alone."""

    def test_returns_toplevel_and_branches(self, repo: Path, wt: Path) -> None:
        found = evacuations(_evacuate(repo, wt), repo)
        assert len(found) == 1
        assert found[0].toplevel == wt.resolve()
        assert "lane" in found[0].branches

    def test_no_evacuation_is_empty(self, repo: Path, wt: Path) -> None:
        assert evacuations(f"git worktree remove {wt}", repo) == []

    def test_tracked_landing_is_empty(self, repo: Path, wt: Path) -> None:
        assert evacuations(f"git -C {wt} diff main > {repo}/.gitignore", repo) == []


class TestTurnRecords:
    """Records live per identity and expire with their turn."""

    def test_main_thread_record_survives_within_the_turn(
        self, repo: Path, wt: Path, untracked: Path
    ) -> None:
        advance_turn(untracked, _SESSION)
        works = evacuations(_evacuate(repo, wt), repo)
        record_evacuations(untracked, _SESSION, None, works)
        assert recorded_evacuations(untracked, _SESSION, None) == works

    def test_main_thread_record_expires_at_the_next_prompt(
        self, repo: Path, wt: Path, untracked: Path
    ) -> None:
        advance_turn(untracked, _SESSION)
        record_evacuations(untracked, _SESSION, None, evacuations(_evacuate(repo, wt), repo))
        advance_turn(untracked, _SESSION)
        assert recorded_evacuations(untracked, _SESSION, None) == []

    def test_agent_record_is_its_own_and_ignores_prompts(
        self, repo: Path, wt: Path, untracked: Path
    ) -> None:
        works = evacuations(_evacuate(repo, wt), repo)
        record_evacuations(untracked, _SESSION, "a1", works)
        advance_turn(untracked, _SESSION)
        assert recorded_evacuations(untracked, _SESSION, "a1") == works
        assert recorded_evacuations(untracked, _SESSION, "a2") == []
        assert recorded_evacuations(untracked, _SESSION, None) == []

    def test_new_record_in_the_same_turn_accumulates_bounded(
        self, repo: Path, wt: Path, untracked: Path
    ) -> None:
        works = evacuations(_evacuate(repo, wt), repo)
        for _ in range(80):
            record_evacuations(untracked, _SESSION, "a1", works)
        assert 0 < len(recorded_evacuations(untracked, _SESSION, "a1")) <= 50

    def test_unplaceable_evacuation_is_not_recorded(self, repo: Path, untracked: Path) -> None:
        works = evacuations(f"cd $X && git diff > {repo}/untracked/p.patch", repo)
        record_evacuations(untracked, _SESSION, "a1", works)
        assert recorded_evacuations(untracked, _SESSION, "a1") == []

    def test_corrupt_state_reads_as_empty(self, untracked: Path) -> None:
        record_evacuations(untracked, _SESSION, "a1", [])
        assert recorded_evacuations(untracked, _SESSION, "a1") == []


class TestDestroysRecorded:
    """A later command destroying recorded work."""

    def test_worktree_remove_matches_recorded_toplevel(self, repo: Path, wt: Path) -> None:
        works = evacuations(_evacuate(repo, wt), repo)
        found = destroys_recorded(f"git worktree remove {wt}", repo, works)
        assert found is not None
        assert str(wt) in found.destruction
        assert found.landing == str(repo / "untracked" / "lane.patch")

    def test_branch_delete_matches_recorded_branch(self, repo: Path, wt: Path) -> None:
        works = evacuations(_evacuate(repo, wt), repo)
        assert destroys_recorded("git branch -D lane", repo, works) is not None

    def test_other_worktree_does_not_match(self, repo: Path, wt: Path, tmp_path: Path) -> None:
        other = tmp_path / "other"
        _git(repo, "worktree", "add", "-b", "other", str(other))
        works = evacuations(_evacuate(repo, wt), repo)
        assert destroys_recorded(f"git worktree remove {other}", repo, works) is None

    def test_no_records_never_matches(self, repo: Path, wt: Path) -> None:
        assert destroys_recorded(f"git worktree remove {wt}", repo, []) is None


def _input(command: str, cwd: Path, **extra: Any) -> dict[str, Any]:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
        "session_id": _SESSION,
        **extra,
    }


class TestHandlerSameTurn:
    """destructive_git denies a destruction of work evacuated earlier this turn."""

    @pytest.fixture
    def handler(self, untracked: Path) -> DestructiveGitHandler:
        instance = DestructiveGitHandler()
        instance._untracked_override = untracked
        return instance

    def test_denies_remove_after_recorded_evacuation(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path, untracked: Path
    ) -> None:
        advance_turn(untracked, _SESSION)
        record_evacuations(untracked, _SESSION, None, evacuations(_evacuate(repo, wt), repo))
        hook_input = _input(f"git worktree remove {wt}", repo)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.rule == RuleID.GIT_EVACUATE_THEN_DESTROY
        assert result.reason is not None
        assert "commit" in result.reason
        assert BRANCH_LIMIT_PRINCIPLE in result.reason

    def test_agent_record_is_read_by_agent_id(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path, untracked: Path
    ) -> None:
        record_evacuations(untracked, _SESSION, "a1", evacuations(_evacuate(repo, wt), repo))
        denied = handler.handle(_input("git branch -D lane", repo, agent_id="a1"))
        assert denied.rule == RuleID.GIT_EVACUATE_THEN_DESTROY
        other = handler.handle(_input(f"git worktree remove {wt}", repo, agent_id="a2"))
        assert other.decision == Decision.ALLOW

    def test_next_turn_allows_cleanup(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path, untracked: Path
    ) -> None:
        advance_turn(untracked, _SESSION)
        record_evacuations(untracked, _SESSION, None, evacuations(_evacuate(repo, wt), repo))
        advance_turn(untracked, _SESSION)
        assert handler.handle(_input(f"git worktree remove {wt}", repo)).decision == Decision.ALLOW

    def test_warn_mode_adds_context_only(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path, untracked: Path
    ) -> None:
        handler._branches = BranchesConfig.model_validate({"evacuation": {"mode": "warn"}})
        advance_turn(untracked, _SESSION)
        record_evacuations(untracked, _SESSION, None, evacuations(_evacuate(repo, wt), repo))
        result = handler.handle(_input(f"git worktree remove {wt}", repo))
        assert result.decision == Decision.ALLOW
        assert any(BRANCH_LIMIT_PRINCIPLE in line for line in result.context)

    def test_off_mode_ignores_records(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path, untracked: Path
    ) -> None:
        handler._branches = BranchesConfig.model_validate({"evacuation": {"mode": "off"}})
        advance_turn(untracked, _SESSION)
        record_evacuations(untracked, _SESSION, None, evacuations(_evacuate(repo, wt), repo))
        assert handler.handle(_input(f"git worktree remove {wt}", repo)).decision == Decision.ALLOW

    def test_no_session_id_skips_the_record_lookup(
        self, handler: DestructiveGitHandler, repo: Path, wt: Path
    ) -> None:
        hook_input = _input(f"git worktree remove {wt}", repo)
        del hook_input["session_id"]
        assert handler.handle(hook_input).decision == Decision.ALLOW
