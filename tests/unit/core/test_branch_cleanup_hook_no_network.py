"""Hook-path cleanup never runs the remote proof, so it makes no network call (Plan 00618 N-4)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_cleanup import cleanup_after_merge, delete_if_merged

_CONFIG = BranchesConfig(default="main")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    _git(root, "checkout", "-q", "-b", "feat")
    (root / "f.txt").write_text("x")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "work")
    _git(root, "push", "-q", "origin", "feat")
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "--no-ff", "-q", "-m", "Merge feat", "feat")
    return root


@pytest.fixture(autouse=True)
def _no_remote_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("the remote proof (ls-remote) ran on a hook path")

    monkeypatch.setattr(branch_cleanup, "prove_remote_merged", forbidden)


def test_cleanup_after_merge_gives_owner_only_remote_wording(repo: Path) -> None:
    report = cleanup_after_merge(repo, ["feat"], config=_CONFIG, target="main", mode="act")
    assert report.deleted == ("feat",)
    assert any("origin/feat is for the owner" in c for c in report.commands)
    assert not any(c.startswith("git push origin --delete") for c in report.commands)


def test_delete_if_merged_gives_owner_only_remote_wording(repo: Path) -> None:
    report = delete_if_merged(repo, "feat", config=_CONFIG, default="main")
    assert report.deleted == ("feat",)
    assert any("origin/feat is for the owner" in c for c in report.commands)
