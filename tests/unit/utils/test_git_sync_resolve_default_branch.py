"""`resolve_default_branch` (Plan 00558 Task 2.0, DESIGN.md section 1).

A named `branches.default` wins; `auto` falls back to `git_sync.default_branch`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.utils import git_sync


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "master")
    _git(
        tmp_path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "c",
    )
    return tmp_path


def test_named_default_wins_without_asking_git(tmp_path: Path) -> None:
    """A named default is returned as written, even where git would say otherwise."""
    config = BranchesConfig(default="trunk")
    assert git_sync.resolve_default_branch(config, tmp_path) == "trunk"


def test_auto_falls_back_to_default_branch(repo: Path) -> None:
    assert git_sync.resolve_default_branch(BranchesConfig(), repo) == "master"


def test_auto_returns_none_when_git_cannot_tell(tmp_path: Path) -> None:
    assert git_sync.resolve_default_branch(BranchesConfig(), tmp_path) is None


def test_auto_delegates_to_default_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[Path] = []

    def fake(cwd: Path) -> str:
        seen.append(cwd)
        return "develop"

    monkeypatch.setattr(git_sync, "default_branch", fake)
    assert git_sync.resolve_default_branch(BranchesConfig(), tmp_path) == "develop"
    assert seen == [tmp_path]
