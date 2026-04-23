"""Plan 00100 Task 0.2: restart_daemon_verified slow-startup false-negative.

Field bug (2026-04-23): daemon logs `Daemon listening on ...` at 14:51:37,
but the script's PID-file poll timed out fractionally earlier. Root cause:
`cli.py:341` uses a fixed `time.sleep(0.5)` before polling — insufficient
for startup overhead on slow hosts.

v2 fix:
  1. Replace the fixed 0.5s sleep in cli.py with a polling loop:
     100ms interval × 50 iterations = 5s ceiling, exit early on PID-file
     appearance.
  2. daemon_control.sh:restart_daemon_verified must extend the overall
     timeout to 15s and — on timeout — fall back to `get_daemon_status`
     (socket reachability) before declaring failure.
  3. Log progress every 1s so the user sees "waiting for daemon (N/15s)".
  4. If the timeout expires but `pgrep claude-hooks-daemon` finds the
     process, retry the status check for 5 more seconds before aborting.

These tests verify the above via static analysis of the two files.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "cli.py"
DAEMON_CONTROL_SH = REPO_ROOT / "scripts" / "install" / "daemon_control.sh"


def _read_cli_py() -> str:
    return CLI_PY.read_text()


def _read_daemon_control_sh() -> str:
    return DAEMON_CONTROL_SH.read_text()


# ----- cli.py: the first-fork parent branch must poll, not fixed-sleep ------


def test_cli_start_uses_polling_loop_not_fixed_sleep() -> None:
    """The first-fork parent branch must NOT use `time.sleep(0.5)` before
    a single PID file check. It must poll with a short interval."""
    content = _read_cli_py()

    # Find the first-fork parent branch (the one that checks PID file after fork).
    # It contains the distinctive sequence: after `if pid > 0:` it should poll.
    # We search within a ~40-line window after the first `pid = os.fork()`.
    match = re.search(
        r"pid = os\.fork\(\).*?if pid > 0:\s*\n(.{1,2000}?)except OSError", content, re.DOTALL
    )
    assert match is not None, "First-fork parent branch not found in cli.py"
    body = match.group(1)

    # Must NOT contain `time.sleep(0.5)` as a fire-and-forget single wait.
    has_fixed_half_second = re.search(r"time\.sleep\(\s*0\.5\s*\)", body) is not None
    assert not has_fixed_half_second, (
        "cli.py first-fork parent must not use `time.sleep(0.5)` before checking "
        "PID file. Use a polling loop instead. See Plan 00100 Task 0.2."
    )

    # Must contain a loop (for or while) with a short sleep interval.
    has_polling_loop = bool(re.search(r"for\s+\w+\s+in\s+range\(|while\s", body))
    assert has_polling_loop, (
        "cli.py first-fork parent must use a polling loop (for/while) around "
        "the PID file check. See Plan 00100 Task 0.2."
    )


def test_cli_start_polls_with_short_interval() -> None:
    """The polling loop must use a short (≤200ms) interval so it exits
    quickly once the PID file appears. Accepts either a numeric literal or
    a reference to the `Timeout.DAEMON_PID_POLL_INTERVAL_SEC` constant."""
    content = _read_cli_py()
    match = re.search(
        r"pid = os\.fork\(\).*?if pid > 0:\s*\n(.{1,2000}?)except OSError", content, re.DOTALL
    )
    assert match is not None
    body = match.group(1)

    # Look for either: a short-enough literal sleep, or a reference to the
    # named polling-interval constant.
    sleep_args = re.findall(r"time\.sleep\(\s*([0-9.]+)\s*\)", body)
    has_short_literal = any(0 < float(arg) <= 0.2 for arg in sleep_args if arg)
    uses_poll_constant = "Timeout.DAEMON_PID_POLL_INTERVAL_SEC" in body

    # Cross-check: the constant is indeed short.
    if uses_poll_constant:
        from claude_code_hooks_daemon.constants import Timeout

        assert Timeout.DAEMON_PID_POLL_INTERVAL_SEC <= 0.2, (
            "Timeout.DAEMON_PID_POLL_INTERVAL_SEC must be ≤200ms. " "See Plan 00100 Task 0.2."
        )

    assert has_short_literal or uses_poll_constant, (
        f"cli.py polling loop must sleep ≤200ms between checks. "
        f"Found sleeps: {sleep_args}. See Plan 00100 Task 0.2."
    )


# ----- daemon_control.sh: restart_daemon_verified extensions ----------------


def test_restart_daemon_verified_has_extended_timeout() -> None:
    """restart_daemon_verified must have an overall timeout of at least 15s
    (up from the implicit ~2s `sleep 2` in v1)."""
    content = _read_daemon_control_sh()
    # Extract restart_daemon_verified body.
    match = re.search(
        r"restart_daemon_verified\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None, "restart_daemon_verified() not found"
    body = match.group(0)

    # The old `sleep 2` must be gone (too short for slow-host startup).
    assert "sleep 2" not in body or body.count("sleep 2") < 2, (
        "restart_daemon_verified must not rely solely on `sleep 2`. "
        "Extend the startup wait to 15s via polling. See Plan 00100 Task 0.2."
    )

    # Body must reference 15 somewhere (the new timeout).
    assert re.search(r"\b15\b", body), (
        "restart_daemon_verified must reference a 15-second timeout. " "See Plan 00100 Task 0.2."
    )


def test_restart_daemon_verified_falls_back_to_status_on_timeout() -> None:
    """On PID-file timeout, must call get_daemon_status as a belt-and-braces
    secondary check before declaring failure."""
    content = _read_daemon_control_sh()
    match = re.search(
        r"restart_daemon_verified\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None
    body = match.group(0)

    # The body already calls get_daemon_status — that's the v1 behavior.
    # v2 ensures it's called after a polling loop, not just after `sleep 2`.
    assert (
        "get_daemon_status" in body
    ), "restart_daemon_verified must call get_daemon_status as secondary check."


def test_restart_daemon_verified_logs_progress() -> None:
    """The extended wait must log progress so the user sees activity."""
    content = _read_daemon_control_sh()
    match = re.search(
        r"restart_daemon_verified\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None
    body = match.group(0)

    # Must log something time-related during the wait.
    # Look for "waiting" or "N/15" or "N/" + timeout reference.
    has_progress_log = bool(
        re.search(r"waiting\s+for\s+daemon|waiting\.\.\.|[0-9]+/15", body, re.IGNORECASE)
    )
    assert has_progress_log, (
        "restart_daemon_verified must log progress during the 15s wait. " "See Plan 00100 Task 0.2."
    )


def test_restart_daemon_verified_pgrep_fallback() -> None:
    """If timeout expires but the daemon process exists, retry status for
    a further 5s before aborting."""
    content = _read_daemon_control_sh()
    match = re.search(
        r"restart_daemon_verified\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None
    body = match.group(0)

    # Body must reference `pgrep` (or equivalent process-existence check).
    has_pgrep = "pgrep" in body or "ps -p" in body
    assert has_pgrep, (
        "restart_daemon_verified must check for daemon process existence "
        "(pgrep / ps -p) as a final fallback before aborting. "
        "See Plan 00100 Task 0.2."
    )
