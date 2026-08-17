"""Tests for stale daemon file cleanup in paths.py.

Strategy: active daemons periodically touch their runtime files.
Files not touched within stale_days are from dead containers and safe to remove.
"""

import os
import time
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.daemon.paths import (
    cleanup_stale_daemon_files,
    cleanup_stale_session_dirs,
    touch_daemon_files,
    touch_daemon_files_in_dir,
    write_cleanup_status,
)

_SEVEN_DAYS = 7 * 24 * 3600
_OLD_MTIME = time.time() - _SEVEN_DAYS - 3600  # 1 hour past cutoff


def _make_old(path: Path) -> None:
    """Set file mtime to beyond the 7-day stale cutoff."""
    os.utime(path, (path.stat().st_atime, _OLD_MTIME))


class TestCleanupStaleDaemonFiles:
    """Tests for cleanup_stale_daemon_files()."""

    def test_returns_zero_when_untracked_dir_does_not_exist(self, tmp_path: Path) -> None:
        """Returns 0 when untracked directory hasn't been created yet."""
        nonexistent = tmp_path / "nonexistent"
        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=nonexistent,
        ):
            result = cleanup_stale_daemon_files(tmp_path)
        assert result == 0

    def test_returns_zero_when_directory_is_empty(self, tmp_path: Path) -> None:
        """Returns 0 when untracked directory has no daemon files."""
        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            result = cleanup_stale_daemon_files(tmp_path)
        assert result == 0

    def test_removes_old_daemon_files(self, tmp_path: Path) -> None:
        """Removes daemon files older than max_age_days."""
        pid_file = tmp_path / "daemon-abc123.pid"
        sock_file = tmp_path / "daemon-abc123.sock"
        log_file = tmp_path / "daemon-abc123.log"
        sp_file = tmp_path / "daemon-abc123.socket-path"

        for f in (pid_file, sock_file, log_file, sp_file):
            f.write_text("stale")
            _make_old(f)

        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            result = cleanup_stale_daemon_files(tmp_path, max_age_days=7)

        assert result == 4
        assert not pid_file.exists()
        assert not sock_file.exists()
        assert not log_file.exists()
        assert not sp_file.exists()

    def test_preserves_recently_touched_files(self, tmp_path: Path) -> None:
        """Files touched within max_age_days are preserved (active container)."""
        # Fresh file — mtime is now
        fresh = tmp_path / "daemon-live123.pid"
        fresh.write_text("42")
        # Old file from dead container
        old = tmp_path / "daemon-dead456.pid"
        old.write_text("99")
        _make_old(old)

        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            result = cleanup_stale_daemon_files(tmp_path, max_age_days=7)

        assert result == 1
        assert fresh.exists()
        assert not old.exists()

    def test_ignores_non_daemon_files(self, tmp_path: Path) -> None:
        """Does not touch files that don't start with 'daemon-'."""
        config = tmp_path / "config.yaml"
        config.write_text("foo: bar")
        _make_old(config)

        other = tmp_path / "somefile.sock"
        other.touch()
        _make_old(other)

        old_daemon = tmp_path / "daemon-dead.pid"
        old_daemon.write_text("1")
        _make_old(old_daemon)

        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            result = cleanup_stale_daemon_files(tmp_path, max_age_days=7)

        assert result == 1
        assert config.exists()
        assert other.exists()
        assert not old_daemon.exists()

    def test_respects_custom_max_age_days(self, tmp_path: Path) -> None:
        """max_age_days parameter controls the cutoff threshold."""
        # File that is 2 days old
        two_days_old = tmp_path / "daemon-medium.pid"
        two_days_old.write_text("1")
        mtime_2d = time.time() - (2 * 24 * 3600 + 3600)
        os.utime(two_days_old, (mtime_2d, mtime_2d))

        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            # 7-day cutoff: 2-day-old file is fresh, not removed
            result_7d = cleanup_stale_daemon_files(tmp_path, max_age_days=7)
            assert result_7d == 0
            assert two_days_old.exists()

            # 1-day cutoff: 2-day-old file is stale, removed
            result_1d = cleanup_stale_daemon_files(tmp_path, max_age_days=1)
            assert result_1d == 1
            assert not two_days_old.exists()

    def test_handles_permission_error_gracefully(self, tmp_path: Path) -> None:
        """Does not crash when a file cannot be removed; skips and continues."""
        f1 = tmp_path / "daemon-old1.pid"
        f2 = tmp_path / "daemon-old2.sock"
        for f in (f1, f2):
            f.write_text("old")
            _make_old(f)

        original_unlink = Path.unlink

        def flaky_unlink(self: Path, missing_ok: bool = False) -> None:
            if self.name.endswith(".sock"):
                raise OSError("permission denied")
            original_unlink(self, missing_ok=missing_ok)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
                return_value=tmp_path,
            ),
            patch.object(Path, "unlink", flaky_unlink),
        ):
            result = cleanup_stale_daemon_files(tmp_path, max_age_days=7)

        assert result == 1  # Only .pid removed; .sock failed but didn't crash


class TestTouchDaemonFiles:
    """Tests for touch_daemon_files()."""

    def test_touches_current_daemon_files(self, tmp_path: Path) -> None:
        """Updates mtime on all files belonging to the current daemon instance."""
        # Create current daemon files with old mtime
        sock = tmp_path / "daemon-current.sock"
        pid = tmp_path / "daemon-current.pid"
        for f in (sock, pid):
            f.touch()
            _make_old(f)

        # File from another daemon instance — should NOT be touched
        other = tmp_path / "daemon-other.pid"
        other.write_text("999")
        _make_old(other)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.paths._get_hostname_suffix",
                return_value="-current",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
                return_value=tmp_path,
            ),
        ):
            touch_daemon_files(tmp_path)

        # Current daemon files should have fresh mtime
        cutoff = time.time() - 60  # 1 minute ago
        assert sock.stat().st_mtime > cutoff
        assert pid.stat().st_mtime > cutoff

        # Other daemon's file should still have old mtime
        assert other.stat().st_mtime < cutoff

    def test_handles_missing_files_gracefully(self, tmp_path: Path) -> None:
        """Does not crash when current daemon files don't exist yet."""
        with (
            patch(
                "claude_code_hooks_daemon.daemon.paths._get_hostname_suffix",
                return_value="-current",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
                return_value=tmp_path,
            ),
        ):
            touch_daemon_files(tmp_path)  # Should not raise


class TestCleanupStaleDaemonFilesExceptionBranch:
    """Test the generic Exception handler in cleanup_stale_daemon_files."""

    def test_continues_on_unexpected_exception(self, tmp_path: Path) -> None:
        """Unexpected non-OSError exceptions are logged and skipped, not raised."""
        stale = tmp_path / "daemon-stale.pid"
        stale.write_text("1")
        _make_old(stale)

        import os as _os

        _original_stat = Path.stat

        # Mirrors `Path.stat(*, follow_symlinks=True)` exactly. Python 3.13
        # rewrote `Path.is_dir()` to call `self.stat(follow_symlinks=...)`
        # rather than a bare `self.stat()`, so a stub taking only `self` raises
        # TypeError there instead of exercising the branch under test — passing
        # on 3.11/3.12 and failing on 3.13 alone. A double standing in for a
        # stdlib method has to accept the signature the stdlib actually calls,
        # not the shortest one that happens to work today (Plan 00245).
        def exploding_stat(self: Path, *, follow_symlinks: bool = True) -> _os.stat_result:
            if self.name.endswith(".pid"):
                raise RuntimeError("unexpected stat failure")
            return _original_stat(self, follow_symlinks=follow_symlinks)

        with (
            patch(
                "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
                return_value=tmp_path,
            ),
            patch.object(Path, "stat", exploding_stat),
        ):
            result = cleanup_stale_daemon_files(tmp_path)

        assert result == 0  # Nothing removed, but no crash


class TestTouchDaemonFilesInDir:
    """Tests for touch_daemon_files_in_dir() internals."""

    def test_returns_early_when_dir_missing(self, tmp_path: Path) -> None:
        """Does nothing when the untracked directory doesn't exist."""
        missing = tmp_path / "nonexistent"
        touch_daemon_files_in_dir(missing)  # Should not raise

    def test_handles_touch_oserror(self, tmp_path: Path) -> None:
        """OSError on touch is logged at debug level; does not propagate."""
        sock = tmp_path / "daemon-current.sock"
        sock.touch()

        with (
            patch(
                "claude_code_hooks_daemon.daemon.paths._get_hostname_suffix",
                return_value="-current",
            ),
            patch.object(Path, "touch", side_effect=OSError("read-only")),
        ):
            touch_daemon_files_in_dir(tmp_path)  # Should not raise


class TestWriteCleanupStatus:
    """Tests for write_cleanup_status()."""

    def test_writes_json_file(self, tmp_path: Path) -> None:
        """Writes count and timestamp to cleanup_status.json."""
        import json

        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            write_cleanup_status(tmp_path, 5)

        status_file = tmp_path / "cleanup_status.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text())
        assert data["count"] == 5
        assert "timestamp" in data

    def test_handles_oserror_gracefully(self, tmp_path: Path) -> None:
        """OSError writing the status file is swallowed (best-effort)."""
        with (
            patch(
                "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
                return_value=tmp_path,
            ),
            patch.object(Path, "write_text", side_effect=OSError("disk full")),
        ):
            write_cleanup_status(tmp_path, 3)  # Should not raise


class TestCleanupStaleSessionDirs:
    """Tests for cleanup_stale_session_dirs() (Plan 00181 Task 3.2).

    thread-registry/ and context-sidecar/ accumulate one JSON file per session
    that their writers never delete (they only skip stale entries at read time);
    payload-capture/ holds per-event capture files. A file untouched for
    max_age_days belongs to a dead session and must be aged out here.
    """

    _SUBDIRS = ("thread-registry", "context-sidecar", "payload-capture")

    def test_returns_zero_when_untracked_dir_missing(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent"
        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=nonexistent,
        ):
            assert cleanup_stale_session_dirs(tmp_path) == 0

    def test_returns_zero_when_subdirs_absent(self, tmp_path: Path) -> None:
        """Untracked dir exists but the per-session subdirs were never created."""
        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            assert cleanup_stale_session_dirs(tmp_path) == 0

    def test_removes_old_files_in_each_subdir(self, tmp_path: Path) -> None:
        """One aged file per subdir is removed; the count is the total."""
        for name in self._SUBDIRS:
            subdir = tmp_path / name
            subdir.mkdir()
            stale = subdir / "dead-session.json"
            stale.write_text("stale")
            _make_old(stale)

        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            removed = cleanup_stale_session_dirs(tmp_path, max_age_days=7)

        assert removed == 3
        for name in self._SUBDIRS:
            assert not (tmp_path / name / "dead-session.json").exists()

    def test_preserves_fresh_files(self, tmp_path: Path) -> None:
        """A recently-touched (live-session) file is never removed."""
        subdir = tmp_path / "thread-registry"
        subdir.mkdir()
        fresh = subdir / "live-session.json"
        fresh.write_text("fresh")  # mtime is now

        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            removed = cleanup_stale_session_dirs(tmp_path, max_age_days=7)

        assert removed == 0
        assert fresh.exists()

    def test_removes_only_aged_files_mixed(self, tmp_path: Path) -> None:
        """In one subdir, aged files go and fresh ones stay."""
        subdir = tmp_path / "context-sidecar"
        subdir.mkdir()
        dead = subdir / "dead.json"
        dead.write_text("x")
        _make_old(dead)
        live = subdir / "live.json"
        live.write_text("y")

        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            removed = cleanup_stale_session_dirs(tmp_path, max_age_days=7)

        assert removed == 1
        assert not dead.exists()
        assert live.exists()

    def test_now_override_controls_cutoff(self, tmp_path: Path) -> None:
        """An injected ``now`` far in the future ages out even a fresh file."""
        subdir = tmp_path / "payload-capture"
        subdir.mkdir()
        capture = subdir / "Stop.jsonl"
        capture.write_text("event")  # mtime is now

        future = time.time() + (30 * 86400)  # 30 days ahead
        with patch(
            "claude_code_hooks_daemon.daemon.paths._get_untracked_dir",
            return_value=tmp_path,
        ):
            removed = cleanup_stale_session_dirs(tmp_path, max_age_days=7, now=future)

        assert removed == 1
        assert not capture.exists()
