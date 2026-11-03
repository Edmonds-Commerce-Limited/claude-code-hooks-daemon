"""Tests for the Stop-event branch guard handler (Plan 00558 Task 4.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_records import TOUCHED_KEY
from claude_code_hooks_daemon.handlers.stop import branch_stop_guard
from claude_code_hooks_daemon.handlers.stop.branch_stop_guard import BranchStopGuardHandler

SESSION = "sess-1"


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
def handler(repo: Path, tmp_path: Path) -> BranchStopGuardHandler:
    instance = BranchStopGuardHandler()
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
    _git(repo, "config", "--add", f"branch.{name}.{TOUCHED_KEY}", f"{SESSION}:")


def _payload() -> dict[str, Any]:
    return {"hook_event_name": "Stop", "session_id": SESSION}


class TestStopHandler:
    def test_registration(self, handler: BranchStopGuardHandler) -> None:
        assert handler.handler_id == HandlerID.BRANCH_STOP_GUARD
        assert handler.priority == Priority.BRANCH_STOP_GUARD == 9
        assert handler.terminal is False

    def test_matches_a_real_stop(self, handler: BranchStopGuardHandler) -> None:
        assert handler.matches(_payload()) is True

    def test_does_not_match_without_session(self, handler: BranchStopGuardHandler) -> None:
        assert handler.matches({"hook_event_name": "Stop"}) is False

    def test_clean_repo_allows(self, handler: BranchStopGuardHandler) -> None:
        assert handler.handle(_payload()).decision == Decision.ALLOW

    def test_unpushed_branch_denies_under_rule(
        self, handler: BranchStopGuardHandler, repo: Path
    ) -> None:
        _leave_unpushed(repo)
        result = handler.handle(_payload())
        assert result.decision == Decision.DENY
        assert "R-BRANCH-STOP-GUARD" in (result.reason or "")
        assert "feat-a" in (result.reason or "")

    def test_usage_pause_allows(
        self,
        handler: BranchStopGuardHandler,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _leave_unpushed(repo)
        monkeypatch.setattr(branch_stop_guard, "hook_is_usage_paused", lambda _payload: True)
        assert handler.handle(_payload()).decision == Decision.ALLOW

    def test_allow_carries_context(
        self, handler: BranchStopGuardHandler, repo: Path
    ) -> None:
        _leave_unpushed(repo)
        handler._branches = handler._branches.model_validate({"stop_guard": {"mode": "warn"}})
        result = handler.handle(_payload())
        assert result.decision == Decision.ALLOW
        assert any("feat-a" in line for line in result.context)

    def test_unexpected_failure_allows(
        self, handler: BranchStopGuardHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(branch_stop_guard, "decide_stop", boom)
        assert handler.handle(_payload()).decision == Decision.ALLOW

    def test_acceptance_tests_declared(self, handler: BranchStopGuardHandler) -> None:
        assert handler.get_acceptance_tests()
