"""``scripts/lib/release_tag_verify.sh``: a release tag is trusted only when signed (Plan 00625).

The relayed ruling (DESIGN 11a items 2, 3 and review M1): an unattended
upgrade installs a tag only when it exists on origin, is an annotated tag
whose own header names it, carries an SSH signature, and that signature
verifies against a key in the project's allowed-signers file, which must not
live inside the daemon clone the tag came from. Every key here is a
throwaway generated in the test; nothing is fetched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_LIB: Final[Path] = _REPO_ROOT / "scripts" / "lib" / "release_tag_verify.sh"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_ENV: Final[dict[str, str]] = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}

pytestmark = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs ssh-keygen")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@x.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=_ENV,
    )
    return result.stdout.strip()


def _keygen(path: Path) -> Path:
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def _signed_tag(cwd: Path, key: Path, name: str) -> None:
    _git(cwd, "-c", "gpg.format=ssh", "-c", f"user.signingkey={key}", "tag", "-s", "-m", "m", name)


@dataclass
class Fixture:
    daemon: Path
    signers: Path
    origin: Path
    origin_work: Path

    def verify(
        self, tag: str, signers: Path | None = None, path: str | None = None
    ) -> tuple[int, str, str]:
        script = (
            'source "$1"; rc=0; release_tag_verify "$2" "$3" "$4" || rc=$?; '
            'printf "%s\\n%s\\n%s\\n" "$rc" "$RELEASE_TAG_VERIFY_SHA" "$RELEASE_TAG_VERIFY_REASON"'
        )
        env = dict(_ENV)
        if path is not None:
            env["PATH"] = path
        result = subprocess.run(
            [_BASH, "-c", script, "verify", str(_LIB), str(self.daemon), tag, str(signers or self.signers)],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        rc, sha, reason = result.stdout.split("\n")[:3]
        return int(rc), sha, reason

    def origin_tag_sha(self, tag: str) -> str:
        return _git(self.origin, "rev-parse", f"refs/tags/{tag}")


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    good = _keygen(tmp_path / "good")
    bad = _keygen(tmp_path / "bad")
    work = tmp_path / "origin-work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "commit", "-q", "--allow-empty", "-m", "one")
    _signed_tag(work, good, "v1.1.0")
    _git(work, "tag", "v1.2.0")  # lightweight
    _git(work, "tag", "-a", "-m", "unsigned", "v1.3.0")
    _signed_tag(work, bad, "v1.4.0")
    _git(work, "tag", "-a", "-m", "m\n-----BEGIN PGP SIGNATURE-----\nx\n-----END PGP SIGNATURE-----", "v1.6.0")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(origin))
    # Replay: the signed v1.1.0 tag object published under another name.
    _git(origin, "update-ref", "refs/tags/v1.5.0", _git(origin, "rev-parse", "refs/tags/v1.1.0"))
    project = tmp_path / "project"
    daemon = project / ".claude" / "hooks-daemon"
    daemon.parent.mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--no-tags", str(origin), str(daemon))
    signers = project / ".claude" / "hooks-daemon-release-signers"
    signers.write_text(
        f"# release signers\nrelease {(tmp_path / 'good.pub').read_text().strip()}\n",
        encoding="utf-8",
    )
    return Fixture(daemon=daemon, signers=signers, origin=origin, origin_work=work)


def test_a_signed_release_tag_on_origin_verifies(fixture: Fixture) -> None:
    rc, sha, reason = fixture.verify("v1.1.0")
    assert (rc, reason) == (0, "")
    assert sha == fixture.origin_tag_sha("v1.1.0")


@pytest.mark.parametrize("tag", ["v1.1", "main", "v1.1.0-rc1", "1.1.0", "v1.1.0\nv1.2.0"])
def test_a_name_that_is_not_a_plain_release_tag_is_refused(fixture: Fixture, tag: str) -> None:
    rc, sha, reason = fixture.verify(tag)
    assert rc == 1 and sha == ""
    assert "not a release tag" in reason


def test_an_absent_signers_file_is_refused(fixture: Fixture, tmp_path: Path) -> None:
    rc, _, reason = fixture.verify("v1.1.0", signers=tmp_path / "absent")
    assert rc == 1
    assert "no trusted release-signing key" in reason


def test_a_comment_only_signers_file_is_refused(fixture: Fixture) -> None:
    fixture.signers.write_text("# nothing yet\n\n", encoding="utf-8")
    rc, _, reason = fixture.verify("v1.1.0")
    assert rc == 1
    assert "no trusted release-signing key" in reason


def test_a_signers_file_inside_the_clone_is_refused(fixture: Fixture) -> None:
    inside = fixture.daemon / "signers"
    inside.write_text(fixture.signers.read_text(encoding="utf-8"), encoding="utf-8")
    rc, _, reason = fixture.verify("v1.1.0", signers=inside)
    assert rc == 1
    assert "inside the daemon clone" in reason


def test_a_symlink_into_the_clone_is_refused(fixture: Fixture, tmp_path: Path) -> None:
    inside = fixture.daemon / "signers"
    inside.write_text(fixture.signers.read_text(encoding="utf-8"), encoding="utf-8")
    link = tmp_path / "link-signers"
    link.symlink_to(inside)
    rc, _, reason = fixture.verify("v1.1.0", signers=link)
    assert rc == 1
    assert "inside the daemon clone" in reason


def test_no_ssh_keygen_is_refused(fixture: Fixture, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin-without-ssh-keygen"
    bin_dir.mkdir()
    for tool in ("git", "cat", "grep", "readlink", "dirname", "basename", "realpath"):
        found = shutil.which(tool)
        if found is not None:
            (bin_dir / tool).symlink_to(found)
    rc, _, reason = fixture.verify("v1.1.0", path=str(bin_dir))
    assert rc == 1
    assert "ssh-keygen" in reason


def test_a_tag_that_is_not_on_origin_is_refused(fixture: Fixture) -> None:
    """Review M1: a tag that exists only in the local clone is never installed."""
    _git(fixture.daemon, "tag", "v9.0.0")
    rc, _, reason = fixture.verify("v9.0.0")
    assert rc == 1
    assert "not on origin" in reason


def test_a_lightweight_tag_is_refused(fixture: Fixture) -> None:
    rc, _, reason = fixture.verify("v1.2.0")
    assert rc == 1
    assert "not an annotated tag" in reason


def test_an_unsigned_annotated_tag_is_refused(fixture: Fixture) -> None:
    rc, _, reason = fixture.verify("v1.3.0")
    assert rc == 1
    assert "no SSH signature" in reason


def test_a_non_ssh_signature_is_refused(fixture: Fixture) -> None:
    rc, _, reason = fixture.verify("v1.6.0")
    assert rc == 1
    assert "no SSH signature" in reason


def test_a_tag_signed_by_an_unlisted_key_is_refused(fixture: Fixture) -> None:
    rc, _, reason = fixture.verify("v1.4.0")
    assert rc == 1
    assert "does not verify" in reason


def test_a_signed_tag_replayed_under_another_name_is_refused(fixture: Fixture) -> None:
    rc, _, reason = fixture.verify("v1.5.0")
    assert rc == 1
    assert "names v1.1.0" in reason


def test_a_git_config_override_in_the_environment_cannot_steer_it(fixture: Fixture) -> None:
    """A gpg.ssh.program that always succeeds, passed through GIT_CONFIG_*, is ignored."""
    script = (
        'source "$1"; export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=gpg.ssh.program '
        "GIT_CONFIG_VALUE_0=true; rc=0; "
        'release_tag_verify "$2" v1.4.0 "$3" || rc=$?; echo "$rc"'
    )
    result = subprocess.run(
        [_BASH, "-c", script, "verify", str(_LIB), str(fixture.daemon), str(fixture.signers)],
        capture_output=True,
        text=True,
        check=True,
        env=_ENV,
    )
    assert result.stdout.strip() == "1"
