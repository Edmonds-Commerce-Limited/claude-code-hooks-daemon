"""Review 10, R10-3: a PID file is read with when it was last written.

A daemon writes its PID file after it has started, so a process that started
after the file was written holds a pid reused since. ``stop`` refuses one;
it needs the time from the same open as the pid, so a file rewritten in
between cannot lend a new pid an old time, or an old pid a new one.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.daemon.paths import (
    PidFileText,
    PidRecord,
    read_pid_file,
    read_pid_file_text,
    read_pid_record,
)

_PATHS = "claude_code_hooks_daemon.daemon.paths"
#: Above Linux's default pid_max, so no process can have it.
_NONEXISTENT_PID = 2**22 + 7


def test_the_record_says_when_the_file_was_last_written(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(f"{os.getpid()}\n")
    os.utime(pid_path, (1_000_000.0, 1_000_000.0))

    assert read_pid_record(pid_path) == PidRecord(pid=os.getpid(), written_at=1_000_000.0)


def test_the_pid_file_reads_as_its_record_does(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(f"{os.getpid()}\n")

    assert read_pid_file(pid_path) == os.getpid()


def test_a_file_naming_no_live_pid_has_no_record(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    assert read_pid_record(pid_path) is None
    pid_path.write_text("not a pid\n")
    assert read_pid_record(pid_path) is None
    pid_path.write_text(f"{_NONEXISTENT_PID}\n")
    assert read_pid_record(pid_path) is None


def test_a_live_pid_that_is_no_daemon_has_no_verified_record(tmp_path: Path) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(f"{os.getpid()}\n")

    with patch(f"{_PATHS}.is_daemon_pid", return_value=False):
        assert read_pid_record(pid_path, verify_daemon=True) is None


class TestReadPidFileText:
    """A PID file's text, or why there is none: absent is not unreadable."""

    def test_a_file_gives_its_text(self, tmp_path: Path) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text("123\n")
        assert read_pid_file_text(pid_path) == PidFileText(text="123\n")

    def test_an_absent_file_gives_no_text_and_no_error(self, tmp_path: Path) -> None:
        assert read_pid_file_text(tmp_path / "daemon.pid") == PidFileText(text=None)

    def test_an_unreadable_file_says_why(self, tmp_path: Path) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.mkdir()
        read = read_pid_file_text(pid_path)
        assert read.text is None
        assert read.unreadable is not None and "Is a directory" in read.unreadable

    def test_undecodable_bytes_are_unreadable(self, tmp_path: Path) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_bytes(b"\xff\xfe")
        read = read_pid_file_text(pid_path)
        assert read.text is None
        assert read.unreadable is not None
