"""Issue 1 (`hooks-daemon-niggles.md`, 2026-05-14): SessionStart boot race.

Field report: a session that reported `daemon_startup_failed` had the
daemon up and listening within ~1 second of the SessionStart hook firing.
The hook's bash `start_daemon()` polled for socket appearance for 5s
(50 deciseconds), removed the PID file on timeout, and reported failure
while the daemon continued coming up. Subsequent PreToolUse/PostToolUse
hooks then reported `✅ hook system active`, confirming the false alarm.

Root causes in `init.sh::start_daemon()`:
  1. 5s timeout is too tight for cold-start Python with handler imports
     + config load + asyncio bind on slow disks (containers, cold caches).
     Plan 00100 Task 0.2 already extended the equivalent path in
     `scripts/install/daemon_control.sh::restart_daemon_verified` to 15s.
     `init.sh` was missed.
  2. Polling only checks for socket existence — not whether the daemon
     process is alive and the socket is connectable. A socket file can
     appear and then disappear during enforce-single-daemon restarts.
  3. PID file is unlinked on timeout. If the daemon is genuinely still
     coming up, this destroys its PID slot and `is_daemon_running()`
     returns false even after the daemon binds successfully.

Tests verify the fix via static analysis of `init.sh`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"


def _read_init_sh() -> str:
    return INIT_SH.read_text()


def _extract_start_daemon_body() -> str:
    """Extract the body of the start_daemon() bash function."""
    content = _read_init_sh()
    match = re.search(
        r"^start_daemon\(\)\s*\{(.*?)^\}",
        content,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "start_daemon() not found in init.sh"
    return match.group(1)


def test_daemon_startup_timeout_is_at_least_15_seconds() -> None:
    """DAEMON_STARTUP_TIMEOUT must be ≥150 (deciseconds, i.e. 15s).

    5s (50 deciseconds) was the legacy ceiling and produced false
    `daemon_startup_failed` reports while the daemon was still binding.
    15s matches Timeout.DAEMON_RESTART_VERIFY_TIMEOUT_SEC, the python-side
    constant used by restart_daemon_verified (Plan 00100 Task 0.2).
    """
    content = _read_init_sh()
    match = re.search(r"^DAEMON_STARTUP_TIMEOUT=([0-9]+)", content, re.MULTILINE)
    assert match is not None, "DAEMON_STARTUP_TIMEOUT not defined in init.sh"
    timeout_ds = int(match.group(1))
    assert timeout_ds >= 150, (
        f"DAEMON_STARTUP_TIMEOUT={timeout_ds} deciseconds is too short. "
        f"Cold-start Python with handler imports + asyncio bind can take "
        f"5-10s on slow disks. Use ≥150 (15s) to match python-side "
        f"Timeout.DAEMON_RESTART_VERIFY_TIMEOUT_SEC. See Issue 1 in "
        f"untracked/hooks-daemon-niggles.md."
    )


def test_start_daemon_does_not_unlink_pid_file_on_timeout() -> None:
    """start_daemon() must not `rm -f "$PID_PATH"` on timeout.

    The daemon may genuinely still be coming up when the bash poll
    times out (5-second race observed in the field). Unlinking the
    PID file destroys the daemon's PID slot and makes
    is_daemon_running() return false even after the socket binds.
    Let is_daemon_running() clean stale PIDs on next call instead.
    """
    body = _extract_start_daemon_body()

    # Look for `rm -f` of PID_PATH inside start_daemon — that is the bug.
    pid_unlink = re.search(r'rm\s+-f\s+"?\$\{?PID_PATH\}?"?', body)
    assert pid_unlink is None, (
        "start_daemon() must not unlink PID_PATH on timeout. Remove the "
        '`rm -f "$PID_PATH"` line. is_daemon_running() handles stale PID '
        "cleanup on subsequent calls. See Issue 1 in "
        "untracked/hooks-daemon-niggles.md."
    )


def test_start_daemon_does_final_retry_after_polling_loop() -> None:
    """After the polling loop exits, start_daemon() must do one final
    is_daemon_running + socket check before declaring failure.

    This closes the race where the daemon binds the socket on the
    very tick the polling loop's `elapsed < TIMEOUT` check goes
    false — without the final check, a genuinely successful startup
    is reported as failure.
    """
    body = _extract_start_daemon_body()

    # Find the while-loop tail and check that an is_daemon_running /
    # socket check follows it before the `return 1` / error message.
    # The structure should be:
    #     while [[ $elapsed -lt $TIMEOUT ]]; do ... done
    #     # final retry check
    #     if is_daemon_running && [[ -S "$SOCKET_PATH" ]]; then return 0; fi
    #     echo ERROR ...
    #     return 1

    # Look for the while-loop followed by a final check before failure.
    final_check = re.search(
        r"done\s*\n.*?(is_daemon_running.*?-S\s+\"?\$\{?SOCKET_PATH\}?\"?|"
        r"-S\s+\"?\$\{?SOCKET_PATH\}?\"?.*?is_daemon_running).*?return\s+0",
        body,
        re.DOTALL,
    )
    assert final_check is not None, (
        "start_daemon() must perform a final is_daemon_running + socket "
        "check after the polling loop exits, before returning failure. "
        "This catches daemons that bind right on the timeout boundary. "
        "See Issue 1 in untracked/hooks-daemon-niggles.md."
    )


def test_start_daemon_polling_loop_uses_combined_readiness_check() -> None:
    """The polling loop must check both `is_daemon_running` AND socket
    existence — checking the socket file alone is insufficient.

    Background: enforce_single_daemon_process can leave a transient
    socket file on disk during a kill+respawn cycle. A socket-only
    check could see the stale file and return success before the
    new daemon binds. Combining with is_daemon_running (PID alive)
    guarantees the daemon we just spawned is the one we see.
    """
    body = _extract_start_daemon_body()

    # Find the polling loop body (between `while` and matching `done`).
    loop_match = re.search(
        r"while\s+\[\[\s+\$elapsed\s+-lt\s+\$DAEMON_STARTUP_TIMEOUT\s+\]\];\s*do\s*\n(.*?)^\s*done",
        body,
        re.DOTALL | re.MULTILINE,
    )
    assert loop_match is not None, "Polling loop not found in start_daemon"
    loop_body = loop_match.group(1)

    has_socket_check = re.search(r"-S\s+\"?\$\{?SOCKET_PATH\}?\"?", loop_body) is not None
    has_running_check = "is_daemon_running" in loop_body

    assert has_socket_check and has_running_check, (
        "Polling loop must combine `is_daemon_running` with socket "
        "existence check. Found socket check: "
        f"{has_socket_check}, is_daemon_running: {has_running_check}. "
        "See Issue 1 in untracked/hooks-daemon-niggles.md."
    )
