"""A remote branch contained in another SURVIVING remote branch may be deleted (Q14).

The owner's ruling: a branch whose commits another branch that still exists
already holds loses nothing when it goes. The proof stays the guard's own: the
tip is an ancestor of a remote-tracking ref the same command does not delete,
confirmed against the remote's live tips. A sole holder stays refused.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}
_CONFIG = BranchesConfig(default="main", integration_lines=["release/*"], exempt=["users/*"])


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    ).stdout


def _commit(repo: Path, name: str) -> None:
    filename = f"{name.replace('/', '-')}.txt"
    (repo / filename).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", f"Add {filename}")


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
    return path


def _stack(repo: Path) -> None:
    """``inner`` (one commit) and ``outer`` (``inner`` plus one), neither merged to main."""
    _git(repo, "checkout", "-q", "-b", "inner")
    _commit(repo, "inner")
    _git(repo, "push", "--quiet", "origin", "inner")
    _git(repo, "checkout", "-q", "-b", "outer")
    _commit(repo, "outer")
    _git(repo, "push", "--quiet", "origin", "outer")
    _git(repo, "checkout", "-q", "main")


class TestAContainedBranchIsAdmitted:
    def test_a_branch_contained_in_a_surviving_branch_is_proven(self, repo: Path) -> None:
        _stack(repo)
        tip = _git(repo, "rev-parse", "refs/heads/inner").strip()
        proof = prove_remote_merged(repo, "origin", ["inner"], "main", _CONFIG)
        assert proof.tips == {"inner": tip}
        assert proof.problems == {}

    def test_two_branches_at_one_commit_each_survive_the_other(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "twin-a")
        _commit(repo, "twin")
        _git(repo, "push", "--quiet", "origin", "twin-a")
        _git(repo, "push", "--quiet", "origin", "twin-a:refs/heads/twin-b")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "fetch", "--quiet", "origin")
        proof = prove_remote_merged(repo, "origin", ["twin-a"], "main", _CONFIG)
        assert "twin-a" in proof.tips


class TestASoleHolderIsRefused:
    def test_the_outer_branch_holds_a_commit_nothing_else_has(self, repo: Path) -> None:
        _stack(repo)
        proof = prove_remote_merged(repo, "origin", ["outer"], "main", _CONFIG)
        assert proof.tips == {}
        assert "not merged" in proof.problems["outer"]

    def test_an_unrelated_branch_does_not_vouch(self, repo: Path) -> None:
        _stack(repo)
        _git(repo, "checkout", "-q", "-b", "elsewhere")
        _commit(repo, "elsewhere")
        _git(repo, "push", "--quiet", "origin", "elsewhere")
        _git(repo, "checkout", "-q", "main")
        proof = prove_remote_merged(repo, "origin", ["elsewhere"], "main", _CONFIG)
        assert proof.tips == {}


class TestTheSurvivorMustSurvive:
    def test_a_survivor_deleted_in_the_same_command_does_not_vouch(self, repo: Path) -> None:
        _stack(repo)
        proof = prove_remote_merged(repo, "origin", ["inner", "outer"], "main", _CONFIG)
        assert "inner" not in proof.tips
        assert "outer" not in proof.tips

    def test_a_survivor_named_only_as_also_deleting_does_not_vouch(self, repo: Path) -> None:
        _stack(repo)
        proof = prove_remote_merged(
            repo, "origin", ["inner"], "main", _CONFIG, also_deleting=["inner", "outer"]
        )
        assert proof.tips == {}

    def test_twins_deleted_together_are_both_refused(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "twin-a")
        _commit(repo, "twin")
        _git(repo, "push", "--quiet", "origin", "twin-a")
        _git(repo, "push", "--quiet", "origin", "twin-a:refs/heads/twin-b")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "fetch", "--quiet", "origin")
        proof = prove_remote_merged(repo, "origin", ["twin-a", "twin-b"], "main", _CONFIG)
        assert proof.tips == {}

    def test_a_survivor_that_moved_since_the_fetch_is_not_trusted(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _stack(repo)
        other = tmp_path / "other"
        _git(tmp_path, "clone", "--quiet", str(tmp_path / "remote.git"), str(other))
        _git(other, "checkout", "-q", "outer")
        _commit(other, "late")
        _git(other, "push", "--quiet", "--force", "origin", "outer~2:refs/heads/outer")
        proof = prove_remote_merged(repo, "origin", ["inner"], "main", _CONFIG)
        assert proof.tips == {}
        assert "inner" in proof.problems


class TestIntegrationLinesAreUnchanged:
    def test_a_line_contained_in_a_surviving_branch_is_still_refused(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "release/1")
        _commit(repo, "line")
        _git(repo, "push", "--quiet", "origin", "release/1")
        _git(repo, "checkout", "-q", "-b", "feature-on-line")
        _commit(repo, "on-line")
        _git(repo, "push", "--quiet", "origin", "feature-on-line")
        _git(repo, "checkout", "-q", "main")
        proof = prove_remote_merged(repo, "origin", ["release/1"], "main", _CONFIG)
        assert proof.tips == {}
        assert "integration line" in proof.problems["release/1"]
