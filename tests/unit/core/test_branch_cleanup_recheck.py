"""Bulk clean re-checks a worktree right before it removes it (Plan 00618 N-2)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_cleanup import clean_sweep

_CONFIG = BranchesConfig(default="main")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "checkout", "-q", "-b", "main")
    (root / ".gitignore").write_text("*.log\nuntracked/\n")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "root")
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    _git(root, "branch", "done")
    return root


def test_an_ignored_file_added_after_the_first_check_stops_the_removal(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", str(wt), "done")
    real = branch_cleanup._ref_exists
    real_blockers = branch_cleanup.worktree_blockers
    late = wt / "late-work.log"
    first_check_done: list[bool] = []

    def blockers_seen(*args: Any) -> Any:
        found = real_blockers(*args)
        first_check_done.append(True)
        return found

    def ref_exists_then_work_lands(repo_arg: Path, ref: str) -> bool:
        # The first check has passed by now; work lands before the removal.
        if first_check_done:
            late.write_text("unsaved\n")
        return real(repo_arg, ref)

    monkeypatch.setattr(branch_cleanup, "worktree_blockers", blockers_seen)
    monkeypatch.setattr(branch_cleanup, "_ref_exists", ref_exists_then_work_lands)
    report = clean_sweep(repo, _CONFIG, dry_run=False)
    assert first_check_done, "the worktree was never checked"
    assert late.read_text() == "unsaved\n"
    assert wt not in report.removed_worktrees
    assert any("late-work.log" in line for line in report.skipped)
