"""A client socket read-timeout must be reported as an ALIVE daemon (Plan 00177).

``send_request_stdin`` (the init.sh python forwarder) opens the daemon socket
with a single timeout covering connect + send + the whole recv drain. On a large
transcript a slow Stop handler blows that budget; the resulting ``socket.timeout``
was previously collapsed into the SAME ``Hooks daemon not running - protection
not active`` block as a genuinely-absent socket, steering operators to restart a
perfectly healthy daemon.

These tests pin the fixed contract, driving the real forwarder against a mock
Unix socket server that accepts + stalls (so connect + send succeed and only the
recv times out — exactly the "reached but slow" shape):

- Stop/SubagentStop ``socket_timeout``  -> fail OPEN (no ``decision: block``); the
  daemon was reached and is alive, so the stop is allowed rather than wedged.
- genuine-down (missing socket)         -> still fail CLOSED with the honest
  "daemon not running" block (a restart IS the right action there).
- non-Stop ``socket_timeout``           -> honest advisory context that names the
  daemon as ALIVE and says do NOT restart.
- ``CLAUDE_HOOKS_SOCKET_TIMEOUT`` overrides the flat 30 s budget (used here to
  keep the tests fast).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / ".claude" / "init.sh"

_RUN_TIMEOUT_SECONDS = 30
_STOP_PAYLOAD = '{"hook_event_name":"Stop","stop_hook_active":false}'

# A mock daemon: bind a Unix socket, accept, read the request, then sleep WITHOUT
# replying — forcing the client's recv() to time out (connect + send succeed).
# accept() raises OSError once the parent terminate()s and the socket closes;
# that is the loop's normal exit, so it breaks (never a silent pass).
_MOCK_SERVER = """
import socket, sys, time
path = sys.argv[1]
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(path)
srv.listen(1)
while True:
    try:
        conn, _addr = srv.accept()
    except OSError:
        break
    conn.recv(65536)   # drain the request; then never reply
    time.sleep(30)     # client recv() blocks until its own timeout fires
"""


def _sandbox_project(tmp_path: Path) -> Path:
    """Throwaway project that sources a copy of the real init.sh (no .git)."""
    proj = tmp_path / "proj"
    claude_dir = proj / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "init.sh").write_text(_INIT_SH.read_text())
    (claude_dir / "hooks-daemon.env").write_text(
        'export HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/root"\n'
    )
    return proj


def _start_mock_daemon(tmp_path: Path) -> tuple[subprocess.Popen[str], str]:
    """Start the stalling mock daemon; return (process, socket_path)."""
    socket_path = str(tmp_path / "mock-daemon.sock")
    script = tmp_path / "mock_server.py"
    script.write_text(_MOCK_SERVER)
    proc = subprocess.Popen(
        ["python3", str(script), socket_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Wait for the socket file to appear (bind() creates it).
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if Path(socket_path).exists():
            return proc, socket_path
        time.sleep(0.02)
    proc.terminate()
    raise AssertionError("mock daemon socket never appeared")


def _run_forwarder(
    tmp_path: Path, socket_path: str, event: str, timeout: str = "1"
) -> subprocess.CompletedProcess[str]:
    """Source init.sh, point SOCKET_PATH at ``socket_path``, call send_request_stdin."""
    proj = _sandbox_project(tmp_path)
    init_sh = proj / ".claude" / "init.sh"
    # SOCKET_PATH is assigned AFTER sourcing so it overrides init.sh's own value;
    # the forwarder expands $SOCKET_PATH from the current shell env.
    script = (
        f'source "{init_sh}" >/dev/null 2>/dev/null\n'
        f'SOCKET_PATH="{socket_path}"\n'
        'printf %s "$STDIN_PAYLOAD" | send_request_stdin "$1"'
    )
    env = {
        **os.environ,
        "CLAUDE_HOOKS_SOCKET_TIMEOUT": timeout,
        "STDIN_PAYLOAD": _STOP_PAYLOAD,
        "HOME": str(tmp_path),
    }
    return subprocess.run(
        ["bash", "-c", script, "bash", event],
        capture_output=True,
        text=True,
        env=env,
        timeout=_RUN_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize("event", ["Stop", "SubagentStop"])
def test_stop_socket_timeout_fails_open_daemon_alive(tmp_path: Path, event: str) -> None:
    """A read-timeout on Stop allows the stop (no block) — the daemon is alive."""
    proc, socket_path = _start_mock_daemon(tmp_path)
    try:
        result = _run_forwarder(tmp_path, socket_path, event, timeout="1")
    finally:
        proc.terminate()

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    # Fail OPEN: no block. Crucially NOT the "daemon not running" block.
    assert parsed.get("decision") != "block", parsed
    assert "not running" not in json.dumps(parsed).lower()
    # The diagnostic still surfaces on stderr, honestly attributed.
    assert "socket_timeout" in result.stderr


def test_stop_genuine_down_still_fails_closed(tmp_path: Path) -> None:
    """A genuinely-absent socket still blocks with the honest 'not running' reason."""
    missing_socket = str(tmp_path / "nonexistent.sock")
    result = _run_forwarder(tmp_path, missing_socket, "Stop", timeout="1")

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed.get("decision") == "block", parsed
    assert "not running" in parsed.get("reason", "").lower()


def test_non_stop_socket_timeout_context_says_alive(tmp_path: Path) -> None:
    """A non-Stop read-timeout fails open with context naming the daemon ALIVE."""
    proc, socket_path = _start_mock_daemon(tmp_path)
    try:
        result = _run_forwarder(tmp_path, socket_path, "PostToolUse", timeout="1")
    finally:
        proc.terminate()

    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert "decision" not in parsed
    context = parsed["hookSpecificOutput"]["additionalContext"].lower()
    assert "alive" in context
    assert "not restart" in context
