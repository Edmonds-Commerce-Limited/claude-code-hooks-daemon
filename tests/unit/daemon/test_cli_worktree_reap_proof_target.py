"""``worktree-reap --base-branch`` must not let the caller choose its own proof.

The base branch is the ref a branch is proved merged against. If the caller may
name any ref (the branch itself, a sibling holding it), unmerged work is "merged"
and the delete goes through. Only the default or a declared integration line may
prove a deletion safe, exactly as for ``delete-branch --protected-ref``.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_worktree_reap

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_EXIT_USAGE = 2


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo on main whose ``agent-doomed`` branch holds unique work and has no worktree."""
    path = tmp_path / "repo"
    path.mkdir()
    (path / ".claude" / "hooks-daemon").mkdir(parents=True)
    _git(path, "init", "-b", "main")
    _commit(path, "base.txt", "base\n", "Initial commit")
    _git(path, "checkout", "-b", "agent-doomed")
    _commit(path, "only-here.txt", "unique work\n", "Work only on the branch")
    _git(path, "checkout", "main")
    return path


def _args(repo: Path, **overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "project_root": repo,
        "base_branch": None,
        "reap": True,
        "only": None,
        "reap_branches": True,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestBaseBranchIsNotCallerChosen:
    """Unmerged work survives whatever ref the caller names as the base."""

    @pytest.mark.parametrize("target", ["agent-doomed", "refs/heads/agent-doomed", "TIP_SHA"])
    def test_naming_the_branch_itself_as_base_deletes_nothing(
        self, repo: Path, target: str
    ) -> None:
        if target == "TIP_SHA":
            target = _git(repo, "rev-parse", "agent-doomed").strip()
        assert cmd_worktree_reap(_args(repo, base_branch=target)) == _EXIT_USAGE
        assert "agent-doomed" in _git(repo, "branch", "--list")

    def test_the_default_branch_named_explicitly_is_accepted(self, repo: Path) -> None:
        assert cmd_worktree_reap(_args(repo, base_branch="main", reap_branches=False)) != (
            _EXIT_USAGE
        )
