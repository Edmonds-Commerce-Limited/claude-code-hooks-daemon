"""Tests for the branch creator/touch recorder (Plan 00558 Task 4.2 part B)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_records import touched_branches
from claude_code_hooks_daemon.handlers.post_tool_use.branch_touch_recorder import (
    BranchTouchRecorderHandler,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _config(repo: Path, key: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "config", "--get-all", key],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.split()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    return root


@pytest.fixture
def handler(tmp_path: Path) -> BranchTouchRecorderHandler:
    instance = BranchTouchRecorderHandler()
    instance._untracked_override = tmp_path / "untracked"
    return instance


def _bash(repo: Path, command: str, agent: str | None = "a1") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(repo),
        "session_id": "s1",
    }
    if agent:
        payload["agent_id"] = agent
    return payload


class TestRegistration:
    def test_identity(self, handler: BranchTouchRecorderHandler) -> None:
        assert handler.handler_id == HandlerID.BRANCH_TOUCH_RECORDER
        assert handler.priority == Priority.BRANCH_TOUCH_RECORDER
        assert handler.terminal is False


class TestMatches:
    def test_creation_and_touch_commands_match(
        self, handler: BranchTouchRecorderHandler, repo: Path
    ) -> None:
        assert handler.matches(_bash(repo, "git switch -c feat"))
        assert handler.matches(_bash(repo, "git commit -m x"))

    def test_read_only_git_does_not_match(
        self, handler: BranchTouchRecorderHandler, repo: Path
    ) -> None:
        assert not handler.matches(_bash(repo, "git status"))
        assert not handler.matches(_bash(repo, "ls"))

    def test_file_writes_match_and_reads_do_not(
        self, handler: BranchTouchRecorderHandler, repo: Path
    ) -> None:
        for tool in ("Write", "Edit"):
            assert handler.matches({"tool_name": tool, "tool_input": {"file_path": "/x/y"}})
        assert handler.matches({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/n"}})
        assert not handler.matches({"tool_name": "Read", "tool_input": {"file_path": "/x"}})


class TestRecords:
    def test_bash_creation_records_creator_and_route(
        self, handler: BranchTouchRecorderHandler, repo: Path
    ) -> None:
        _git(repo, "switch", "-q", "-c", "feat")
        result = handler.handle(_bash(repo, "git switch -c feat"))
        assert result.decision == Decision.ALLOW
        assert _config(repo, "branch.feat.hooksDaemonCreator") == ["s1:a1"]
        assert _config(repo, "branch.feat.hooksDaemonRoute") == ["switch"]
        assert touched_branches(repo, "s1", "a1") == ["feat"]

    def test_failed_creation_records_nothing(
        self, handler: BranchTouchRecorderHandler, repo: Path
    ) -> None:
        handler.handle(_bash(repo, "git switch -c never-made"))
        assert _config(repo, "branch.never-made.hooksDaemonCreator") == []

    def test_commit_touches_the_checked_out_branch(
        self, handler: BranchTouchRecorderHandler, repo: Path
    ) -> None:
        handler.handle(_bash(repo, "git commit --allow-empty -m x", agent=None))
        assert touched_branches(repo, "s1", None) == ["main"]

    def test_git_dash_c_names_the_directory(
        self, handler: BranchTouchRecorderHandler, repo: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        handler.handle(_bash(elsewhere, f"git -C {repo} commit --allow-empty -m x"))
        assert touched_branches(repo, "s1", "a1") == ["main"]

    def test_edit_touches_the_files_branch(
        self, handler: BranchTouchRecorderHandler, repo: Path
    ) -> None:
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(repo / "pkg" / "new.py")},
            "session_id": "s1",
            "agent_id": "a2",
        }
        assert handler.handle(hook_input).decision == Decision.ALLOW
        assert touched_branches(repo, "s1", "a2") == ["main"]

    def test_detached_head_and_no_repo_record_nothing(
        self, handler: BranchTouchRecorderHandler, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "switch", "-q", "--detach")
        handler.handle(_bash(repo, "git commit --allow-empty -m x"))
        assert touched_branches(repo, "s1", "a1") == []
        outside = {"tool_name": "Write", "tool_input": {"file_path": "/"}, "session_id": "s1"}
        assert handler.handle(outside).decision == Decision.ALLOW

    def test_no_session_records_nothing(
        self, handler: BranchTouchRecorderHandler, repo: Path
    ) -> None:
        payload = _bash(repo, "git commit --allow-empty -m x")
        del payload["session_id"]
        assert handler.handle(payload).decision == Decision.ALLOW
        assert _config(repo, "branch.main.hooksDaemonTouchedBy") == []


class TestDocs:
    def test_guidance_and_acceptance(self, handler: BranchTouchRecorderHandler) -> None:
        assert "hooksDaemonTouchedBy" in (handler.get_claude_md() or "")
        assert handler.get_acceptance_tests()
