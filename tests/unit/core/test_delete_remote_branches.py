"""`delete_remote_branches`: the leased agent route for a remote branch the proof accepts.

It is built on `prove_remote_merged` (so the surviving-content tier applies) and
`_push_deletes` (so the delete holds a lease on the proven tip). A branch the proof
does not accept is refused and nothing is pushed.
"""

import subprocess
from collections.abc import Collection
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup
from claude_code_hooks_daemon.core.branch_cleanup import delete_remote_branches
from claude_code_hooks_daemon.core.remote_branch_proof import RemoteProof
from tests.support.git_fixtures import git_setup_timeout, run_git


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """`dup` and `novel` are unmerged; main holds dup's file but not novel's."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    run_git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    run_git(tmp_path, "init", "--initial-branch=main", str(work))
    run_git(work, "config", "user.email", "t@example.invalid")
    run_git(work, "config", "user.name", "Tester")
    run_git(work, "config", "commit.gpgsign", "false")
    run_git(work, "remote", "add", "origin", str(origin))
    run_git(work, "commit", "--allow-empty", "-m", "base")
    run_git(work, "push", "-u", "origin", "main")
    run_git(work, "remote", "set-head", "origin", "main")
    for name in ("dup", "novel"):
        run_git(work, "checkout", "-q", "-b", name, "main")
        (work / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
        run_git(work, "add", f"{name}.txt")
        run_git(work, "commit", "-m", name)
        run_git(work, "push", "-u", "origin", name)
        run_git(work, "checkout", "-q", "main")
    (work / "dup.txt").write_text("dup\n", encoding="utf-8")
    run_git(work, "add", "dup.txt")
    run_git(work, "commit", "-m", "same file, independent commit")
    run_git(work, "push", "origin", "main")
    run_git(work, "fetch", "origin")
    return work


def _out(work: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(work), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout


def _remote_heads(work: Path) -> str:
    return _out(work, "ls-remote", "--heads", "origin")


def test_a_proven_branch_is_deleted_with_a_restore_line_at_its_tip(clone: Path) -> None:
    tip = _out(clone, "rev-parse", "origin/dup").strip()
    report = delete_remote_branches(clone, BranchesConfig(), "main", ["dup"])
    assert report.deleted_remote == ("origin/dup",)
    assert report.commands == (f"git push origin {tip}:refs/heads/dup",)
    assert "refs/heads/dup" not in _remote_heads(clone)


def test_a_branch_the_proof_refuses_is_not_deleted(clone: Path) -> None:
    report = delete_remote_branches(clone, BranchesConfig(), "main", ["novel"])
    assert report.deleted_remote == ()
    assert report.commands == ()
    assert any("novel" in line and "novel.txt" in line for line in report.skipped)
    assert "refs/heads/novel" in _remote_heads(clone)


def test_one_refused_name_does_not_stop_a_proven_one(clone: Path) -> None:
    report = delete_remote_branches(clone, BranchesConfig(), "main", ["novel", "dup"])
    assert report.deleted_remote == ("origin/dup",)
    heads = _remote_heads(clone)
    assert "refs/heads/novel" in heads
    assert "refs/heads/dup" not in heads


def test_the_default_branch_is_refused_before_any_git_runs(clone: Path) -> None:
    report = delete_remote_branches(clone, BranchesConfig(), "main", ["main"])
    assert report.deleted_remote == ()
    assert any("default branch" in line for line in report.skipped)
    assert "refs/heads/main" in _remote_heads(clone)


def test_a_moved_remote_tip_is_refused_by_the_lease(
    clone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit pushed to the branch between the proof and the push is never lost."""
    real = branch_cleanup.prove_remote_merged

    def prove_then_move(
        directory: Path,
        remote: str,
        names: list[str],
        default: str,
        branches: BranchesConfig,
        also_deleting: Collection[str] = (),
    ) -> RemoteProof:
        proof = real(directory, remote, names, default, branches, also_deleting)
        run_git(clone, "checkout", "-q", "dup")
        (clone / "late.txt").write_text("late\n", encoding="utf-8")
        run_git(clone, "add", "late.txt")
        run_git(clone, "commit", "-m", "late")
        run_git(clone, "push", "origin", "dup")
        run_git(clone, "checkout", "-q", "main")
        return proof

    monkeypatch.setattr(branch_cleanup, "prove_remote_merged", prove_then_move)
    report = delete_remote_branches(clone, BranchesConfig(), "main", ["dup"])
    assert report.deleted_remote == ()
    assert report.skipped
    assert "refs/heads/dup" in _remote_heads(clone)
