"""End-to-end: branch-park writes SIGNED commits in a real repository.

Plan 00594 Task 4.9 makes ``park_branch`` pass ``-S`` to ``git commit-tree`` when
``commit.gpgsign`` is true. The unit tests only look at flags and a fake gpg
program; this drives a real repository, a bare remote and a throwaway SSH
signing key, then asks git itself to verify every commit the park wrote.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.branch_park import (
    BranchParkError,
    park_branch,
    read_park_record,
)
from tests.support.git_fixtures import git_setup_timeout

_EMAIL = "signer@example.com"
_IN_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    result = _run(["git", "-C", str(repo), *args])
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _ssh_signing_unavailable_reason(tmp_path: Path) -> str | None:
    """Why SSH commit signing cannot run here, or None when it can."""
    if shutil.which("ssh-keygen") is None:
        return "ssh-keygen is not installed"
    probe = _run(["git", "-c", "gpg.format=ssh", "var", "GIT_COMMITTER_IDENT"])
    if probe.returncode != 0:
        return "git cannot run with gpg.format=ssh"
    key = tmp_path / "probe-key"
    made = _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
    if made.returncode != 0:
        return f"ssh-keygen cannot generate a key: {made.stderr.strip()}"
    signed = _run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "git", str(key) + ".pub"])
    if signed.returncode != 0:
        return f"ssh-keygen cannot sign: {signed.stderr.strip()}"
    return None


@pytest.fixture
def signing_repo(tmp_path: Path) -> Path:
    """A repo with a bare origin, a branch ``work`` and SSH signing configured but off."""
    reason = _ssh_signing_unavailable_reason(tmp_path)
    if reason is not None:
        message = f"SSH commit signing is unavailable: {reason}"
        if _IN_CI:
            pytest.fail(message)
        pytest.skip(message)

    keys = tmp_path / "keys"
    keys.mkdir()
    key = keys / "key"
    made = _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
    assert made.returncode == 0, made.stderr
    pub = (keys / "key.pub").read_text().strip()
    signers = keys / "allowed_signers"
    signers.write_text(f"{_EMAIL} {pub}\n")

    bare = tmp_path / "origin.git"
    assert _run(["git", "init", "-q", "--bare", "-b", "main", str(bare)]).returncode == 0
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", _EMAIL)
    _git(root, "config", "user.name", "Signer")
    _git(root, "config", "gpg.format", "ssh")
    _git(root, "config", "user.signingkey", str(keys / "key.pub"))
    _git(root, "config", "gpg.ssh.allowedSignersFile", str(signers))
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "commit", "-q", "--allow-empty", "-m", "root")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "checkout", "-q", "-b", "work")
    (root / "f.txt").write_text("x")
    _git(root, "add", "f.txt")
    _git(root, "commit", "-q", "-m", "work")
    _git(root, "push", "-q", "-u", "origin", "work")
    _git(root, "checkout", "-q", "main")
    return root


def _new_commits(repo: Path, original: str) -> list[str]:
    return _git(repo, "rev-list", f"{original}..work").split()


class TestSignedParkEndToEnd:
    def test_every_park_and_unpark_commit_verifies(self, signing_repo: Path) -> None:
        original = _git(signing_repo, "rev-parse", "work")
        _git(signing_repo, "config", "commit.gpgsign", "true")

        parked = park_branch(signing_repo, "work", reason="waiting", remote="origin")
        cleared = park_branch(signing_repo, "work", reason=None, remote="origin", clear=True)

        written = _new_commits(signing_repo, original)
        assert len(written) == 2
        assert {parked.sha, cleared.sha} == set(written)
        for sha in written:
            verified = _run(["git", "-C", str(signing_repo), "verify-commit", sha])
            assert verified.returncode == 0, verified.stderr
            assert _git(signing_repo, "log", "-1", "--format=%G?", sha) == "G"
        assert _git(signing_repo, "rev-parse", "origin/work") == cleared.sha

    def test_unsigned_when_gpgsign_unset_and_still_succeeds(self, signing_repo: Path) -> None:
        original = _git(signing_repo, "rev-parse", "work")

        result = park_branch(signing_repo, "work", reason="waiting", remote="origin")

        assert result.pushed is True
        assert _new_commits(signing_repo, original) == [result.sha]
        assert _git(signing_repo, "log", "-1", "--format=%G?", result.sha) == "N"

    def test_broken_key_fails_with_hint_and_changes_nothing(self, signing_repo: Path) -> None:
        before = _git(signing_repo, "rev-parse", "work")
        _git(signing_repo, "config", "commit.gpgsign", "true")
        _git(signing_repo, "config", "user.signingkey", str(signing_repo / "missing-key.pub"))

        with pytest.raises(BranchParkError, match="commit.gpgsign"):
            park_branch(signing_repo, "work", reason="waiting", remote="origin")

        assert _git(signing_repo, "rev-parse", "work") == before
        assert _git(signing_repo, "rev-parse", "origin/work") == before
        assert read_park_record(signing_repo, "work") is None

    def test_broken_key_on_unpark_keeps_tip_and_record(self, signing_repo: Path) -> None:
        park_branch(signing_repo, "work", reason="waiting", remote="origin")
        tip = _git(signing_repo, "rev-parse", "work")
        record = read_park_record(signing_repo, "work")
        assert record is not None
        _git(signing_repo, "config", "commit.gpgsign", "true")
        _git(signing_repo, "config", "user.signingkey", str(signing_repo / "missing-key.pub"))

        with pytest.raises(BranchParkError, match="commit.gpgsign"):
            park_branch(signing_repo, "work", reason=None, remote="origin", clear=True)

        assert _git(signing_repo, "rev-parse", "work") == tip
        assert read_park_record(signing_repo, "work") == record
