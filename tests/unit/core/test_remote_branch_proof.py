"""The shared remote-delete proof (Plan 00571 Task 2.2).

The same proof backs the ``destructive_git`` remote-delete guard and
``branch-sweep --clean --remote``. Real repositories with a bare remote: the
subject is git's ancestry and what the remote itself reports.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.remote_branch_proof import (
    branch_name,
    named_ref_problem,
    prove_remote_merged,
)

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


def _pushed_branch(repo: Path, name: str, *, merge: bool) -> str:
    _git(repo, "checkout", "-q", "-b", name)
    _commit(repo, name)
    _git(repo, "push", "--quiet", "origin", name)
    _git(repo, "checkout", "-q", "main")
    if merge:
        _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
        _git(repo, "push", "--quiet", "origin", "main")
    return _git(repo, "rev-parse", f"refs/heads/{name}").strip()


class TestNamedRefProblem:
    @pytest.mark.parametrize(
        ("ref", "fragment"),
        [
            ("main", "default branch"),
            ("users/joe", "exempt"),
            ("master", "protected"),
            ("refs/tags/v1", "not a literal branch name"),
            ("a;b", "not a literal branch name"),
        ],
    )
    def test_refused_names(self, ref: str, fragment: str) -> None:
        problem = named_ref_problem("origin", ref, "main", _CONFIG)
        assert problem is not None
        assert fragment in problem

    def test_an_ordinary_name_passes(self) -> None:
        assert named_ref_problem("origin", "refs/heads/feat", "main", _CONFIG) is None

    def test_branch_name_strips_the_heads_prefix(self) -> None:
        assert branch_name("refs/heads/feat") == "feat"


class TestProveRemoteMerged:
    def test_a_merged_branch_is_proven_with_its_live_tip(self, repo: Path) -> None:
        tip = _pushed_branch(repo, "feat", merge=True)
        proof = prove_remote_merged(repo, "origin", ["feat"], "main", _CONFIG)
        assert proof.tips == {"feat": tip}
        assert proof.problems == {}

    def test_an_unmerged_branch_is_a_problem(self, repo: Path) -> None:
        _pushed_branch(repo, "novel", merge=False)
        proof = prove_remote_merged(repo, "origin", ["novel"], "main", _CONFIG)
        assert proof.tips == {}
        assert "not merged" in proof.problems["novel"]

    def test_a_commit_pushed_since_the_fetch_is_never_proven(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _pushed_branch(repo, "feat", merge=True)
        other = tmp_path / "other"
        _git(tmp_path, "clone", "--quiet", str(tmp_path / "remote.git"), str(other))
        _git(other, "checkout", "-q", "feat")
        _commit(other, "late")
        _git(other, "push", "--quiet", "origin", "feat")
        proof = prove_remote_merged(repo, "origin", ["feat"], "main", _CONFIG)
        assert proof.tips == {}
        assert "could not be confirmed" in proof.problems["feat"]

    def test_a_tag_of_the_same_name_is_ambiguous(self, repo: Path) -> None:
        _pushed_branch(repo, "feat", merge=True)
        _git(repo, "tag", "feat")
        proof = prove_remote_merged(repo, "origin", ["feat"], "main", _CONFIG)
        assert "tag" in proof.problems["feat"]

    def test_no_tracking_ref_is_a_problem(self, repo: Path) -> None:
        proof = prove_remote_merged(repo, "origin", ["ghost"], "main", _CONFIG)
        assert "no remote-tracking ref" in proof.problems["ghost"]

    def test_a_line_merged_only_into_another_line_is_refused(self, repo: Path) -> None:
        _git(repo, "branch", "release/2", "main")
        _git(repo, "push", "--quiet", "origin", "release/2")
        _pushed_branch(repo, "release/1", merge=False)
        _git(repo, "checkout", "-q", "release/2")
        _git(repo, "merge", "--no-ff", "-q", "-m", "Merge release/1", "release/1")
        _git(repo, "push", "--quiet", "origin", "release/2")
        _git(repo, "checkout", "-q", "main")
        proof = prove_remote_merged(repo, "origin", ["release/1"], "main", _CONFIG)
        assert "integration line not yet merged" in proof.problems["release/1"]
