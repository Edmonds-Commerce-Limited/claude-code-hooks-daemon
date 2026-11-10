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

    @pytest.mark.parametrize("stamp", ["1.1.0rc1", "1.1.0-rc.1", "1.1", "main", "1.1.0.dev3"])
    def test_a_stamp_that_is_not_a_release_shape_gives_nothing(
        self, tmp_path: Path, stamp: str
    ) -> None:
        assert _previous_release(tmp_path, stamp) == ""

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
        assert meta.tracked_sha is not None
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


def _bash(script: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["NO_COLOR"] = "1"
    return subprocess.run(
        [BASH, "-c", f'source "{OUTPUT_LIB}"; source "{BRANCH_INSTALL_LIB}"; {script}'],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


class TestRestoreTrackingAfterRolledBackRebuild:
    """A rebuild blanks the record; a rollback puts the previous one back."""

    def test_reads_the_recorded_fields(self, tmp_path: Path) -> None:
        venv = tmp_path / "venv-a"
        venv.mkdir()
        write_daemon_metadata(
            venv,
            _metadata("v1.1.0+x.abcdef0").model_copy(
                update={
                    "tracked_ref": "rc/1.1.0",
                    "tracked_sha": "c" * 40,
                    "last_release_tag": "v1.0.0",
                }
            ),
        )
        for field, expected in (
            ("tracked_ref", "rc/1.1.0"),
            ("tracked_sha", "c" * 40),
            ("last_release_tag", "v1.0.0"),
        ):
            result = _bash(f'read_recorded_tracking_field "{venv}" {field}')
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stdout.strip() == expected

    def test_restore_writes_the_previous_fields_back_onto_a_blank_record(
        self, tmp_path: Path
    ) -> None:
        venv = tmp_path / "venv-a"
        venv.mkdir()
        write_daemon_metadata(venv, _metadata("v1.1.0+rc-1.1.0.abcdef1"))  # rebuilt: blank

        result = _bash(
            f'restore_install_tracking "{sys.executable}" "{venv}" rc/1.1.0 {"c" * 40} v1.0.0'
        )

        assert result.returncode == 0, result.stdout + result.stderr
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert (meta.tracked_ref, meta.tracked_sha, meta.last_release_tag) == (
            "rc/1.1.0",
            "c" * 40,
            "v1.0.0",
        )

    def test_restore_with_no_previous_ref_leaves_the_record_alone(self, tmp_path: Path) -> None:
        venv = tmp_path / "venv-a"
        venv.mkdir()
        write_daemon_metadata(venv, _metadata())

        result = _bash(f'restore_install_tracking "{sys.executable}" "{venv}" "" "" ""')

        assert result.returncode == 0, result.stdout + result.stderr
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert meta.tracked_ref is None


UPGRADE_SCRIPT = REPO_ROOT / "scripts" / "upgrade_version.sh"


def _code_lines() -> list[tuple[int, str]]:
    """Non-comment lines of the Layer 2 script with their 1-based line numbers."""
    return [
        (number, line.strip())
        for number, line in enumerate(UPGRADE_SCRIPT.read_text().splitlines(), start=1)
        if line.strip() and not line.strip().startswith("#")
    ]


def _numbers(predicate: str) -> list[int]:
    return [number for number, line in _code_lines() if predicate in line]


class TestUpgradeScriptCallOrder:
    """Structural: the order the behavioural fixtures cannot run (Layer 2 is stubbed)."""

    def test_previous_release_is_read_before_every_ensure_venv(self) -> None:
        reads = [number for number, line in _code_lines() if line == "_read_installed_version"]
        builds = _numbers("=$(ensure_venv ")
        assert len(reads) == 1
        assert len(builds) == 2
        assert all(reads[0] < build for build in builds)

    def test_each_tracking_record_follows_the_restart_of_its_own_path(self) -> None:
        builds = _numbers("=$(ensure_venv ")
        restarts = _numbers("if ! restart_daemon_verified")
        records = [number for number, line in _code_lines() if line == "_record_tracking"]
        assert len(records) == 3
        for record in records:
            restart = max(r for r in restarts if r < record)
            assert any(build < restart for build in builds)

    def test_a_failed_step_15_restart_still_records_the_code_that_stays_installed(self) -> None:
        lines = [line for _, line in _code_lines()]
        start = next(
            i for i, line in enumerate(lines) if "Daemon failed to start after upgrade" in line
        )
        end = lines.index("exit 1", start)
        assert "_record_tracking" in lines[start:end]

    def test_the_rollback_restores_the_previous_tracking(self) -> None:
        text = UPGRADE_SCRIPT.read_text()
        start = text.index("cleanup_on_failure() {")
        assert "restore_install_tracking" in text[start : text.index("trap cleanup_on_failure")]
