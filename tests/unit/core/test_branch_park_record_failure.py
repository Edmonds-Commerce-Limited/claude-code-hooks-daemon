"""A park whose record cannot be written leaves the branch where it was (Plan 00618 N-6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import branch_park
from claude_code_hooks_daemon.core.branch_park import BranchParkError, park_branch


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "branch", "work")
    return root


def _locked(*_args: str) -> None:
    raise BranchParkError("config.lock is held")


def test_a_failed_record_write_puts_the_branch_back(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _git(repo, "rev-parse", "work")
    monkeypatch.setattr(branch_park, "_config_write", lambda *_a: _locked())
    with pytest.raises(BranchParkError, match="nothing changed"):
        park_branch(repo, "work", reason="waiting", remote="origin", push=False)
    assert _git(repo, "rev-parse", "work") == before
