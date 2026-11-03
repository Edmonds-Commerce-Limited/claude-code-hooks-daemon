"""Tests for the SubagentStop-event branch guard handler (Plan 00558 Task 4.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.handlers.pre_tool_use.subagent_context_budget import (
    STATE_HARD_ENGAGED,
    STATE_KIND as BUDGET_STATE_KIND,
)
from claude_code_hooks_daemon.handlers.subagent_stop.branch_subagent_stop_guard import (
    BranchSubagentStopGuardHandler,
)
from claude_code_hooks_daemon.utils.spend_ledger import state_path, write_state

SESSION = "sess-1"
AGENT = "agent-1"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / ".git" / "info" / "exclude").write_text("untracked/\n")
    _git(root, "checkout", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    return root


@pytest.fixture
def handler(repo: Path, tmp_path: Path) -> BranchSubagentStopGuardHandler:
    instance = BranchSubagentStopGuardHandler()
    instance._project_root_override = repo
    instance._untracked_override = tmp_path / "untracked"
    instance._untracked_override.mkdir()
    return instance


def _leave_unpushed(repo: Path, name: str = "feat-a") -> None:
    _git(repo, "branch", name, "main")
    tree = _git(repo, "rev-parse", f"{name}^{{tree}}").strip()
    parent = _git(repo, "rev-parse", name).strip()
    tip = _git(repo, "commit-tree", tree, "-p", parent, "-m", "work").strip()
    _git(repo, "update-ref", f"refs/heads/{name}", tip)
    _git(repo, "config", "--add", f"branch.{name}.{TOUCHED_KEY}", f"{SESSION}:{AGENT}")


def _payload(agent: str | None = AGENT) -> dict[str, Any]:
    payload: dict[str, Any] = {"hook_event_name": "SubagentStop", "session_id": SESSION}
    if agent:
        payload["agent_id"] = agent
    return payload


class TestSubagentStopHandler:
    def test_registration(self, handler: BranchSubagentStopGuardHandler) -> None:
        assert handler.handler_id == HandlerID.BRANCH_SUBAGENT_STOP_GUARD
        assert handler.priority == Priority.BRANCH_SUBAGENT_STOP_GUARD == 12
        assert handler.terminal is False

    def test_needs_an_agent_id(self, handler: BranchSubagentStopGuardHandler) -> None:
        assert handler.matches(_payload(None)) is False
        assert handler.matches(_payload()) is True

    def test_unpushed_branch_denies(
        self, handler: BranchSubagentStopGuardHandler, repo: Path
    ) -> None:
        _leave_unpushed(repo)
        result = handler.handle(_payload())
        assert result.decision == Decision.DENY
        assert "feat-a" in (result.reason or "")

    def test_advise_mode_allows_this_repos_unpushed_commits(
        self, handler: BranchSubagentStopGuardHandler, repo: Path
    ) -> None:
        _leave_unpushed(repo)
        handler._branches = handler._branches.model_validate(
            {"stop_guard": {"unpushed_subagent": "advise"}}
        )
        assert handler.handle(_payload()).decision == Decision.ALLOW

    def test_hard_band_appends_tip(
        self,
        handler: BranchSubagentStopGuardHandler,
        repo: Path,
        tmp_path: Path,
    ) -> None:
        _leave_unpushed(repo)
        tip = _git(repo, "rev-parse", "feat-a").strip()
        write_state(
            state_path(tmp_path / "untracked", SESSION, BUDGET_STATE_KIND, AGENT),
            {STATE_HARD_ENGAGED: True},
        )
        result = handler.handle(_payload())
        assert result.decision == Decision.DENY
        assert tip in (result.reason or "")

    def test_acceptance_tests_declared(self, handler: BranchSubagentStopGuardHandler) -> None:
        assert handler.get_acceptance_tests()
