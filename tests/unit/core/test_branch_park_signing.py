"""Park commits honour ``commit.gpgsign`` (Plan 00594 Task 4.9).

``git commit-tree`` does not read ``commit.gpgsign`` on its own, so the park
commit must ask for ``-S`` itself when the repository requires signing.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.branch_park import BranchParkError, park_branch
from tests.support.git_fixtures import git_setup_timeout

_SIGNATURE_HEADER = "gpgsig "
_SIGNING_KEY = "TESTKEY"
_FAKE_GPG_OK = """#!/bin/sh
echo "$@" >> "$0.args"
cat > /dev/null
printf -- '-----BEGIN PGP SIGNATURE-----\\n\\nZmFrZQ==\\n-----END PGP SIGNATURE-----\\n'
echo '[GNUPG:] SIG_CREATED D 1 8 00 0 FAKE' >&2
"""
_FAKE_GPG_FAIL = """#!/bin/sh
echo "gpg: no secret key for signing" >&2
exit 1
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=git_setup_timeout(),
    ).stdout.strip()


def _fake_gpg(directory: Path, body: str) -> Path:
    program = directory / "fake-gpg"
    program.write_text(body)
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    return program


def _require_signing(repo: Path, program: Path) -> None:
    _git(repo, "config", "commit.gpgsign", "true")
    _git(repo, "config", "user.signingkey", _SIGNING_KEY)
    _git(repo, "config", "gpg.program", str(program))


def _commit_object(repo: Path, rev: str) -> str:
    return _git(repo, "cat-file", "commit", rev)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(bare)],
        check=True,
        timeout=git_setup_timeout(),
    )
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Tess")
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


class TestSignedPark:
    def test_unsigned_when_signing_not_configured(self, repo: Path) -> None:
        result = park_branch(repo, "work", reason="waiting", remote="origin")
        assert _SIGNATURE_HEADER not in _commit_object(repo, result.sha)

    def test_park_is_signed_when_gpgsign_true(self, repo: Path, tmp_path: Path) -> None:
        program = _fake_gpg(tmp_path, _FAKE_GPG_OK)
        _require_signing(repo, program)
        result = park_branch(repo, "work", reason="waiting", remote="origin")
        assert _SIGNATURE_HEADER in _commit_object(repo, result.sha)
        assert _SIGNING_KEY in Path(f"{program}.args").read_text()
        assert result.pushed is True

    def test_clear_is_signed_when_gpgsign_true(self, repo: Path, tmp_path: Path) -> None:
        park_branch(repo, "work", reason="waiting", remote="origin")
        _require_signing(repo, _fake_gpg(tmp_path, _FAKE_GPG_OK))
        result = park_branch(repo, "work", reason=None, remote="origin", clear=True)
        assert _SIGNATURE_HEADER in _commit_object(repo, result.sha)

    def test_remote_only_park_is_signed(self, repo: Path, tmp_path: Path) -> None:
        _git(repo, "branch", "-D", "work")
        _require_signing(repo, _fake_gpg(tmp_path, _FAKE_GPG_OK))
        result = park_branch(repo, "work", reason="waiting", remote="origin")
        assert _SIGNATURE_HEADER in _commit_object(repo, result.sha)

    def test_gpgsign_false_stays_unsigned(self, repo: Path, tmp_path: Path) -> None:
        _require_signing(repo, _fake_gpg(tmp_path, _FAKE_GPG_OK))
        _git(repo, "config", "commit.gpgsign", "false")
        result = park_branch(repo, "work", reason="waiting", remote="origin")
        assert _SIGNATURE_HEADER not in _commit_object(repo, result.sha)


class TestSigningFailure:
    def test_park_fails_clearly_and_leaves_branch(self, repo: Path, tmp_path: Path) -> None:
        _require_signing(repo, _fake_gpg(tmp_path, _FAKE_GPG_FAIL))
        before = _git(repo, "rev-parse", "work")
        with pytest.raises(BranchParkError) as raised:
            park_branch(repo, "work", reason="waiting", remote="origin")
        message = str(raised.value)
        assert "no secret key for signing" in message
        assert "commit.gpgsign" in message
        assert _git(repo, "rev-parse", "work") == before
        assert _git(repo, "rev-parse", "origin/work") == before

    def test_clear_fails_clearly_and_leaves_branch(self, repo: Path, tmp_path: Path) -> None:
        park_branch(repo, "work", reason="waiting", remote="origin")
        before = _git(repo, "rev-parse", "work")
        _require_signing(repo, _fake_gpg(tmp_path, _FAKE_GPG_FAIL))
        with pytest.raises(BranchParkError, match="commit.gpgsign"):
            park_branch(repo, "work", reason=None, remote="origin", clear=True)
        assert _git(repo, "rev-parse", "work") == before

    def test_remote_only_park_fails_and_pushes_nothing(self, repo: Path, tmp_path: Path) -> None:
        _git(repo, "branch", "-D", "work")
        before = _git(repo, "rev-parse", "origin/work")
        _require_signing(repo, _fake_gpg(tmp_path, _FAKE_GPG_FAIL))
        with pytest.raises(BranchParkError, match="commit.gpgsign"):
            park_branch(repo, "work", reason="waiting", remote="origin")
        assert _git(repo, "rev-parse", "origin/work") == before
