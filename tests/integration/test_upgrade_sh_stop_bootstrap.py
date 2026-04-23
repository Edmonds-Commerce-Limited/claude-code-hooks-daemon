"""Integration tests for upgrade.sh's pre-checkout daemon-stop step.

Plan 00100 Task 2.5: the pre-checkout stop block used to resolve a venv
python just to run ``daemon.cli stop``. That reintroduced the very
precedence logic we were trying to delete (Phase 2 SSOT). This test pins
the refactored behaviour: stop the daemon by PID-killing every
``$DAEMON_DIR/untracked/daemon-*.pid`` — zero venv lookups, zero Python
invocations.

The refactor contract:

  1. No venv python is required on disk for the stop step to run.
  2. Every PID listed in ``untracked/daemon-*.pid`` receives SIGTERM.
  3. Missing or empty PID files are silently skipped (stop is best-effort).
  4. Missing ``untracked/`` directory is silently skipped (fresh install).
  5. The script does not shell out to ``python``, ``python3``, or any
     ``claude_code_hooks_daemon.daemon.cli`` command for this step.

Tests run just the stop block by extracting the dedicated helper function
from upgrade.sh and invoking it against a fake DAEMON_DIR.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"

SLEEP_BIN = "/bin/sleep"
TRUE_BIN = "/bin/true"

# Harness: extract the _stop_running_daemons function body from upgrade.sh
# by awk-filtering between the opening brace line and the matching closing
# brace, then source that snippet and invoke the function. This is safer
# than running the whole script (which would hit git, curl, etc.).
HARNESS = r"""
set -euo pipefail
awk '/^_stop_running_daemons\(\) \{/,/^\}$/' "$UPGRADE_SH_PATH" > "$TMP_FN_FILE"
# shellcheck disable=SC1090
source "$TMP_FN_FILE"
_stop_running_daemons "$DAEMON_DIR"
"""


def _spawn_sleeper() -> subprocess.Popen[bytes]:
    """Start a 30-second sleep that we can pretend is the daemon."""
    return subprocess.Popen([SLEEP_BIN, "30"])


def _write_pid_file(untracked: Path, name: str, pid: int) -> Path:
    pid_file = untracked / name
    pid_file.write_text(f"{pid}\n")
    return pid_file


def _process_alive(pid: int) -> bool:
    """Return True iff pid is running AND not a zombie.

    A sleeper terminated by SIGTERM but not yet reaped by pytest is a zombie
    whose PID is still allocated (``os.kill(pid, 0)`` succeeds), so that
    check alone incorrectly reports "alive". /proc/<pid>/status reports
    ``State: Z (zombie)`` for such processes — treat that as dead.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    status_path = Path(f"/proc/{pid}/status")
    try:
        status = status_path.read_text()
    except FileNotFoundError:
        return False
    for line in status.splitlines():
        if line.startswith("State:"):
            return "Z" not in line
    return True


def _run_stop_step(daemon_dir: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    tmp_fn = tmp_path / "stop_fn.sh"
    env = os.environ.copy()
    env.update(
        UPGRADE_SH_PATH=str(UPGRADE_SH),
        TMP_FN_FILE=str(tmp_fn),
        DAEMON_DIR=str(daemon_dir),
    )
    return subprocess.run(
        ["bash", "-c", HARNESS],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class TestStopHelperExists:
    """Task 2.5 contract: upgrade.sh must expose a _stop_running_daemons function."""

    def test_function_is_defined(self) -> None:
        content = UPGRADE_SH.read_text()
        assert "_stop_running_daemons()" in content, (
            "upgrade.sh must define _stop_running_daemons() so the stop logic "
            "is isolated and testable. The inline for-loop over venv-* in "
            "upgrade.sh:156-164 must be replaced."
        )


class TestNoVenvDependency:
    """The stop step must not reference the venv at all."""

    def _extract_function_body(self) -> str:
        content = UPGRADE_SH.read_text()
        lines = content.splitlines()
        in_fn = False
        body: list[str] = []
        for line in lines:
            if line.startswith("_stop_running_daemons()"):
                in_fn = True
                continue
            if in_fn:
                if line == "}":
                    break
                body.append(line)
        return "\n".join(body)

    def test_no_venv_python_references_in_stop_function(self) -> None:
        fn_text = self._extract_function_body()
        assert "venv-" not in fn_text, (
            "Stop function must not enumerate untracked/venv-* — that "
            "duplicates SSOT precedence. Use the PID file directly."
        )
        assert (
            "bin/python" not in fn_text
        ), "Stop function must not invoke any venv python — PID-kill only."
        assert (
            "claude_code_hooks_daemon.daemon.cli" not in fn_text
        ), "Stop function must not shell out to daemon.cli — PID-kill only."


class TestStopByPidFile:
    def test_sigterms_pid_from_pid_file(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)

        proc = _spawn_sleeper()
        try:
            _write_pid_file(untracked, "daemon-testhost.pid", proc.pid)
            result = _run_stop_step(daemon_dir, tmp_path)
            assert result.returncode == 0, f"stderr: {result.stderr}"

            for _ in range(30):
                if not _process_alive(proc.pid):
                    break
                time.sleep(0.05)
            assert not _process_alive(
                proc.pid
            ), "Sleeper should have been terminated by the stop step's SIGTERM"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_stops_multiple_daemons(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)

        p1 = _spawn_sleeper()
        p2 = _spawn_sleeper()
        try:
            _write_pid_file(untracked, "daemon-hostA.pid", p1.pid)
            _write_pid_file(untracked, "daemon-hostB.pid", p2.pid)
            result = _run_stop_step(daemon_dir, tmp_path)
            assert result.returncode == 0, f"stderr: {result.stderr}"

            for _ in range(30):
                if not _process_alive(p1.pid) and not _process_alive(p2.pid):
                    break
                time.sleep(0.05)
            assert not _process_alive(p1.pid)
            assert not _process_alive(p2.pid)
        finally:
            for p in (p1, p2):
                if p.poll() is None:
                    p.kill()
                    p.wait()


class TestStopIsBestEffort:
    def test_missing_untracked_dir_is_noop(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        result = _run_stop_step(daemon_dir, tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_no_pid_files_is_noop(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)
        result = _run_stop_step(daemon_dir, tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_empty_pid_file_is_skipped(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)
        (untracked / "daemon-testhost.pid").write_text("")
        result = _run_stop_step(daemon_dir, tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_stale_pid_file_is_skipped(self, tmp_path: Path) -> None:
        """A PID pointing at a non-existent process should not cause failure."""
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)

        dead = subprocess.Popen([TRUE_BIN])
        dead.wait()
        dead_pid = dead.pid

        if _process_alive(dead_pid):
            pytest.skip("Could not synthesise a stale PID on this platform")

        _write_pid_file(untracked, "daemon-stale.pid", dead_pid)
        result = _run_stop_step(daemon_dir, tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_nonnumeric_pid_file_is_skipped(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)
        (untracked / "daemon-bad.pid").write_text("not-a-pid\n")
        result = _run_stop_step(daemon_dir, tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"
