"""``branch-sweep --clean`` honours keeps and bot-owned names (Plan 00571 Phase 3 slice d).

A merged branch kept inside its age is skipped (locally and on the remote) and the
skip is reported; a lapsed keep is an unkept merged branch and is cleaned. With
``--remote`` the keep notes are fetched BEFORE the inventory, so a keep written in
another clone protects the branch here; a failed fetch refuses the remote half.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_cleanup import CleanupReport, clean_sweep
from claude_code_hooks_daemon.core.branch_keep import keep_branch
from tests.support.git_fixtures import git_setup_timeout

_DAY = 86_400
_CONFIG = BranchesConfig(default="main", merged={"max_age_days": 7})


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


def _identify(repo: Path) -> None:
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Tess")


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    path = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(path))
    return path


@pytest.fixture
def repo(tmp_path: Path, bare: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _identify(root)
    (root / ".gitignore").write_text("untracked/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "root")
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "push", "-q", "origin", "main")
    return root


def _merged(repo: Path, name: str, *, push: bool = False) -> str:
    _git(repo, "checkout", "-q", "-b", name)
    filename = f"{name.replace('/', '-')}.txt"
    (repo / filename).write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", f"Add {filename}")
    if push:
        _git(repo, "push", "-q", "origin", name)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
    if push:
        _git(repo, "push", "-q", "origin", "main")
    return _git(repo, "rev-parse", f"refs/heads/{name}")


def _keep(repo: Path, tip: str, *, age_days: int = 0) -> None:
    keep_branch(
        repo,
        [tip],
        reason="needed for the audit",
        remote="origin",
        user="Tess",
        now=time.time() - age_days * _DAY,
    )


def _sweep(repo: Path, tmp_path: Path, *, remote: bool) -> CleanupReport:
    return clean_sweep(repo, _CONFIG, dry_run=False, bundle_dir=tmp_path / "b", remote=remote)


def _remote_heads(bare: Path) -> set[str]:
    out = _git(bare, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return set(out.splitlines())


class TestLocalKeeps:
    def test_a_kept_branch_is_skipped_and_reported(self, repo: Path, tmp_path: Path) -> None:
        _keep(repo, _merged(repo, "kept"))
        report = _sweep(repo, tmp_path, remote=False)
        assert report.deleted == ()
        assert "kept: kept: needed for the audit" in report.skipped
        assert _git(repo, "branch", "--list", "kept")

    def test_a_lapsed_keep_is_cleaned(self, repo: Path, tmp_path: Path) -> None:
        _keep(repo, _merged(repo, "lapsed"), age_days=30)
        report = _sweep(repo, tmp_path, remote=False)
        assert report.deleted == ("lapsed",)

    def test_an_unkept_merged_branch_is_still_cleaned(self, repo: Path, tmp_path: Path) -> None:
        _merged(repo, "plain")
        assert _sweep(repo, tmp_path, remote=False).deleted == ("plain",)

    def test_a_bot_owned_branch_is_never_cleaned(self, repo: Path, tmp_path: Path) -> None:
        _merged(repo, "dependabot/pip/requests")
        report = _sweep(repo, tmp_path, remote=False)
        assert report.deleted == ()
        assert _git(repo, "branch", "--list", "dependabot/pip/requests")


class TestRemoteKeeps:
    def test_a_kept_remote_branch_is_skipped(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _keep(repo, _merged(repo, "kept", push=True))
        report = _sweep(repo, tmp_path, remote=True)
        assert report.deleted_remote == ()
        assert "kept" in _remote_heads(bare)
        assert "origin/kept: kept: needed for the audit" in report.skipped

    def test_a_keep_from_another_clone_is_fetched_first(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        tip = _merged(repo, "theirs", push=True)
        _git(repo, "branch", "-q", "-D", "theirs")
        other = tmp_path / "other"
        _git(tmp_path, "clone", "-q", str(bare), str(other))
        _identify(other)
        _keep(other, tip)
        report = _sweep(repo, tmp_path, remote=True)
        assert report.deleted_remote == ()
        assert "theirs" in _remote_heads(bare)

    def test_a_failed_keep_fetch_refuses_the_remote_half(
        self, repo: Path, bare: Path, tmp_path: Path
    ) -> None:
        _merged(repo, "feat", push=True)
        _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
        report = _sweep(repo, tmp_path, remote=True)
        assert report.deleted == ("feat",)
        assert report.deleted_remote == ()
        assert "feat" in _remote_heads(bare)
        assert any(
            line.startswith("origin: keep notes could not be fetched (")
            and line.endswith("), so the remote half was refused")
            for line in report.skipped
        )
