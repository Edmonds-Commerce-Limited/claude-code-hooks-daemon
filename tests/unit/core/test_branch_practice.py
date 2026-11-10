"""Tests for the branch-practice advisories: recovery-copy names, nested worktrees."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.branch_guard import RECOVERY_COPY_PATTERNS
from claude_code_hooks_daemon.core.branch_practice import (
    nested_worktree_advisory,
    recovery_copy_advisory,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    return root


def test_patterns_are_the_documented_set() -> None:
    assert set(RECOVERY_COPY_PATTERNS) == {
        "rescue/*",
        "recovery/*",
        "backup/*",
        "*-rescue",
        "*-backup",
    }


@pytest.mark.parametrize(
    "name",
    ["rescue/plan-12", "recovery/x", "backup/old", "plan-12-rescue", "feature-backup"],
)
def test_recovery_shaped_names_draw_the_archive_advice(name: str) -> None:
    advice = recovery_copy_advisory(name)
    assert advice is not None
    assert name in advice
    assert "refs/archive/" in advice and "bundle" in advice


@pytest.mark.parametrize("name", ["feature/rescue-flow", "backups", "plan-12", "rescued"])
def test_ordinary_names_draw_nothing(name: str) -> None:
    assert recovery_copy_advisory(name) is None


def test_worktree_inside_a_linked_worktree_names_the_main_checkout(
    repo: Path, tmp_path: Path
) -> None:
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "one", str(linked))
    advice = nested_worktree_advisory(linked, "inner")
    assert advice is not None
    assert str(repo.resolve()) in advice
    assert "never nested" in advice


def test_absolute_target_inside_a_linked_worktree_is_nested(repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "one", str(linked))
    assert nested_worktree_advisory(repo, str(linked / "deep" / "inner")) is not None


def test_worktree_under_the_main_checkout_is_fine(repo: Path) -> None:
    assert nested_worktree_advisory(repo, ".claude/worktrees/x") is None


def test_sibling_of_a_linked_worktree_is_fine(repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "one", str(linked))
    assert nested_worktree_advisory(linked, "../sibling") is None


def test_a_directory_that_is_not_a_repository_draws_nothing(tmp_path: Path) -> None:
    assert nested_worktree_advisory(tmp_path, "inner") is None
