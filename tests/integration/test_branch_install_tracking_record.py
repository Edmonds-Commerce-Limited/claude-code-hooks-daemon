"""Plan 00594 Task 5.1 -- Layer 2 records what a branch install tracks.

Drives the real ``record_install_tracking`` function of
``scripts/install/branch_install.sh`` against a real git checkout and the real
``record-venv-tracking`` command: a branch install writes the exact ref, the
full sha and the release installed before it; a release install clears them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.metadata import (
    DaemonVenvMetadata,
    read_daemon_metadata,
    write_daemon_metadata,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_LIB = REPO_ROOT / "scripts" / "install" / "output.sh"
BRANCH_INSTALL_LIB = REPO_ROOT / "scripts" / "install" / "branch_install.sh"
GIT = shutil.which("git") or "/usr/bin/git"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 60

REF_VAR = "HOOKS_DAEMON_UNSAFE_TRACK_REF"
REASON_VAR = "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE"


def _metadata(version: str = "v1.0.0") -> DaemonVenvMetadata:
    return DaemonVenvMetadata(
        python_path="/usr/bin/python3.11",
        fingerprint="fp",
        lock_hash="sha256:" + "a" * 64,
        daemon_version=version,
        written_at="2026-04-24T10:00:00Z",
    )


@pytest.fixture
def daemon_dir(tmp_path: Path) -> Path:
    """A git checkout with one commit."""
    repo = tmp_path / "daemon"
    repo.mkdir()
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "T"],
        ["commit", "-q", "--allow-empty", "-m", "c"],
    ):
        subprocess.run([GIT, *args], cwd=repo, check=True, capture_output=True)
    return repo


def _head(repo: Path) -> str:
    return subprocess.run(
        [GIT, "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _record(
    venv: Path,
    daemon_dir: Path,
    *,
    ref: str | None,
    previous_release: str = "",
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["NO_COLOR"] = "1"
    if ref is not None:
        env[REF_VAR] = ref
        env[REASON_VAR] = "test"
    script = (
        f'source "{OUTPUT_LIB}"; source "{BRANCH_INSTALL_LIB}"; '
        f'record_install_tracking "{sys.executable}" "{venv}" "{daemon_dir}" "{previous_release}"'
    )
    return subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _previous_release(venv: Path, installed_version: str) -> str:
    script = (
        f'source "{OUTPUT_LIB}"; source "{BRANCH_INSTALL_LIB}"; '
        f'read_previous_release_tag "{venv}" "{installed_version}"'
    )
    result = subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


class TestReadPreviousReleaseTag:
    def test_a_release_stamp_is_the_previous_release(self, tmp_path: Path) -> None:
        assert _previous_release(tmp_path, "1.0.0") == "v1.0.0"
        assert _previous_release(tmp_path, "v1.0.0") == "v1.0.0"

    def test_a_branch_stamp_without_a_record_gives_nothing(self, tmp_path: Path) -> None:
        assert _previous_release(tmp_path, "1.1.0+rc-1.1.0.abcdef0") == ""
        assert _previous_release(tmp_path, "") == ""


class TestBranchInstallRecordsTracking:
    def test_records_exact_ref_full_sha_and_previous_release(
        self, tmp_path: Path, daemon_dir: Path
    ) -> None:
        venv = tmp_path / "venv-a"
        venv.mkdir()
        write_daemon_metadata(venv, _metadata("v1.1.0+rc-1.1.0.abcdef0"))

        result = _record(venv, daemon_dir, ref="rc/1.1.0", previous_release="v1.0.0")

        assert result.returncode == 0, result.stdout + result.stderr
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert meta.tracked_ref == "rc/1.1.0"
        assert meta.tracked_sha == _head(daemon_dir)
        assert len(meta.tracked_sha) == 40
        assert meta.last_release_tag == "v1.0.0"

    @pytest.mark.parametrize("lock_changes", [False, True], ids=["same-lock", "lock-changed"])
    def test_rc_to_rc_keeps_the_release_when_the_same_venv_folder_is_rebuilt(
        self, tmp_path: Path, daemon_dir: Path, lock_changes: bool
    ) -> None:
        """The venv folder name does not change with the version, so a rebuild wipes it."""
        venv = tmp_path / "venv-py313-project"
        venv.mkdir()
        write_daemon_metadata(
            venv,
            _metadata("v1.1.0+rc-1.1.0.abcdef0").model_copy(
                update={
                    "tracked_ref": "rc/1.1.0",
                    "tracked_sha": "c" * 40,
                    "last_release_tag": "v1.0.0",
                }
            ),
        )
        # What the install reads BEFORE ensure_venv touches the folder.
        previous = _previous_release(venv, "1.1.0+rc-1.1.0.abcdef0")

        shutil.rmtree(venv)  # ensure_venv rebuilds the folder and its record
        venv.mkdir()
        rebuilt = _metadata("v1.1.0+rc-1.1.0.abcdef1")
        if lock_changes:
            rebuilt = rebuilt.model_copy(update={"lock_hash": "sha256:" + "b" * 64})
        write_daemon_metadata(venv, rebuilt)

        result = _record(venv, daemon_dir, ref="rc/1.1.0", previous_release=previous)

        assert result.returncode == 0, result.stdout + result.stderr
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert meta.last_release_tag == "v1.0.0"
        assert meta.tracked_sha == _head(daemon_dir)

    def test_a_full_sha_pin_records_the_sha_as_the_ref(
        self, tmp_path: Path, daemon_dir: Path
    ) -> None:
        venv = tmp_path / "venv-a"
        venv.mkdir()
        write_daemon_metadata(venv, _metadata("v1.1.0+x.abcdef0"))
        sha = _head(daemon_dir)

        result = _record(venv, daemon_dir, ref=sha)

        assert result.returncode == 0, result.stdout + result.stderr
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert meta.tracked_ref == sha
        assert meta.tracked_sha == sha


class TestReleaseInstallClearsTracking:
    def test_a_release_install_clears_the_three_fields(
        self, tmp_path: Path, daemon_dir: Path
    ) -> None:
        venv = tmp_path / "venv-a"
        venv.mkdir()
        write_daemon_metadata(
            venv,
            _metadata().model_copy(
                update={
                    "tracked_ref": "rc/1.1.0",
                    "tracked_sha": "c" * 40,
                    "last_release_tag": "v1.0.0",
                }
            ),
        )

        result = _record(venv, daemon_dir, ref=None)

        assert result.returncode == 0, result.stdout + result.stderr
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert (meta.tracked_ref, meta.tracked_sha, meta.last_release_tag) == (None, None, None)

    def test_a_failed_record_warns_and_does_not_fail_the_install(
        self, tmp_path: Path, daemon_dir: Path
    ) -> None:
        venv = tmp_path / "venv-without-metadata"
        venv.mkdir()

        result = _record(venv, daemon_dir, ref="rc/1.1.0")

        assert result.returncode == 0
        assert "tracking" in (result.stdout + result.stderr).lower()
