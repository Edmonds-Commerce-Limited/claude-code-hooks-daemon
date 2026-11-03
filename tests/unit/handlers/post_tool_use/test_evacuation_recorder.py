"""Tests for the evacuation recorder (Plan 00558 Task 4.5)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.evacuation_turns import recorded_evacuations
from claude_code_hooks_daemon.handlers.post_tool_use.evacuation_recorder import (
    EvacuationRecorderHandler,
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-b", "main", str(repo))
    (repo / ".gitignore").write_text("untracked/\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "base")
    _git(repo, "worktree", "add", "-b", "lane", str(tmp_path / "wt"))
    return repo


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    return tmp_path / "daemon-untracked"


@pytest.fixture
def recorder(untracked: Path) -> EvacuationRecorderHandler:
    instance = EvacuationRecorderHandler()
    instance._untracked_override = untracked
    return instance


def _bash(repo: Path, command: str, **extra: Any) -> dict[str, Any]:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(repo),
        "session_id": "s1",
        **extra,
    }


class TestRecorder:
    def test_identity(self, recorder: EvacuationRecorderHandler) -> None:
        assert recorder.handler_id == HandlerID.EVACUATION_RECORDER
        assert recorder.priority == Priority.EVACUATION_RECORDER
        assert recorder.terminal is False

    def test_matches_only_an_evacuating_bash_command(
        self, recorder: EvacuationRecorderHandler, repo: Path
    ) -> None:
        wt = repo.parent / "wt"
        assert recorder.matches(_bash(repo, f"git -C {wt} diff main > {repo}/untracked/p")) is True
        assert recorder.matches(_bash(repo, "git status")) is False
        assert recorder.matches({"tool_name": "Read", "tool_input": {}}) is False

    def test_records_under_the_main_thread(
        self, recorder: EvacuationRecorderHandler, repo: Path, untracked: Path
    ) -> None:
        wt = repo.parent / "wt"
        result = recorder.handle(_bash(repo, f"git -C {wt} diff main > {repo}/untracked/p"))
        assert result.decision == Decision.ALLOW
        kept = recorded_evacuations(untracked, "s1", None)
        assert [work.toplevel for work in kept] == [wt.resolve()]

    def test_records_under_an_agent(
        self, recorder: EvacuationRecorderHandler, repo: Path, untracked: Path
    ) -> None:
        wt = repo.parent / "wt"
        recorder.handle(_bash(repo, f"git -C {wt} diff main > {repo}/untracked/p", agent_id="a1"))
        assert recorded_evacuations(untracked, "s1", "a1") != []
        assert recorded_evacuations(untracked, "s1", None) == []

    def test_no_session_records_nothing(
        self, recorder: EvacuationRecorderHandler, repo: Path, untracked: Path
    ) -> None:
        wt = repo.parent / "wt"
        hook_input = _bash(repo, f"git -C {wt} diff main > {repo}/untracked/p")
        del hook_input["session_id"]
        assert recorder.handle(hook_input).decision == Decision.ALLOW
        assert not untracked.exists()
