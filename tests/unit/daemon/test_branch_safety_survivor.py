"""A local branch contained in another branch the remote still holds (ledger N751).

The owner's rule: a branch contained in another branch that survives loses nothing
when it goes. For a LOCAL delete that is the remote-held tier: a live remote ref at
or above the tip. These tests pin it, and pin the refusals that must stay.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.daemon.branch_safety import TIER_REMOTE_HELD, classify_branch
from claude_code_hooks_daemon.utils.remote_refs import list_remote_refs

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    ).stdout


def _commit(repo: Path, name: str) -> None:
    (repo / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", f"{name}.txt")
    _git(repo, "commit", "-m", f"Add {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(bare))
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _commit(path, "base")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "--quiet", "origin", "main")
    _git(path, "remote", "set-head", "origin", "main")
    return path


def _classify(repo: Path, name: str) -> branch_safety.BranchClassification:
    return classify_branch(
        repo,
        name,
        protected_ref="origin/main",
        remote_listing=list_remote_refs(repo, "origin"),
    )


def test_a_local_branch_inside_a_pushed_long_lived_branch_is_remote_held(repo: Path) -> None:
    """`u2` is an ancestor of the pushed `v2-smoke`, which merges nowhere."""
    _git(repo, "checkout", "-q", "-b", "u2")
    _commit(repo, "u2")
    _git(repo, "checkout", "-q", "-b", "v2-smoke")
    _commit(repo, "smoke")
    _git(repo, "push", "--quiet", "origin", "v2-smoke")
    _git(repo, "checkout", "-q", "main")
    verdict = _classify(repo, "u2")
    assert verdict.tier == TIER_REMOTE_HELD
    assert verdict.refusal is None


def test_a_local_branch_nothing_remote_holds_is_not_proven(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "solo")
    _commit(repo, "solo")
    _git(repo, "checkout", "-q", "main")
    verdict = _classify(repo, "solo")
    assert verdict.tier != TIER_REMOTE_HELD
