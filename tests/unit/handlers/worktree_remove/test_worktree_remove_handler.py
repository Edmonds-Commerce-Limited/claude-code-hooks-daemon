"""Tests for WorktreeRemoveHandler (Plan 00188).

Because the daemon now OWNS worktree creation (real git worktrees), it also
cleans them up on WorktreeRemove so ``git worktree list`` never accumulates
stale registrations. WorktreeRemove is a side-effect event — an empty ``{}``
response is safe — so the handler never blocks and never fails the event.

Claude Code's exact WorktreeRemove payload was not observed (it did not fire for
a Task-tool worktree), so the handler is deliberately payload-defensive:

- ALWAYS ``git worktree prune`` (path-independent; only removes registrations
  whose directories are already gone — never touches a live worktree).
- ADDITIONALLY ``git worktree remove --force <path>`` when the payload carries a
  recognisable worktree path that still exists.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.handlers.worktree_remove.worktree_remove_handler import (
    WorktreeRemoveHandler,
)


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)


def _add_worktree(root: Path, name: str) -> Path:
    wt = root / ".claude" / "worktrees" / name
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "-b", name, str(wt)],
        check=True,
        capture_output=True,
        text=True,
    )
    return wt


def _worktree_list(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "worktree", "list"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    return root


class TestInitialisation:
    def test_config_key(self) -> None:
        assert WorktreeRemoveHandler().config_key == "worktree_remove"

    def test_matches_all_events(self) -> None:
        handler = WorktreeRemoveHandler()
        assert handler.matches({"hook_event_name": EventType.WORKTREE_REMOVE.value}) is True


class TestHandle:
    def test_returns_empty_hook_result(self, repo: Path) -> None:
        handler = WorktreeRemoveHandler()
        result = handler.handle({"cwd": str(repo)})
        assert isinstance(result, HookResult)
        assert result.to_json(EventType.WORKTREE_REMOVE.value) == {}

    def test_prunes_deleted_worktree_registration(self, repo: Path) -> None:
        wt = _add_worktree(repo, "gone-abc123")
        assert wt.name in _worktree_list(repo)
        # Simulate Claude Code deleting the directory but leaving the registration
        import shutil

        shutil.rmtree(wt)
        WorktreeRemoveHandler().handle({"cwd": str(repo)})
        assert wt.name not in _worktree_list(repo)

    def test_removes_worktree_when_path_given(self, repo: Path) -> None:
        wt = _add_worktree(repo, "live-def456")
        assert wt.exists()
        WorktreeRemoveHandler().handle({"cwd": str(repo), "worktree_path": str(wt)})
        assert not wt.exists()
        assert wt.name not in _worktree_list(repo)

    def test_leaves_unrelated_live_worktree_untouched(self, repo: Path) -> None:
        keep = _add_worktree(repo, "keep-me-111")
        WorktreeRemoveHandler().handle({"cwd": str(repo)})
        assert keep.exists()
        assert keep.name in _worktree_list(repo)

    def test_missing_cwd_is_clean_noop(self) -> None:
        # No cwd / not a repo: must not raise.
        result = WorktreeRemoveHandler().handle({})
        assert result.to_json(EventType.WORKTREE_REMOVE.value) == {}

    def test_nonexistent_path_is_clean_noop(self, repo: Path) -> None:
        result = WorktreeRemoveHandler().handle(
            {"cwd": str(repo), "worktree_path": str(repo / ".claude/worktrees/nope")}
        )
        assert result.to_json(EventType.WORKTREE_REMOVE.value) == {}
