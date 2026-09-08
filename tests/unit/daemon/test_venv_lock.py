"""Plan 00100 Task 4.3: the Python side of the venv build lock.

``hooks-daemon repair`` runs ``uv sync`` into the same fingerprint-keyed venv
that a concurrently starting daemon's ``ensure_venv`` (scripts/install/venv.sh)
may be rebuilding. Both must contend on ONE lock — the same file, the same
backend selection — or the bash lock only serialises bash with bash.

``venv_lock`` mirrors the bash contract exactly:

- lock file ``{project_root}/untracked/.venv-bootstrap.lock`` (flock), or
  ``.venv-bootstrap.lock.d`` (mkdir fallback);
- bounded wait, then ``VenvLockTimeout`` whose message names the lock path
  and the bound;
- ``HOOKS_DAEMON_VENV_LOCK_BACKEND`` selects the backend; a stale mkdir lock
  is reclaimed after ``HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS``.

The cross-language cases hold the lock from a real bash ``flock`` process,
because the whole point is exclusion against ``ensure_venv``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.venv_lock import (
    DEFAULT_TIMEOUT_SECONDS,
    VENV_LOCK_FILE_NAME,
    VenvLockTimeout,
    venv_lock,
    venv_lock_path,
)

BASH = shutil.which("bash") or "/bin/bash"


def _hold_flock(lock_file: Path, seconds: int) -> subprocess.Popen[str]:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    script = f'exec 9>"{lock_file}"; flock 9; echo held; sleep {seconds}'
    proc = subprocess.Popen(
        [BASH, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "held"
    return proc


class TestLockPath:
    def test_lock_file_sits_beside_the_venvs(self, tmp_path: Path) -> None:
        assert venv_lock_path(tmp_path) == tmp_path / "untracked" / VENV_LOCK_FILE_NAME
        assert VENV_LOCK_FILE_NAME == ".venv-bootstrap.lock"

    def test_default_bound_matches_the_bash_default(self) -> None:
        assert DEFAULT_TIMEOUT_SECONDS == 120


class TestFlockBackend:
    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with venv_lock(tmp_path, timeout_seconds=1, backend="flock"):
            assert venv_lock_path(tmp_path).is_file()
        # Released: a fresh acquisition must not wait.
        started = time.monotonic()
        with venv_lock(tmp_path, timeout_seconds=1, backend="flock"):
            pass
        assert time.monotonic() - started < 0.5

    def test_excludes_a_bash_flock_holder_and_names_the_lock(self, tmp_path: Path) -> None:
        lock_file = venv_lock_path(tmp_path)
        holder = _hold_flock(lock_file, seconds=30)
        try:
            with pytest.raises(VenvLockTimeout) as excinfo:
                with venv_lock(tmp_path, timeout_seconds=1, backend="flock"):
                    pytest.fail("must not enter the critical section while bash holds it")
        finally:
            holder.kill()
            holder.wait()
        message = str(excinfo.value)
        assert str(lock_file) in message
        assert "1s" in message
        assert "gave up waiting for the venv lock" in message

    def test_waits_for_a_holder_that_releases(self, tmp_path: Path) -> None:
        lock_file = venv_lock_path(tmp_path)
        holder = _hold_flock(lock_file, seconds=1)
        try:
            started = time.monotonic()
            with venv_lock(tmp_path, timeout_seconds=10, backend="flock"):
                waited = time.monotonic() - started
        finally:
            holder.kill()
            holder.wait()
        assert waited >= 0.5, "must have waited for the bash holder to release"

    def test_wait_is_announced(self, tmp_path: Path) -> None:
        lock_file = venv_lock_path(tmp_path)
        holder = _hold_flock(lock_file, seconds=1)
        notices: list[str] = []
        try:
            with venv_lock(tmp_path, timeout_seconds=10, backend="flock", on_wait=notices.append):
                pass
        finally:
            holder.kill()
            holder.wait()
        assert len(notices) == 1
        assert "waiting up to 10s" in notices[0]
        assert str(lock_file) in notices[0]


class TestMkdirBackend:
    def test_acquires_creates_and_removes_the_dir(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "untracked" / f"{VENV_LOCK_FILE_NAME}.d"
        with venv_lock(tmp_path, timeout_seconds=1, backend="mkdir"):
            assert lock_dir.is_dir()
            assert (lock_dir / "pid").read_text().strip() == str(os.getpid())
        assert not lock_dir.exists()

    def test_fresh_lock_dir_times_out_with_its_path(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "untracked" / f"{VENV_LOCK_FILE_NAME}.d"
        lock_dir.mkdir(parents=True)
        with pytest.raises(VenvLockTimeout) as excinfo:
            with venv_lock(tmp_path, timeout_seconds=1, backend="mkdir"):
                pytest.fail("must not enter while a fresh lock dir exists")
        assert str(lock_dir) in str(excinfo.value)

    def test_stale_lock_dir_is_reclaimed(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "untracked" / f"{VENV_LOCK_FILE_NAME}.d"
        lock_dir.mkdir(parents=True)
        an_hour_ago = time.time() - 3600
        os.utime(lock_dir, (an_hour_ago, an_hour_ago))
        notices: list[str] = []
        with venv_lock(tmp_path, timeout_seconds=1, backend="mkdir", on_wait=notices.append):
            assert (lock_dir / "pid").exists(), "reclaimed and re-taken by this process"
        assert any("stale venv lock" in n for n in notices)

    def test_stale_threshold_is_configurable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock_dir = tmp_path / "untracked" / f"{VENV_LOCK_FILE_NAME}.d"
        lock_dir.mkdir(parents=True)
        ten_seconds_ago = time.time() - 10
        os.utime(lock_dir, (ten_seconds_ago, ten_seconds_ago))
        monkeypatch.setenv("HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS", "5")
        with venv_lock(tmp_path, timeout_seconds=1, backend="mkdir"):
            pass


class TestBackendSelection:
    def test_unknown_backend_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="HOOKS_DAEMON_VENV_LOCK_BACKEND"):
            with venv_lock(tmp_path, timeout_seconds=1, backend="semaphore"):
                pass

    def test_env_var_selects_backend(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_VENV_LOCK_BACKEND", "mkdir")
        lock_dir = tmp_path / "untracked" / f"{VENV_LOCK_FILE_NAME}.d"
        with venv_lock(tmp_path, timeout_seconds=1):
            assert lock_dir.is_dir()

    def test_default_is_flock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_LOCK_BACKEND", raising=False)
        lock_dir = tmp_path / "untracked" / f"{VENV_LOCK_FILE_NAME}.d"
        with venv_lock(tmp_path, timeout_seconds=1):
            assert venv_lock_path(tmp_path).is_file()
            assert not lock_dir.exists()

    def test_timeout_env_var_is_the_default_bound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_VENV_LOCK_TIMEOUT", "1")
        lock_file = venv_lock_path(tmp_path)
        holder = _hold_flock(lock_file, seconds=30)
        try:
            started = time.monotonic()
            with pytest.raises(VenvLockTimeout) as excinfo:
                with venv_lock(tmp_path, backend="flock"):
                    pass
            elapsed = time.monotonic() - started
        finally:
            holder.kill()
            holder.wait()
        assert elapsed < 10
        assert "1s" in str(excinfo.value)
