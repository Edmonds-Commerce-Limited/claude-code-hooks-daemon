"""``branch-sweep --clean --remote`` (Plan 00571 Task 2.2, issue #165).

Deletes provably merged REMOTE branches as well as local ones, by the remote
guard's own proof, behind the same recovery bundle. Real repositories with a
bare remote: the subject is what the remote actually holds afterwards.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_cleanup import CleanupReport, clean_sweep, render

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}
_CONFIG = BranchesConfig(default="main", exempt=["users/*"])


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
def bare(tmp_path: Path) -> Path:
    path = tmp_path / "remote.git"
    _git(tmp_path, "init", "--quiet", "--bare", "-b", "main", str(path))
    return path


@pytest.fixture
def repo(tmp_path: Path, bare: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / ".gitignore").write_text("untracked/\n", encoding="utf-8")
    _git(path, "add", ".gitignore")
    _git(path, "commit", "-m", "Initial commit")
    _git(path, "remote", "add", "origin", str(bare))
    _git(path, "push", "--quiet", "origin", "main")
    return path


def _pushed(repo: Path, name: str, *, merge: bool, keep_local: bool = True) -> str:
    _git(repo, "checkout", "-q", "-b", name)
    _commit(repo, name)
    _git(repo, "push", "--quiet", "origin", name)
    _git(repo, "checkout", "-q", "main")
    if merge:
        _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
        _git(repo, "push", "--quiet", "origin", "main")
    tip = _git(repo, "rev-parse", f"refs/heads/{name}").strip()
    if not keep_local:
        _git(repo, "branch", "-q", "-D", name)
    return tip


def _remote_branches(bare: Path) -> set[str]:
    out = _git(bare, "for-each-ref", "--format=%(refname)", "refs/heads")
    return {line.removeprefix("refs/heads/") for line in out.splitlines() if line}


def _sweep(repo: Path, tmp_path: Path, **kwargs: bool) -> CleanupReport:
    return clean_sweep(
        repo,
        _CONFIG,
        dry_run=kwargs.get("dry_run", False),
        bundle_dir=tmp_path / "b",
        remote=kwargs.get("remote", True),
    )


class TestRemoteClean:
    def test_without_the_flag_no_remote_branch_is_touched(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _pushed(repo, "feat", merge=True)
        report = _sweep(repo, tmp_path, remote=False)
        assert report.deleted == ("feat",)
        assert report.deleted_remote == ()
        assert "feat" in _remote_branches(bare)

    def test_a_merged_remote_branch_is_deleted_with_its_local_copy(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _pushed(repo, "feat", merge=True)
        report = _sweep(repo, tmp_path)
        assert report.deleted == ("feat",)
        assert report.deleted_remote == ("origin/feat",)
        assert "feat" not in _remote_branches(bare)

    def test_a_patch_equivalent_remote_branch_is_deleted_behind_a_bundle(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        # Plan 00594 Task 3.1: the sweep no longer keeps a cherry-picked remote branch.
        _git(repo, "checkout", "-q", "-b", "picked")
        _commit(repo, "picked")
        _git(repo, "push", "--quiet", "origin", "picked")
        _git(repo, "checkout", "-q", "main")
        _commit(repo, "unrelated")
        _git(repo, "cherry-pick", "main..picked")
        _git(repo, "push", "--quiet", "origin", "main")
        report = _sweep(repo, tmp_path)
        assert report.deleted_remote == ("origin/picked",)
        assert report.bundle is not None
        assert "picked" not in _remote_branches(bare)

    def test_a_remote_only_merged_branch_is_deleted(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _pushed(repo, "gone-local", merge=True, keep_local=False)
        report = _sweep(repo, tmp_path)
        assert report.deleted_remote == ("origin/gone-local",)
        assert "gone-local" not in _remote_branches(bare)

    def test_an_unmerged_remote_branch_is_kept(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _pushed(repo, "novel", merge=False)
        report = _sweep(repo, tmp_path)
        assert report.deleted_remote == ()
        assert "novel" in _remote_branches(bare)

    def test_a_remote_tip_moved_since_the_fetch_is_kept(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _pushed(repo, "feat", merge=True, keep_local=False)
        other = tmp_path / "other"
        _git(tmp_path, "clone", "--quiet", str(bare), str(other))
        _git(other, "checkout", "-q", "feat")
        _commit(other, "late")
        _git(other, "push", "--quiet", "origin", "feat")
        report = _sweep(repo, tmp_path)
        assert report.deleted_remote == ()
        assert "feat" in _remote_branches(bare)
        assert any("could not be confirmed" in line for line in report.skipped)

    def test_an_exempt_remote_branch_is_never_a_candidate(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _pushed(repo, "users/joe", merge=True, keep_local=False)
        report = _sweep(repo, tmp_path)
        assert report.deleted_remote == ()
        assert "users/joe" in _remote_branches(bare)

    def test_dry_run_deletes_nothing_and_names_the_remote_branch(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _pushed(repo, "feat", merge=True, keep_local=False)
        report = _sweep(repo, tmp_path, dry_run=True)
        (line,) = [c for c in report.commands if c.startswith("would delete remote origin/feat")]
        assert "proven merged into main" in line
        assert "feat" in _remote_branches(bare)
        assert report.bundle is None


class TestRemoteRecovery:
    def test_the_remote_tip_is_in_the_bundle_and_restorable(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        tip = _pushed(repo, "gone-local", merge=True, keep_local=False)
        report = _sweep(repo, tmp_path)
        assert report.bundle is not None
        heads = _git(repo, "bundle", "list-heads", str(report.bundle))
        assert f"{tip} refs/remotes/origin/gone-local" in heads
        restore = next(c for c in report.commands if "refs/remotes/origin/gone-local" in c)
        for step in restore.split(" && "):
            _git(repo, *step.split()[1:])
        assert _git(bare, "rev-parse", "refs/heads/gone-local").strip() == tip

    def test_local_and_remote_share_one_bundle(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _pushed(repo, "feat", merge=True)
        report = _sweep(repo, tmp_path)
        assert report.bundle is not None
        heads = _git(repo, "bundle", "list-heads", str(report.bundle))
        assert "refs/heads/feat" in heads
        assert "refs/remotes/origin/feat" in heads

    def test_render_names_the_deleted_remote_branches(self) -> None:
        text = "\n".join(render(CleanupReport(deleted_remote=("origin/a",))))
        assert re.search(r"Deleted remote branch\(es\): origin/a", text)
