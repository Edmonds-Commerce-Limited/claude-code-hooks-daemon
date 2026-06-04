"""Regression: restart_daemon_verified must not report a false failure when
the daemon starter is superseded by single-daemon enforcement (exit 143).

Field bug (2026-06-04, observed twice across consecutive `/hooks-daemon
upgrade` runs): during an upgrade, a live hook-triggered daemon auto-start ran
``enforce_single_daemon``, which SIGTERMed the in-flight ``cli start`` parent
(exit 143). ``restart_daemon_verified`` returned early on the starter's
non-zero exit and reported "Daemon failed to start (exit code 143)" even though
the winning daemon came up healthy and RUNNING.

Root cause: the starter process's exit code was treated as authoritative for
"did the daemon start". Under single-daemon enforcement a *superseded* starter
is EXPECTED, not an error — the authoritative source of truth is the status
poll ("is a daemon RUNNING and serving"), which the function already performs
but only reached when the starter exited 0.

Fix: ``restart_daemon_verified`` records the starter's exit code for
diagnostics but ALWAYS defers the start/no-start decision to the status poll.

These tests source ``daemon_control.sh`` and stub the daemon-touching helpers
so the control flow is exercised deterministically (no real daemon, no race).
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
DAEMON_CONTROL_SH = REPO_ROOT / "scripts" / "install" / "daemon_control.sh"


def _run_harness(stub_body: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Source daemon_control.sh, install stubs, call restart_daemon_verified."""
    fake_python = tmp_path / "python"
    fake_python.write_text("#!/bin/bash\nexit 0\n")
    fake_python.chmod(0o755)

    harness = tmp_path / "harness.sh"
    harness.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            source "{DAEMON_CONTROL_SH}"

            # Make the polling wait instantaneous.
            sleep() {{ :; }}

            # Stubs override the real helpers defined above (bash: later
            # definition wins).
            {stub_body}

            restart_daemon_verified "{fake_python}"
            echo "RESTART_EXIT=$?"
            """))
    harness.chmod(0o755)
    return subprocess.run(
        ["bash", str(harness)],
        capture_output=True,
        text=True,
        timeout=Timeout.DAEMON_STARTUP,
        check=False,
    )


def test_superseded_starter_exit_143_but_daemon_running_is_success(tmp_path: Path) -> None:
    """Starter exits 143 (SIGTERM by enforcement) but a daemon IS running:
    restart_daemon_verified must return success, not a false failure."""
    stubs = """
        stop_daemon_safe() { return 0; }
        start_daemon_safe() {
            DAEMON_START_EXIT_CODE=143
            DAEMON_START_OUTPUT=""
            return 143
        }
        get_daemon_status() { echo "Daemon: RUNNING"; }
    """
    result = _run_harness(stubs, tmp_path)
    assert "RESTART_EXIT=0" in result.stdout, (
        "restart_daemon_verified must succeed when the daemon is RUNNING even "
        "though the starter exited 143 (benign single-daemon enforcement "
        f"supersession).\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_genuine_start_failure_with_no_daemon_still_reports_failure(tmp_path: Path) -> None:
    """Starter fails AND no daemon ever runs: must still report failure so the
    deferral-to-status-poll does not mask a real start failure."""
    stubs = """
        stop_daemon_safe() { return 0; }
        start_daemon_safe() {
            DAEMON_START_EXIT_CODE=1
            DAEMON_START_OUTPUT="ImportError: boom"
            return 1
        }
        get_daemon_status() { echo "Daemon: NOT RUNNING"; }
        pgrep() { return 1; }
    """
    result = _run_harness(stubs, tmp_path)
    assert "RESTART_EXIT=1" in result.stdout, (
        "restart_daemon_verified must still fail when no daemon is running "
        f"after a genuine start failure.\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def test_genuine_failure_surfaces_starter_diagnostics(tmp_path: Path) -> None:
    """When the daemon genuinely is not running, the captured starter output
    must be surfaced so real failures (e.g. ImportError) remain debuggable."""
    stubs = """
        stop_daemon_safe() { return 0; }
        start_daemon_safe() {
            DAEMON_START_EXIT_CODE=1
            DAEMON_START_OUTPUT="ImportError: no module named widget"
            return 1
        }
        get_daemon_status() { echo "Daemon: NOT RUNNING"; }
        pgrep() { return 1; }
    """
    result = _run_harness(stubs, tmp_path)
    combined = result.stdout + result.stderr
    assert "ImportError: no module named widget" in combined, (
        "restart_daemon_verified must echo the captured starter output when the "
        f"daemon is genuinely not running.\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
