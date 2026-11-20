"""WorktreeRemove's git calls follow host load (Plan 00474 N621, second entry).

Class: a hard failure gated on a fixed wall-clock budget for a git call whose
duration follows host load, inside an event whose total budget is pinned in
``Timeout.EVENT_HANDLER_BUDGET``. A removal killed at its fixed 30 s leaves a
half-deleted ``prunable`` worktree, so the removal is a base scaled by load and
bounded by a ceiling the event budget is sized for.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.events import EventType
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.handlers.worktree_remove import worktree_remove_handler as wrh
from claude_code_hooks_daemon.handlers.worktree_remove.worktree_remove_handler import (
    WorktreeRemoveHandler,
)

_SATURATED = (700.0, 700.0, 700.0)
_IDLE = (0.0, 0.0, 0.0)
_LOAD_PATH = "claude_code_hooks_daemon.utils.load_scaling.os.getloadavg"


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


def _run_recording(main_repo: Path, load: tuple[float, float, float]) -> dict[str, list[float]]:
    """Remove a real worktree with ``load`` reported; each git verb's timeouts."""
    worktree = main_repo / ".claude" / "worktrees" / "wt"
    _git(main_repo, "worktree", "add", "-q", "-b", "wt", str(worktree))
    seen: dict[str, list[float]] = {}
    real_run_git = wrh.run_git

    def recording(cwd: Path, *args: str, timeout: float = 0, **kwargs: Any) -> Any:
        seen.setdefault(" ".join(args[:2]), []).append(timeout)
        return real_run_git(cwd, *args, timeout=timeout, **kwargs)

    handler = WorktreeRemoveHandler()
    handler._branches = BranchesConfig(default="main")
    with patch.object(wrh, "run_git", recording), patch(_LOAD_PATH, return_value=load):
        handler.handle({"cwd": str(main_repo), "worktree_path": str(worktree)})
    assert "worktree remove" in seen, "the removal was never attempted"
    return seen


class TestRemovalFollowsHostLoad:
    def test_the_removal_is_scaled_to_the_ceiling_on_a_saturated_host(
        self, main_repo: Path
    ) -> None:
        seen = _run_recording(main_repo, _SATURATED)
        assert seen["worktree remove"] == [Timeout.GIT_WORKTREE_REMOVE_EVENT_MAX]

    def test_the_removal_keeps_its_base_on_an_idle_host(self, main_repo: Path) -> None:
        seen = _run_recording(main_repo, _IDLE)
        assert seen["worktree remove"] == [Timeout.GIT_WORKTREE]

    def test_the_metadata_calls_are_scaled_within_their_ceiling(self, main_repo: Path) -> None:
        seen = _run_recording(main_repo, _SATURATED)
        for verb in ("worktree list", "worktree prune"):
            assert seen[verb], verb
            assert all(
                Timeout.GIT_CONTEXT < value <= Timeout.GIT_BRANCH_METADATA_MAX
                for value in seen[verb]
            ), verb


class TestEventBudgetIsDerivedFromTheCeilings:
    def test_remove_budget_is_the_removal_ceiling_plus_the_metadata_calls(self) -> None:
        expected = (
            Timeout.GIT_WORKTREE_REMOVE_EVENT_MAX
            + Timeout.GIT_WORKTREE_REMOVE_METADATA_CALLS * Timeout.GIT_BRANCH_METADATA_MAX
        )
        assert Timeout.EVENT_HANDLER_BUDGET[EventType.WORKTREE_REMOVE] == expected
        assert expected == 170
        assert Timeout.EVENT_CLIENT_WAIT[EventType.WORKTREE_REMOVE] == 180

    def test_a_saturated_removal_is_not_capped_below_its_ceiling_by_the_clock(self) -> None:
        clock = wrh._Clock()
        ceiling = Timeout.GIT_WORKTREE_REMOVE_EVENT_MAX
        assert clock.timeout(ceiling, "the removal") == ceiling
