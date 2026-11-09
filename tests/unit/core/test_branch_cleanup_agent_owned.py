"""``branch-sweep --clean`` leaves a live agent's worktree and branch alone.

A freshly spawned isolation worktree sits at the default branch's tip, so
containment calls its branch merged and the clean worktree has nothing to lose.
Three signals say it is not ours to remove: a ``running`` work-queue record, the
Claude Code harness's ``.claude/worktrees/`` directory, and a git ``locked``
marker. Real repositories throughout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_cleanup import clean_sweep
from claude_code_hooks_daemon.utils.work_queue import WORK_QUEUE_FILENAME, add_record

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "PATH": "/usr/bin:/bin",
}
_CONFIG = BranchesConfig(default="main")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**_ENV, "HOME": str(repo)},
    )
    return result.stdout


def _branches(repo: Path) -> set[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return set(out.split())


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / ".gitignore").write_text("untracked/\n.claude/worktrees/\n", encoding="utf-8")
    _git(path, "add", ".gitignore")
    _git(path, "commit", "-m", "Initial commit")
    return path


def _fresh_worktree(repo: Path, name: str, *, under: str) -> Path:
    """A worktree whose branch sits at main's tip, as an agent's does at spawn."""
    path = repo / under / name
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-b", name, str(path), "main")
    return path


def _queue(untracked: Path, *, branch: str, worktree: str) -> None:
    untracked.mkdir(parents=True, exist_ok=True)
    add_record(
        untracked / WORK_QUEUE_FILENAME,
        "agent-1",
        worktree=worktree,
        branch=branch,
        brief="work",
        brief_file=None,
        last_sha="abc",
        now=1.0,
    )


def _sweep(repo: Path, tmp_path: Path, *, dry_run: bool = False) -> branch_cleanup.CleanupReport:
    return clean_sweep(
        repo,
        _CONFIG,
        dry_run=dry_run,
        bundle_dir=tmp_path / "bundles",
        untracked=tmp_path / "untracked",
    )


class TestRunningAgentsAreLeftAlone:
    def test_harness_directory_worktree_is_skipped(self, repo: Path, tmp_path: Path) -> None:
        path = _fresh_worktree(repo, "agent-a1", under=".claude/worktrees")
        report = _sweep(repo, tmp_path)
        assert path.is_dir()
        assert "agent-a1" in _branches(repo)
        assert report.deleted == ()
        assert report.removed_worktrees == ()
        assert any(
            line.startswith("agent-a1:") and ".claude/worktrees" in line for line in report.skipped
        )

    def test_dry_run_does_not_offer_the_harness_worktree(self, repo: Path, tmp_path: Path) -> None:
        _fresh_worktree(repo, "agent-a1", under=".claude/worktrees")
        report = _sweep(repo, tmp_path, dry_run=True)
        assert not any("agent-a1" in line for line in report.commands)

    def test_running_queue_record_by_branch_is_skipped(self, repo: Path, tmp_path: Path) -> None:
        path = _fresh_worktree(repo, "feat", under="elsewhere")
        _queue(tmp_path / "untracked", branch="feat", worktree="unrelated")
        report = _sweep(repo, tmp_path)
        assert path.is_dir()
        assert "feat" in _branches(repo)
        assert any(line.startswith("feat:") and "running" in line for line in report.skipped)

    def test_running_queue_record_by_worktree_is_skipped(self, repo: Path, tmp_path: Path) -> None:
        path = _fresh_worktree(repo, "feat", under="elsewhere")
        _queue(tmp_path / "untracked", branch="other", worktree=str(path))
        report = _sweep(repo, tmp_path)
        assert path.is_dir()
        assert "feat" in _branches(repo)
        assert any(line.startswith("feat:") and "running" in line for line in report.skipped)

    def test_running_queue_branch_without_worktree_is_kept(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "branch", "queued")
        _queue(tmp_path / "untracked", branch="queued", worktree="gone")
        report = _sweep(repo, tmp_path)
        assert "queued" in _branches(repo)
        assert any(line.startswith("queued:") for line in report.skipped)

    def test_locked_worktree_is_skipped(self, repo: Path, tmp_path: Path) -> None:
        path = _fresh_worktree(repo, "feat", under="elsewhere")
        _git(repo, "worktree", "lock", str(path))
        report = _sweep(repo, tmp_path)
        assert path.is_dir()
        assert "feat" in _branches(repo)
        assert any(line.startswith("feat:") and "locked" in line for line in report.skipped)

    def test_remote_delete_spares_a_skipped_branch(self, repo: Path, tmp_path: Path) -> None:
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True)
        _git(repo, "remote", "add", "origin", str(origin))
        _git(repo, "push", "origin", "main")
        _fresh_worktree(repo, "agent-a1", under=".claude/worktrees")
        _git(repo, "push", "origin", "agent-a1")
        _git(repo, "fetch", "origin")
        report = clean_sweep(
            repo,
            _CONFIG,
            dry_run=False,
            bundle_dir=tmp_path / "bundles",
            remote=True,
            untracked=tmp_path / "untracked",
        )
        assert report.deleted_remote == ()
        assert "agent-a1" in _git(origin, "for-each-ref", "--format=%(refname:short)")

    def test_an_ordinary_merged_worktree_is_still_removed(self, repo: Path, tmp_path: Path) -> None:
        path = _fresh_worktree(repo, "feat", under="elsewhere")
        report = _sweep(repo, tmp_path)
        assert report.removed_worktrees == (path,)
        assert report.deleted == ("feat",)

    def test_an_unreadable_queue_does_not_block_the_sweep(self, repo: Path, tmp_path: Path) -> None:
        _fresh_worktree(repo, "feat", under="elsewhere")
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        (untracked / WORK_QUEUE_FILENAME).write_text("not json", encoding="utf-8")
        report = _sweep(repo, tmp_path)
        assert report.deleted == ("feat",)
