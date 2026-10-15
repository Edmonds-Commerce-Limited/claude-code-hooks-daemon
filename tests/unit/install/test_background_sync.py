"""Plan 00477 Task 5.2 - a pulled version change is synced in the background.

``version_check`` notices at SessionStart that the running daemon is not the
version ``daemon.expected_version`` names. It must not do the sync inside the
hook's time budget, so it starts ``bash .claude/provision.sh --background``
DETACHED and returns. ``provision.sh`` records how far that sync got in a state
file per target version under the daemon's untracked directory; this module is
the one place that names those files, reads them back and starts the process.
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install import background_sync
from claude_code_hooks_daemon.install.background_sync import (
    BACKGROUND_FLAG,
    BackgroundSyncError,
    SyncStatus,
    launch_background_sync,
    log_path,
    read_sync_record,
    state_path,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_VERSION = "3.70.0"


def _write_state(untracked: Path, text: str, version: str = _VERSION) -> Path:
    path = state_path(untracked, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestPaths:
    def test_one_state_file_and_one_log_per_target_version(self, tmp_path: Path) -> None:
        assert state_path(tmp_path, _VERSION) == tmp_path / "background-sync" / "v3.70.0.state"
        assert log_path(tmp_path, _VERSION) == tmp_path / "background-sync" / "v3.70.0.log"

    def test_provision_writes_the_same_files_this_module_reads(self) -> None:
        """The directory name is spelled in bash too; this holds the two together."""
        script = (REPO_ROOT / "provision.sh").read_text()

        assert f'SYNC_STATE_DIR_NAME="{background_sync.SYNC_STATE_DIR_NAME}"' in script
        assert BACKGROUND_FLAG in script


class TestReadSyncRecord:
    def test_no_state_file_means_never_attempted(self, tmp_path: Path) -> None:
        assert read_sync_record(tmp_path, _VERSION) is None

    @pytest.mark.parametrize(
        ("raw", "status"),
        [
            ("running", SyncStatus.RUNNING),
            ("synced", SyncStatus.SYNCED),
            ("failed", SyncStatus.FAILED),
            ("needs-reading", SyncStatus.NEEDS_READING),
        ],
    )
    def test_reads_the_status_provision_recorded(
        self, tmp_path: Path, raw: str, status: SyncStatus
    ) -> None:
        _write_state(tmp_path, f"status={raw}\ntarget={_VERSION}\nfrom=3.69.0\npid=42\ndetail=x\n")

        record = read_sync_record(tmp_path, _VERSION)

        assert record is not None
        assert record.status is status
        assert record.from_version == "3.69.0"
        assert record.pid == 42
        assert record.detail == "x"
        assert record.state_path == state_path(tmp_path, _VERSION)
        assert record.log_path == log_path(tmp_path, _VERSION)

    def test_a_detail_may_carry_equals_signs(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "status=failed\ndetail=origin is a=b\n")

        record = read_sync_record(tmp_path, _VERSION)

        assert record is not None and record.detail == "origin is a=b"

    @pytest.mark.parametrize("text", ["", "status=sideways\n", "garbage\n"])
    def test_an_unreadable_state_is_a_failure_not_a_silence(self, tmp_path: Path, text: str) -> None:
        _write_state(tmp_path, text)

        record = read_sync_record(tmp_path, _VERSION)

        assert record is not None
        assert record.status is SyncStatus.FAILED
        assert "state file" in record.detail

    def test_a_missing_pid_reads_as_none(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "status=running\n")

        record = read_sync_record(tmp_path, _VERSION)

        assert record is not None and record.pid is None


class TestRunningIsCheckedAgainstTheProcess:
    def test_a_live_pid_is_still_running(self, tmp_path: Path) -> None:
        _write_state(tmp_path, f"status=running\npid={os.getpid()}\n")

        record = read_sync_record(tmp_path, _VERSION)

        assert record is not None and record.status is SyncStatus.RUNNING

    def test_a_dead_pid_is_a_failure_naming_it(self, tmp_path: Path) -> None:
        dead = _a_dead_pid()
        _write_state(tmp_path, f"status=running\npid={dead}\n")

        record = read_sync_record(tmp_path, _VERSION)

        assert record is not None
        assert record.status is SyncStatus.FAILED
        assert str(dead) in record.detail
        assert "without recording a result" in record.detail


def _a_dead_pid() -> int:
    """A pid that names no process: one past the highest the kernel will assign."""
    return int(Path("/proc/sys/kernel/pid_max").read_text()) + 1


def _script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "provision.sh"
    script.write_text(f"#!/bin/bash\nset -euo pipefail\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _wait_for(path: Path, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().endswith("\n"):
            return path.read_text()
        time.sleep(0.05)
    raise AssertionError(f"{path} was not written within {timeout}s")


class TestLaunchBackgroundSync:
    def test_runs_the_script_with_the_background_flag_from_the_project_root(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        out = tmp_path / "ran.txt"
        script = _script(tmp_path, f'printf "%s %s\\n" "$PWD" "$*" > "{out}"')
        untracked = tmp_path / "untracked"

        launch_background_sync(script, project, untracked, _VERSION)

        assert _wait_for(out) == f"{project} {BACKGROUND_FLAG}\n"

    def test_returns_before_the_sync_finishes(self, tmp_path: Path) -> None:
        done = tmp_path / "done.txt"
        script = _script(tmp_path, f'sleep 3\necho done > "{done}"')

        started = time.monotonic()
        launch_background_sync(script, tmp_path, tmp_path / "untracked", _VERSION)

        assert time.monotonic() - started < 2.0
        assert not done.exists()

    def test_output_goes_to_the_target_versions_log(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        script = _script(tmp_path, "echo to-stdout\necho to-stderr >&2")

        returned = launch_background_sync(script, tmp_path, untracked, _VERSION)

        assert returned == log_path(untracked, _VERSION)
        text = _wait_for_lines(returned, 2)
        assert "to-stdout" in text and "to-stderr" in text

    def test_the_sync_runs_in_its_own_session(self, tmp_path: Path) -> None:
        """A restart stops the daemon that launched it; the sync must outlive that."""
        out = tmp_path / "sid.txt"
        script = _script(tmp_path, f'ps -o sid= -p $$ > "{out}"')

        launch_background_sync(script, tmp_path, tmp_path / "untracked", _VERSION)

        assert int(_wait_for(out).strip()) != os.getsid(0)

    def test_a_missing_script_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        with pytest.raises(BackgroundSyncError, match="provision.sh"):
            launch_background_sync(
                tmp_path / "provision.sh", tmp_path, tmp_path / "untracked", _VERSION
            )

    def test_no_bash_is_reported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        script = _script(tmp_path, "true")
        monkeypatch.setattr(background_sync.shutil, "which", lambda _name: None)

        with pytest.raises(BackgroundSyncError, match="bash"):
            launch_background_sync(script, tmp_path, tmp_path / "untracked", _VERSION)


def _wait_for_lines(path: Path, lines: int, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and len(path.read_text().splitlines()) >= lines:
            return path.read_text()
        time.sleep(0.05)
    raise AssertionError(f"{path} did not reach {lines} lines within {timeout}s")
