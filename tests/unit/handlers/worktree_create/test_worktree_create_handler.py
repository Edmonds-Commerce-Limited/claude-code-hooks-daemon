"""Tests for WorktreeCreateHandler (Plan 00188).

The handler owns Claude Code's WorktreeCreate hook: it creates a git worktree at
a human-friendly semantic path and returns that absolute path. Claude Code parses
the hook's stdout as the created path, so the response must be the real path (a
directory that exists) and must NEVER be an empty ``{}`` (the original bug, which
Claude Code took literally as ``/<cwd>/{}``).

Tests run against a real temporary git repo — faithful to the production path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.handlers.worktree_create.worktree_create_handler import (
    WorktreeCreateHandler,
)


def _init_repo(root: Path) -> None:
    """Create a git repo with one commit so worktrees can branch from HEAD."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    return root


class TestInitialisation:
    def test_registers_for_worktree_create_event(self) -> None:
        handler = WorktreeCreateHandler()
        assert handler.config_key == "worktree_create"

    def test_matches_all_worktree_create_events(self) -> None:
        handler = WorktreeCreateHandler()
        assert handler.matches({"hook_event_name": EventType.WORKTREE_CREATE.value}) is True


class TestHandle:
    def _input(self, repo: Path, name: str = "Refactor Auth") -> dict:
        return {
            "hook_event_name": EventType.WORKTREE_CREATE.value,
            "cwd": str(repo),
            "name": name,
            "prompt_id": "pid-123",
            "session_id": "sid-456",
        }

    def test_creates_worktree_directory(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        assert result.worktree_path is not None
        assert Path(result.worktree_path).is_dir()

    def test_path_is_semantic_and_absolute(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        path = Path(result.worktree_path or "")
        assert path.is_absolute()
        assert path.name.startswith("refactor-auth-")
        assert str(path).startswith(f"{repo}/.claude/worktrees/")

    def test_registers_a_real_git_worktree(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        listing = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert result.worktree_path in listing

    def test_response_json_is_worktree_path_not_braces(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        payload = result.to_json(EventType.WORKTREE_CREATE.value)
        assert payload == {"worktreePath": result.worktree_path}
        assert payload != {}
        assert "{}" not in str(payload["worktreePath"])

    def test_idempotent_on_refire(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        first = handler.handle(self._input(repo))
        second = handler.handle(self._input(repo))
        assert first.worktree_path == second.worktree_path
        assert Path(second.worktree_path or "").is_dir()

    def test_returns_hook_result(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        assert isinstance(handler.handle(self._input(repo)), HookResult)

    def test_unnamed_agent_falls_back_to_worktree_slug(self, repo: Path) -> None:
        handler = WorktreeCreateHandler()
        payload = self._input(repo, name="")
        result = handler.handle(payload)
        assert Path(result.worktree_path or "").name.startswith("worktree-")
