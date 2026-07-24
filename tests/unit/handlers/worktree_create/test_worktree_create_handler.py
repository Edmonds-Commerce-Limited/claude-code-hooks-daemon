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
    DEFAULT_WORKTREE_COPY_FILES,
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


class TestEnvFileSeeding:
    """Fresh worktrees seed git-ignored local files from the repo top-level.

    Local env files (.env.local, .env.test.local) are git-ignored, so a fresh
    worktree checkout has none of them. The handler copies a configurable list
    from the main working copy so the worktree behaves like the main checkout.
    Fixtures use dummy content only — never real secrets.
    """

    def _input(self, repo: Path, name: str = "Seed Env") -> dict:
        return {
            "hook_event_name": EventType.WORKTREE_CREATE.value,
            "cwd": str(repo),
            "name": name,
            "prompt_id": "pid-seed",
            "session_id": "sid-seed",
        }

    def test_default_env_files_copied_into_worktree(self, repo: Path) -> None:
        for fname in DEFAULT_WORKTREE_COPY_FILES:
            (repo / fname).write_text(f"SEED={fname}\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        for fname in DEFAULT_WORKTREE_COPY_FILES:
            copied = worktree / fname
            assert copied.is_file(), f"{fname} should be seeded into the worktree"
            assert copied.read_text(encoding="utf-8") == f"SEED={fname}\n"

    def test_missing_files_are_skipped_without_error(self, repo: Path) -> None:
        # Only one of the default files exists; the other must be skipped cleanly.
        present = DEFAULT_WORKTREE_COPY_FILES[0]
        (repo / present).write_text("SEED=present\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        assert (worktree / present).is_file()
        for absent in DEFAULT_WORKTREE_COPY_FILES[1:]:
            assert not (worktree / absent).exists()

    def test_no_recopy_on_idempotent_refire(self, repo: Path) -> None:
        fname = DEFAULT_WORKTREE_COPY_FILES[0]
        (repo / fname).write_text("SEED=original\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        first = handler.handle(self._input(repo))
        worktree = Path(first.worktree_path or "")

        # Simulate an edit made inside the worktree after creation.
        (worktree / fname).write_text("SEED=edited-in-worktree\n", encoding="utf-8")

        # A re-fired event for the same agent reuses the worktree and MUST NOT
        # clobber the in-worktree edit.
        handler.handle(self._input(repo))
        assert (worktree / fname).read_text(encoding="utf-8") == "SEED=edited-in-worktree\n"

    def test_configured_copy_files_list_is_honoured(self, repo: Path) -> None:
        (repo / "custom.env").write_text("SEED=custom\n", encoding="utf-8")
        (repo / ".env.local").write_text("SEED=default-not-configured\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        # Simulate the registry applying the `copy_files` option.
        handler._copy_files = ["custom.env"]
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        assert (worktree / "custom.env").is_file()
        # A default file NOT in the configured list is not copied.
        assert not (worktree / ".env.local").exists()

    def test_unsafe_entries_are_ignored(self, repo: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside-secret.env"
        outside.write_text("SEED=outside\n", encoding="utf-8")

        handler = WorktreeCreateHandler()
        handler._copy_files = ["../outside-secret.env", str(outside)]
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        # Neither a traversal entry nor an absolute path escapes into the worktree.
        assert not (worktree / "outside-secret.env").exists()
        assert list(worktree.glob("**/outside-secret.env")) == []

    def test_copy_failure_does_not_break_worktree_creation(self, repo: Path) -> None:
        # A directory at the source name makes the copy raise (IsADirectoryError),
        # exercising the best-effort path: worktree creation must still succeed.
        (repo / ".env.local").mkdir()

        handler = WorktreeCreateHandler()
        handler._copy_files = [".env.local"]
        result = handler.handle(self._input(repo))
        worktree = Path(result.worktree_path or "")

        assert worktree.is_dir()
        assert result.worktree_path is not None
