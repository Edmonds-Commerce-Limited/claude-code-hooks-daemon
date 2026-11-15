"""``delete-branch --protected-ref`` must not let the caller choose its own proof.

The proof target is the ref a branch is measured against. If the caller may name
ANY ref, naming the branch itself (or a sha, or an unmerged sibling holding it)
makes every branch "merged" and the delete goes through: the deleting agent has
asserted its own proof, which is the one thing a delete gate must never accept.
"""

from __future__ import annotations

import argparse
import io
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_delete_branch

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}

_EXIT_REFUSED = 1
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
    """A repo on main whose ``doomed`` branch holds unique work, plus a sibling holding it."""
    path = tmp_path / "repo"
    path.mkdir()
    (path / ".claude" / "hooks-daemon").mkdir(parents=True)
    _git(path, "init", "-b", "main")
    _commit(path, "base.txt", "base\n", "Initial commit")
    _git(path, "checkout", "-b", "doomed")
    _commit(path, "only-here.txt", "unique work\n", "Work only on the branch")
    _git(path, "checkout", "-b", "sibling")
    _commit(path, "more.txt", "more\n", "Sibling on top of doomed")
    _git(path, "checkout", "main")
    return path


def _args(repo: Path, **overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "project_root": repo,
        "branches": ["doomed"],
        "protected_ref": None,
        "dry_run": False,
        "format": "text",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestProofTargetIsNotCallerChosen:
    """Unmerged work survives whatever ref the caller names as the proof target."""

    @pytest.mark.parametrize(
        "target",
        ["doomed", "refs/heads/doomed", "sibling", "TIP_SHA"],
    )
    def test_naming_the_branch_or_a_holder_as_target_deletes_nothing(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, target: str
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        if target == "TIP_SHA":
            target = _git(repo, "rev-parse", "doomed").strip()
        exit_code = cmd_delete_branch(_args(repo, protected_ref=target))
        assert exit_code == _EXIT_USAGE
        assert "doomed" in _git(repo, "branch", "--list")

    def test_the_default_target_still_refuses_unmerged_work(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        assert cmd_delete_branch(_args(repo)) == _EXIT_REFUSED
        assert "doomed" in _git(repo, "branch", "--list")

    def test_the_default_branch_named_explicitly_is_accepted(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO())
        _git(repo, "merge", "--ff-only", "doomed")
        assert cmd_delete_branch(_args(repo, protected_ref="main")) == 0
        assert "doomed" not in _git(repo, "branch", "--list")
