"""Plan 00477 Task 5.2 - a pulled version change is synced in the background.

The tracked session-start forwarder starts ``bash .claude/provision.sh
--background`` detached, and ``provision.sh`` records how far that sync got in a
state file per target version under the daemon's untracked directory.
``version_check`` reads it back at every session start; this module is the one
place in Python that names those files and reads them.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install import background_sync
from claude_code_hooks_daemon.install.background_sync import (
    BACKGROUND_FLAG,
    SyncStatus,
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

    def test_the_session_start_forwarder_starts_the_same_flag(self) -> None:
        forwarder = (REPO_ROOT / ".claude" / "hooks" / "session-start").read_text()

        assert f'provision.sh" {BACKGROUND_FLAG}' in forwarder


class TestInstallerEmitsTheBackgroundSync:
    """The installer is the generator of the tracked forwarder, so it carries the block."""

    def _generated(self, tmp_path: Path, hook_name: str, event_name: str) -> str:
        from install import create_forwarder_script

        return create_forwarder_script(tmp_path, hook_name, event_name).read_text()

    def test_session_start_starts_the_background_sync_before_init(self, tmp_path: Path) -> None:
        content = self._generated(tmp_path, "session-start", "SessionStart")

        assert f'provision.sh" {BACKGROUND_FLAG}' in content
        assert content.index(BACKGROUND_FLAG) < content.index("init.sh")

    def test_no_other_forwarder_starts_it(self, tmp_path: Path) -> None:
        content = self._generated(tmp_path, "pre-tool-use", "PreToolUse")

        assert BACKGROUND_FLAG not in content

    def test_the_block_never_quotes_the_relay_guard_marker(self, tmp_path: Path) -> None:
        """The generator strips a guard by its marker text, so a comment must not carry it."""
        content = self._generated(tmp_path, "session-start", "SessionStart")

        assert "relay hot path" not in content


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
        # A live pid: a "running" record whose process is gone reads as failed.
        live_pid = os.getpid()
        _write_state(
            tmp_path, f"status={raw}\ntarget={_VERSION}\nfrom=3.69.0\npid={live_pid}\ndetail=x\n"
        )

        record = read_sync_record(tmp_path, _VERSION)

        assert record is not None
        assert record.status is status
        assert record.from_version == "3.69.0"
        assert record.pid == live_pid
        assert record.detail == "x"
        assert record.state_path == state_path(tmp_path, _VERSION)
        assert record.log_path == log_path(tmp_path, _VERSION)

    def test_a_detail_may_carry_equals_signs(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "status=failed\ndetail=origin is a=b\n")

        record = read_sync_record(tmp_path, _VERSION)

        assert record is not None and record.detail == "origin is a=b"

    @pytest.mark.parametrize("text", ["", "status=sideways\n", "garbage\n"])
    def test_an_unreadable_state_is_a_failure_not_a_silence(
        self, tmp_path: Path, text: str
    ) -> None:
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


class TestNoProcessIsStartedFromPython:
    def test_the_module_does_not_import_subprocess(self) -> None:
        """The start is the forwarder's, in shell; Python only reads the outcome."""
        source = Path(background_sync.__file__).read_text()

        assert "import subprocess" not in source
        assert not hasattr(background_sync, "launch_background_sync")
