"""A scratch clone whose remote holds branches only outside ``refs/heads`` (issue #166).

The remote is a bare repository; ``archived`` is pushed ONLY under
``refs/archive/archived``, which the default refspec never fetches, so the clone
has no remote-tracking ref for it. ``archived-child`` is held by a remote ref one
commit ABOVE its tip, and ``unpushed`` is held nowhere.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

NOW = 1_800_000_000
DAY = 86_400


def _env(days_ago: float) -> dict[str, str]:
    stamp = f"@{int(NOW - days_ago * DAY)} +0000"
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def git(repo: Path, *args: str, days_ago: float = 0) -> str:
    """Run git in ``repo`` with pinned identity and date; raises on failure."""
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(days_ago),
    )
    return result.stdout.strip()


def commit(repo: Path, name: str, days_ago: float) -> str:
    """Commit one new file called ``name`` and return the new sha."""
    (repo / f"{name}.txt").write_text(f"{name}\n")
    git(repo, "add", f"{name}.txt")
    git(repo, "commit", "-q", "-m", name, days_ago=days_ago)
    return git(repo, "rev-parse", "HEAD")


@dataclass(frozen=True)
class ArchiveRepo:
    """The scratch clone and the shas the tests assert on."""

    clone: Path
    remote: Path
    archived_tip: str
    child_tip: str


def build(root: Path) -> ArchiveRepo:
    """Create the bare remote and the clone under ``root``."""
    remote = root / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    clone = root / "clone"
    clone.mkdir()
    git(clone, "init", "-q", "-b", "main")
    git(clone, "remote", "add", "origin", str(remote))
    commit(clone, "base", 60)
    git(clone, "push", "-q", "origin", "main")
    git(clone, "fetch", "-q", "origin")

    git(clone, "checkout", "-q", "-b", "archived", "main")
    archived_tip = commit(clone, "arch", 44)
    git(clone, "push", "-q", "origin", "archived:refs/archive/archived")

    git(clone, "checkout", "-q", "-b", "archived-child", "main")
    commit(clone, "kid", 43)
    git(clone, "checkout", "-q", "-b", "scratch-above")
    child_tip = commit(clone, "kid-more", 42)
    git(clone, "push", "-q", "origin", "scratch-above:refs/archive/kid-above")
    git(clone, "checkout", "-q", "main")
    git(clone, "branch", "-q", "-D", "scratch-above")

    git(clone, "checkout", "-q", "-b", "unpushed", "main")
    commit(clone, "lost", 41)
    git(clone, "checkout", "-q", "main")
    return ArchiveRepo(clone, remote, archived_tip, child_tip)
