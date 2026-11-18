"""Throwaway git repositories for the branch pool warning ladder tests (Plan 00619).

One home for the builders the ladder, the two ladder handlers and the stop and
session-start surfaces all need, so a change to how a test repository is made is
made once.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def git(repo: Path, *args: str, author_email: str = "t@example.com") -> str:
    """Run ``git`` in ``repo`` with a fixed identity and no user or system config."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": author_email,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def init_repo(tmp_path: Path) -> Path:
    """A repository on ``main`` holding one empty root commit."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "root")
    return root


def init_repo_with_remote(tmp_path: Path) -> Path:
    """Like :func:`init_repo`, cloned from a bare ``origin`` that holds ``main``."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    git(tmp_path, "clone", "-q", str(remote), str(root))
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "checkout", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "root")
    git(root, "push", "-q", "-u", "origin", "main")
    git(root, "remote", "set-head", "origin", "main")
    return root


def add_open_branches(repo: Path, count: int) -> None:
    """``count`` local branches ``work-NN``, each one commit past ``main``."""
    tree = git(repo, "rev-parse", "main^{tree}")
    for index in range(count):
        sha = git(repo, "commit-tree", tree, "-p", "main", "-m", f"work {index}")
        git(repo, "update-ref", f"refs/heads/work-{index:02d}", sha)
