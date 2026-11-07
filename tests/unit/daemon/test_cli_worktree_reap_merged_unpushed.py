"""``worktree-reap --reap-branches`` agrees with ``delete-branch`` on a merged-unpushed branch.

A branch merged into the default but ahead of its own upstream is refused by
``git branch -d``; ``delete-branch`` classifies it ``merged-unpushed`` and deletes it
losslessly behind a recovery bundle. The reaper used to print it, keep it, and exit 0
(ledger N585). These tests use a real repository and a real remote because the
condition under test is one git evaluates against ``refs/remotes/origin/<name>``.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import worktree_reaping
from claude_code_hooks_daemon.daemon.branch_safety import DeletionReport
from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap

_BRANCH = "agent-merged-ahead"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test Author")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test Author")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    monkeypatch.setenv("HOME", str(tmp_path))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """``main`` plus an ``agent-*`` branch merged into it and one commit ahead of its upstream."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(bare)], check=True)
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    _commit(path, "base.txt", "base\n", "Initial commit")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "checkout", "-b", _BRANCH)
    _commit(path, "f.txt", "one\n", "Add f")
    _git(path, "push", "--quiet", "--set-upstream", "origin", _BRANCH)
    _commit(path, "f.txt", "one\ntwo, unpushed\n", "Second commit, never pushed")
    _git(path, "checkout", "main")
    _git(path, "merge", "--no-ff", "-m", f"Merge {_BRANCH}", _BRANCH)
    return path


def _args(repo: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=str(repo), base_branch="main", reap=False, only=None, reap_branches=True
    )


def _branches(repo: Path) -> set[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    return {line.removeprefix("refs/heads/") for line in out.splitlines() if line}


def test_git_alone_refuses_the_fixture_branch(repo: Path) -> None:
    """Guards the fixture: if plain ``branch -d`` succeeded this would prove nothing."""
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "-d", _BRANCH], capture_output=True, text=True
    )
    assert result.returncode != 0


def test_a_merged_unpushed_branch_is_deleted_and_bundled(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_worktree_reap(_args(repo))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert _BRANCH not in _branches(repo)
    assert "PRUNED" in out
    assert list((repo / "untracked" / "deleted-branches").glob("*.bundle"))


def test_a_kept_merged_branch_is_reported_as_kept_and_fails_the_run(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_a: object, **_k: object) -> DeletionReport:
        return DeletionReport(refused=True, blockers=(f"{_BRANCH}: the tip moved",))

    monkeypatch.setattr(worktree_reaping, "delete_branches", refuse)
    rc = cmd_worktree_reap(_args(repo))
    out = capsys.readouterr().out
    assert rc == 1
    assert "KEPT" in out and "the tip moved" in out
    assert "PRUNED" not in out
    assert _BRANCH in _branches(repo)


def test_an_unclassifiable_git_failure_is_reported_as_kept(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> DeletionReport:
        raise subprocess.CalledProcessError(127, ["git"], stderr="timed out")

    monkeypatch.setattr(worktree_reaping, "delete_branches", boom)
    rc = cmd_worktree_reap(_args(repo))
    out = capsys.readouterr().out
    assert rc == 1
    assert "KEPT" in out and "timed out" in out
    assert _BRANCH in _branches(repo)
