"""Integration tests for upgrade.sh's pre-checkout daemon-stop step.

Plan 00100 Task 2.5: the pre-checkout stop block used to resolve a venv
python just to run ``daemon.cli stop``. That reintroduced the very
precedence logic we were trying to delete (Phase 2 SSOT). This test pins
the refactored behaviour: stop the daemon by PID-killing every
``$DAEMON_DIR/untracked/daemon-*.pid`` — zero venv lookups, zero Python
invocations.

The refactor contract:

  1. No venv python is required on disk for the stop step to run.
  2. Every PID listed in ``untracked/daemon-*.pid`` that is a daemon server
     for THIS project root receives SIGTERM; any other pid is named and left
     alone (Plan 00466 N59: a stale PID file can name any process).
  3. Missing or empty PID files are silently skipped (stop is best-effort).
  4. Missing ``untracked/`` directory is silently skipped (fresh install).
  5. The script does not shell out to ``python``, ``python3``, or any
     ``claude_code_hooks_daemon.daemon.cli`` command for this step.

Tests run just the stop block by extracting the dedicated helper functions
from upgrade.sh and invoking them against a fake DAEMON_DIR. The "daemons"
are real Python children whose command line is a daemon server's.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"

SLEEP_BIN = "/bin/sleep"
TRUE_BIN = "/bin/true"
DAEMON_MODULE = "claude_code_hooks_daemon.daemon.cli"
_SLEEP = "import time; time.sleep(30)"
_REAP_SECONDS = 10

# Harness: extract the stop function and the identity check it calls from
# upgrade.sh by awk-filtering between each opening brace line and the
# matching closing brace, then source that snippet and invoke the function.
# This is safer than running the whole script (which would hit git, curl, etc.).
HARNESS = r"""
set -euo pipefail
awk '/^_stop_running_daemons\(\) \{/,/^\}$/' "$UPGRADE_SH_PATH" > "$TMP_FN_FILE"
awk '/^_is_project_daemon_pid\(\) \{/,/^\}$/' "$UPGRADE_SH_PATH" >> "$TMP_FN_FILE"
# shellcheck disable=SC1090
source "$TMP_FN_FILE"
_stop_running_daemons "$DAEMON_DIR" "$PROJECT_ROOT"
"""


def _spawn_sleeper() -> subprocess.Popen[bytes]:
    """Start a 30-second sleep: a live process that is NOT a daemon."""
    return subprocess.Popen([SLEEP_BIN, "30"])


def _spawn_daemon(project_root: Path) -> subprocess.Popen[bytes]:
    """A live process whose command line is a daemon server for ``project_root``."""
    return subprocess.Popen(
        [sys.executable, "-c", _SLEEP, DAEMON_MODULE, "--project-root", str(project_root), "start"]
    )


def _spawn_venv_daemon(project_root: Path) -> subprocess.Popen[bytes]:
    """A daemon server identified only by its interpreter's venv path."""
    interpreter = project_root / ".claude" / "hooks-daemon" / "untracked" / "venv-x" / "bin"
    interpreter.mkdir(parents=True)
    python = interpreter / "python"
    python.symlink_to(sys.executable)
    return subprocess.Popen([str(python), "-c", _SLEEP, DAEMON_MODULE, "start"])


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


def _run_stop_step(
    daemon_dir: Path, tmp_path: Path, project_root: Path | None = None
) -> subprocess.CompletedProcess[str]:
    tmp_fn = tmp_path / "stop_fn.sh"
    env = os.environ.copy()
    env.update(
        UPGRADE_SH_PATH=str(UPGRADE_SH),
        TMP_FN_FILE=str(tmp_fn),
        DAEMON_DIR=str(daemon_dir),
        PROJECT_ROOT=str(project_root if project_root is not None else tmp_path),
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


@pytest.fixture
def children() -> Iterator[list[subprocess.Popen[bytes]]]:
    """Children a test starts, killed and reaped afterwards whatever happened."""
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for child in started:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=_REAP_SECONDS)


def _untracked(tmp_path: Path) -> tuple[Path, Path]:
    daemon_dir = tmp_path / "daemon"
    untracked = daemon_dir / "untracked"
    untracked.mkdir(parents=True)
    return daemon_dir, untracked


class TestStopByPidFile:
    def test_sigterms_this_projects_daemon(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon_dir, untracked = _untracked(tmp_path)
        proc = _spawn_daemon(tmp_path)
        children.append(proc)
        _write_pid_file(untracked, "daemon-testhost.pid", proc.pid)

        result = _run_stop_step(daemon_dir, tmp_path)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert proc.wait(timeout=_REAP_SECONDS) == -signal.SIGTERM

    def test_sigterms_a_daemon_identified_by_its_venv_interpreter(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon_dir, untracked = _untracked(tmp_path)
        proc = _spawn_venv_daemon(tmp_path)
        children.append(proc)
        _write_pid_file(untracked, "daemon-testhost.pid", proc.pid)

        result = _run_stop_step(daemon_dir, tmp_path)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert proc.wait(timeout=_REAP_SECONDS) == -signal.SIGTERM

    def test_stops_multiple_daemons(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon_dir, untracked = _untracked(tmp_path)
        p1 = _spawn_daemon(tmp_path)
        p2 = _spawn_daemon(tmp_path)
        children.extend((p1, p2))
        _write_pid_file(untracked, "daemon-hostA.pid", p1.pid)
        _write_pid_file(untracked, "daemon-hostB.pid", p2.pid)

        result = _run_stop_step(daemon_dir, tmp_path)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert p1.wait(timeout=_REAP_SECONDS) == -signal.SIGTERM
        assert p2.wait(timeout=_REAP_SECONDS) == -signal.SIGTERM


class TestAPidThatIsNotThisProjectsDaemonIsNeverSignalled:
    """Plan 00466 N59: a stale PID file can name whatever reused that pid."""

    def test_a_live_non_daemon_is_left_running_and_named(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon_dir, untracked = _untracked(tmp_path)
        bystander = _spawn_sleeper()
        children.append(bystander)
        pid_file = _write_pid_file(untracked, "daemon-testhost.pid", bystander.pid)

        result = _run_stop_step(daemon_dir, tmp_path)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert _process_alive(bystander.pid), "the stop step signalled a non-daemon"
        assert str(pid_file) in result.stderr
        assert "not signalling" in result.stderr

    def test_another_projects_daemon_is_left_running(
        self, tmp_path: Path, children: list[subprocess.Popen[bytes]]
    ) -> None:
        daemon_dir, untracked = _untracked(tmp_path)
        other = _spawn_daemon(tmp_path / "other-project")
        children.append(other)
        _write_pid_file(untracked, "daemon-testhost.pid", other.pid)

        result = _run_stop_step(daemon_dir, tmp_path)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert _process_alive(other.pid), "the stop step signalled another project's daemon"

    @pytest.mark.parametrize("pid", ["1", "$$"])
    def test_init_and_this_shell_are_not_a_daemon(self, tmp_path: Path, pid: str) -> None:
        # The identity check alone, with no kill anywhere in the harness: a
        # defect here must not be able to deliver a signal to init.
        harness = (
            "set -uo pipefail\n"
            "source <(awk '/^_is_project_daemon_pid\\(\\) \\{/,/^\\}$/' \"$UPGRADE_SH_PATH\")\n"
            f'_is_project_daemon_pid {pid} "$PROJECT_ROOT"\n'
        )
        env = {**os.environ, "UPGRADE_SH_PATH": str(UPGRADE_SH), "PROJECT_ROOT": str(tmp_path)}

        result = subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True, env=env, check=False
        )

        assert result.returncode == 1, result.stderr


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
