"""Regression tests for the pid-file culprit signal in
``no_test_writes_tracked_generated_docs`` (tests/conftest.py).

Plan 00466 N39 (widened): a mid-run rewrite of a tracked generated doc was
traced to an EXTERNAL ``./bin/hooks-daemon restart`` during a live test run,
not to any test. ``_daemon_pid_file_mtime`` is the one-stat helper the fixture
uses to name that specific external cause in its failure message instead of
the generic "suspect an external edit" text.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import _daemon_pid_file_mtime


class TestDaemonPidFileMtime:
    """Unit coverage for the extracted helper, independent of the fixture."""

    def test_returns_none_when_pid_file_does_not_exist(self, tmp_path: Path) -> None:
        missing = tmp_path / "daemon.pid"
        assert _daemon_pid_file_mtime(missing) is None

    def test_returns_the_files_mtime_when_it_exists(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("12345")

        result = _daemon_pid_file_mtime(pid_file)

        assert result == pid_file.stat().st_mtime

    def test_reflects_a_restart_touching_the_file_between_two_calls(self, tmp_path: Path) -> None:
        """A restart removes and recreates (or rewrites) the pid file, so
        the mtime observed before and after must differ -- this is the
        exact signal the fixture compares across its window."""
        pid_file = tmp_path / "daemon.pid"
        pid_file.write_text("111")
        before = _daemon_pid_file_mtime(pid_file)

        pid_file.unlink()
        pid_file.write_text("222")
        # Force a distinct mtime regardless of filesystem timestamp
        # granularity -- the fixture only cares that before != after.
        import os

        stat = pid_file.stat()
        os.utime(pid_file, (stat.st_atime, stat.st_mtime + 1))
        after = _daemon_pid_file_mtime(pid_file)

        assert before != after
