"""A park record is cleared only for a branch that was actually deleted (Plan 00618 N-3)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_cleanup import (
    clean_sweep,
    cleanup_after_merge,
    delete_if_merged,
)
from claude_code_hooks_daemon.core.branch_park import park_branch, read_park_record
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport

_CONFIG = BranchesConfig(default="main")
_REASON = "waiting on review"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
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
    _git(root, "checkout", "-q", "-b", "work")
    (root / "f.txt").write_text("x")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "work")
    park_branch(root, "work", reason=_REASON, remote="origin")
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "--no-ff", "-q", "-m", "Merge work", "work")
    return root


@pytest.fixture(autouse=True)
def _delete_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tip moved after classification: the delete engine refuses and deletes nothing."""

    def refuse(_repo: Path, names: list[str], **_kw: Any) -> DeletionReport:
        return DeletionReport(refused=True, blockers=tuple(f"{n}: tip moved" for n in names))

    monkeypatch.setattr(branch_cleanup, "delete_branches", refuse)


def _kept(repo: Path) -> bool:
    return read_park_record(repo, "work") is not None


def test_cleanup_after_merge_act_keeps_the_record_of_a_refused_delete(repo: Path) -> None:
    report = cleanup_after_merge(repo, ["work"], config=_CONFIG, target="main", mode="act")
    assert report.deleted == ()
    assert report.park_cleared == ()
    assert _kept(repo)


def test_delete_if_merged_keeps_the_record_of_a_refused_delete(repo: Path) -> None:
    report = delete_if_merged(repo, "work", config=_CONFIG, default="main")
    assert report.deleted == ()
    assert report.park_cleared == ()
    assert _kept(repo)


def test_clean_sweep_keeps_the_record_of_a_refused_delete(repo: Path) -> None:
    report = clean_sweep(repo, _CONFIG, dry_run=False)
    assert report.deleted == ()
    assert report.park_cleared == ()
    assert _kept(repo)
