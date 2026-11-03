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


def test_auto_delegates_to_default_branch_with_the_configured_remote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[tuple[Path, str]] = []

    def fake(cwd: Path, *, remote: str) -> str:
        seen.append((cwd, remote))
        return "develop"

    monkeypatch.setattr(git_sync, "default_branch", fake)
    config = BranchesConfig(remote="upstream")
    assert git_sync.resolve_default_branch(config, tmp_path) == "develop"
    assert seen == [(tmp_path, "upstream")]


def _clone_without_head_or_local_default(tmp_path: Path, remote_name: str, branch: str) -> Path:
    """A clone holding only ``<remote>/<branch>``: no ``<remote>/HEAD``, no local default."""
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q", "-b", branch)
    _git(
        source,
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
    clone = tmp_path / "clone"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "work")
    _git(clone, "remote", "add", remote_name, str(source))
    _git(clone, "fetch", "-q", remote_name)
    return clone


@pytest.mark.parametrize("branch", ["main", "master"])
def test_auto_falls_back_to_the_remote_tracking_main_or_master(tmp_path: Path, branch: str) -> None:
    clone = _clone_without_head_or_local_default(tmp_path, "origin", branch)
    assert git_sync.resolve_default_branch(BranchesConfig(), clone) == branch


def test_auto_reads_the_configured_remote(tmp_path: Path) -> None:
    clone = _clone_without_head_or_local_default(tmp_path, "upstream", "main")
    _git(clone, "remote", "set-head", "upstream", "main")
    assert git_sync.resolve_default_branch(BranchesConfig(remote="upstream"), clone) == "main"
    # The default remote has no such refs, so `origin` cannot answer.
    assert git_sync.resolve_default_branch(BranchesConfig(), clone) is None


def test_default_branch_reads_head_of_the_named_remote(tmp_path: Path) -> None:
    clone = _clone_without_head_or_local_default(tmp_path, "upstream", "trunk")
    _git(clone, "remote", "set-head", "upstream", "trunk")
    assert git_sync.default_branch(clone, remote="upstream") == "trunk"
    assert git_sync.default_branch(clone) is None
