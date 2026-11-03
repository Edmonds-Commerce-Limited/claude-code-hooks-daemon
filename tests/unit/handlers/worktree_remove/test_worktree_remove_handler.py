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
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.handlers.worktree_remove import worktree_remove_handler as wrh
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


# --- Plan 00558 Task 3.2: lossless removal, then delete the proven-merged branch ---

_ELIGIBLE = "fix-auth-1a2b3c4d"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    root = tmp_path / "main-repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text("untracked/\n.claude/worktrees/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _handler() -> WorktreeRemoveHandler:
    handler = WorktreeRemoveHandler()
    handler._branches = BranchesConfig(default="main")
    return handler


def _work(root: Path, name: str, *, merge: bool) -> Path:
    wt = _add_worktree(root, name)
    (wt / f"{name}.txt").write_text("work\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", f"work on {name}")
    if merge:
        _git(root, "merge", "-q", "--no-ff", "-m", f"Merge {name}", name)
    return wt


def _has_branch(root: Path, name: str) -> bool:
    return bool(_git(root, "branch", "--list", name).strip())


class TestBranchCleanup:
    def test_a_merged_worktree_create_branch_is_deleted(self, main_repo: Path) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=True)
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert not wt.exists()
        assert not _has_branch(main_repo, _ELIGIBLE)

    def test_an_unmerged_branch_is_kept_for_the_sweep(self, main_repo: Path) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=False)
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert not wt.exists()
        assert _has_branch(main_repo, _ELIGIBLE)

    def test_a_hand_named_merged_branch_is_kept(self, main_repo: Path) -> None:
        wt = _work(main_repo, "feature-x", merge=True)
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert not wt.exists()
        assert _has_branch(main_repo, "feature-x")

    def test_an_exempt_branch_is_kept(self, main_repo: Path) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=True)
        handler = _handler()
        handler._branches = BranchesConfig(default="main", exempt=["fix-*"])
        handler.handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert _has_branch(main_repo, _ELIGIBLE)

    def test_a_detached_worktree_is_removed_and_no_branch_touched(self, main_repo: Path) -> None:
        wt = main_repo / ".claude" / "worktrees" / "detached"
        _git(main_repo, "worktree", "add", "--detach", str(wt))
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert not wt.exists()
        assert _has_branch(main_repo, "main")


class TestLosslessRemoval:
    def test_scratch_notes_keep_the_worktree(
        self, main_repo: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=True)
        notes = wt / "untracked" / "scratch" / "notes.md"
        notes.parent.mkdir(parents=True)
        notes.write_text("my notes\n", encoding="utf-8")
        with caplog.at_level("WARNING"):
            _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert notes.read_text(encoding="utf-8") == "my notes\n"
        assert _has_branch(main_repo, _ELIGIBLE)
        assert "untracked/scratch/" in caplog.text

    def test_an_untracked_file_keeps_the_worktree(self, main_repo: Path) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=True)
        (wt / "new.txt").write_text("x\n", encoding="utf-8")
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert (wt / "new.txt").exists()

    def test_regenerable_stores_do_not_keep_the_worktree(self, main_repo: Path) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=True)
        (wt / "untracked" / "qa").mkdir(parents=True)
        (wt / "untracked" / "qa" / "out.json").write_text("{}\n", encoding="utf-8")
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert not wt.exists()

    def test_an_unregistered_directory_is_never_removed(self, main_repo: Path) -> None:
        stray = main_repo / ".claude" / "worktrees" / "stray"
        stray.mkdir(parents=True)
        (stray / "keep.txt").write_text("x\n", encoding="utf-8")
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(stray)})
        assert (stray / "keep.txt").exists()

    def test_the_main_checkout_is_never_removed(self, main_repo: Path) -> None:
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(main_repo)})
        assert (main_repo / ".gitignore").exists()


class TestForceOnlyWhenContained:
    @staticmethod
    def _removes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
        calls: list[tuple[str, ...]] = []
        real = wrh.run_git

        def spy(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("worktree", "remove"):
                calls.append(args)
            return real(cwd, *args, **kwargs)

        monkeypatch.setattr(wrh, "run_git", spy)
        return calls

    def test_head_contained_in_another_ref_uses_force(
        self, main_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=True)
        calls = self._removes(monkeypatch)
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert calls and "--force" in calls[0]

    def test_head_only_on_its_own_branch_is_removed_without_force(
        self, main_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=False)
        calls = self._removes(monkeypatch)
        _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert calls and "--force" not in calls[0]


class TestBudget:
    def test_an_exhausted_budget_reports_and_keeps_the_branch(
        self, main_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        wt = _work(main_repo, _ELIGIBLE, merge=True)
        clock = iter([0.0] + [1000.0] * 50)
        monkeypatch.setattr(wrh.time, "monotonic", lambda: next(clock))
        with caplog.at_level("WARNING"):
            _handler().handle({"cwd": str(main_repo), "worktree_path": str(wt)})
        assert _has_branch(main_repo, _ELIGIBLE)
        assert "budget" in caplog.text
