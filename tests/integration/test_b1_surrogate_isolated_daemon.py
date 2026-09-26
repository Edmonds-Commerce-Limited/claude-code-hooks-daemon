r"""Plan 00466 N40 M2 follow-up — B1's surrogate crash, end to end against an
isolated daemon.

``NIGGLES.md`` N40's B1 remedy (``core/chain.py``'s ``_safety_payload_size``,
fixed at ``362e2516``) was pinned by ``tests/unit/core/test_chain.py`` and
``tests/unit/daemon/test_controller.py`` calling ``chain.execute``/
``controller.process_event``/``process_request`` directly, but the review's
own real-socket reproducer for this specific shape was never automated
(explicitly recorded as not-yet-done in N40's write-up). This file is that
live-socket gate, mirroring ``test_n24_strict_mode_probe_isolated_daemon.py``:
it starts its OWN isolated daemon (the DEFAULT handler set, no probe handler
needed — B1 lives in core dispatch, not a project handler) and sends a real
PreToolUse payload carrying a lone UTF-16 surrogate, exactly the shape a
model's tool arguments can produce via a ``"\ud800"`` JSON escape.

Reproduced manually before the fix (NIGGLES.md N40, B1): ``git reset --hard
HEAD # \ud800`` was ALLOWED on the vulnerable branch (a crash inside
``_safety_payload_size``, running OUTSIDE every handler's own try/except,
reached ``DaemonController``'s catch-all and built a fail-open
``HookResult.error()``) and DENIED on base ``3104434b``, where the same
command has no surrogate. The tests below assert the fixed shape: a
SAFETY+BLOCKING handler (``prevent-destructive-git``) still gets to deny the
command despite the payload the surrogate sits inside, and the daemon never
crashes/closes the connection.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout
from tests.dispatch_timeouts import DispatchTestTimeout

_DENY = "deny"

# A lone (unpaired) UTF-16 high surrogate. Written as an escape here so this
# SOURCE FILE stays valid UTF-8; `json.dumps` below re-escapes it the same
# way either way (default `ensure_ascii=True`), which is what makes this
# representable in JSON text at all despite not being a valid Unicode scalar
# value on its own.
_LONE_SURROGATE = "\ud800"


@pytest.fixture
def surrogate_daemon_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """An isolated project with the DEFAULT handler set (no probe needed):
    B1's fix lives in ``core/chain.py``'s own dispatch, exercised by any
    SAFETY+BLOCKING handler, not a bespoke test-only handler. Mirrors
    ``tests/integration/test_daemon_smoke.py``'s ``daemon_env``.
    """
    test_id = tmp_path.name[-20:]
    socket_path = Path(f"/tmp/test-b1-surrogate-{test_id}.sock")
    pid_path = Path(f"/tmp/test-b1-surrogate-{test_id}.pid")
    log_path = Path(f"/tmp/test-b1-surrogate-{test_id}.log")

    monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(socket_path))
    monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(pid_path))
    monkeypatch.setenv("CLAUDE_HOOKS_LOG_PATH", str(log_path))

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/test/repo.git"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("# Test Project\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    (config_dir / "hooks-daemon.yaml").write_text(
        "version: '1.0'\n"
        "daemon:\n"
        "  idle_timeout_seconds: 600\n"
        "  log_level: INFO\n"
        "  self_install_mode: true\n"
        "handlers:\n"
        "  pre_tool_use: {}\n"
        "  post_tool_use: {}\n"
        "  session_start: {}\n"
    )

    return {
        "project_root": tmp_path,
        "socket_path": socket_path,
    }


@pytest.fixture
def surrogate_daemon_process(surrogate_daemon_env: dict[str, Any]):
    """Start the isolated daemon and ensure it is stopped after the test."""
    project_root = surrogate_daemon_env["project_root"]
    test_env = os.environ.copy()

    start_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "start"]
    with open("/dev/null", "w") as devnull:
        result = subprocess.run(
            start_cmd,
            cwd=project_root,
            env=test_env,
            stdout=devnull,
            stderr=devnull,
            timeout=DispatchTestTimeout.OUTER_BOUND,
        )
    if result.returncode != 0:
        pytest.fail(f"Failed to start daemon (exit code {result.returncode})")

    time.sleep(1)

    status_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "status"]
    status_result = subprocess.run(
        status_cmd,
        cwd=project_root,
        env=test_env,
        capture_output=True,
        text=True,
        timeout=Timeout.SOCKET_CONNECT,
    )
    if "RUNNING" not in status_result.stdout:
        pytest.fail(f"Daemon not running after start:\n{status_result.stdout}")

    yield surrogate_daemon_env

    stop_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "stop"]
    subprocess.run(
        stop_cmd,
        cwd=project_root,
        env=test_env,
        capture_output=True,
        timeout=Timeout.SOCKET_CONNECT,
    )
    time.sleep(0.5)


def _send_pre_tool_use(
    sock_path: Path, cwd: Path, *, tool_name: str, tool_input: dict[str, Any]
) -> dict[str, Any]:
    """Send a raw PreToolUse event and return the daemon's parsed response.

    A closed connection or an unparseable/empty response (the crash-to-
    fail-open shape B1 fixed) surfaces as a `json.JSONDecodeError` /
    `ConnectionError` here, not a quiet fall-through -- either is a real
    test failure, not a value this helper swallows.
    """
    hook_input: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(cwd),
    }
    payload = {"event": "PreToolUse", "hook_input": hook_input}
    # `ensure_ascii=True` (the default) escapes the lone surrogate as a plain
    # `\ud800` ASCII sequence -- valid JSON text, and exactly how a model's
    # tool arguments reach the daemon over the wire (see `_LONE_SURROGATE`).
    request = json.dumps(payload).encode("utf-8") + b"\n"

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(Timeout.SOCKET_DISPATCH_ROUNDTRIP)
        sock.connect(str(sock_path))
        sock.sendall(request)
        sock.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)

    raw = b"".join(chunks).decode("utf-8").strip()
    return json.loads(raw)


def _decision(response: dict[str, Any]) -> str:
    return str(response.get("hookSpecificOutput", {}).get("permissionDecision", ""))


def _reason(response: dict[str, Any]) -> str:
    return str(response.get("hookSpecificOutput", {}).get("permissionDecisionReason", ""))


def test_a_lone_surrogate_in_command_still_denies_a_destructive_git_command(
    surrogate_daemon_process: dict[str, Any],
) -> None:
    """B1's own manual reproducer, automated: a SAFETY+BLOCKING handler
    (``prevent-destructive-git``) still gets a real verdict on a command
    carrying a lone surrogate, rather than the size measurement crashing
    OUTSIDE its try/except and reaching the daemon's fail-open catch-all.
    """
    project_root = surrogate_daemon_process["project_root"]
    socket_path = surrogate_daemon_process["socket_path"]

    command = f"git reset --hard HEAD~1 # {_LONE_SURROGATE}"
    response = _send_pre_tool_use(
        socket_path, project_root, tool_name="Bash", tool_input={"command": command}
    )

    assert _decision(response) == _DENY, (
        f"A destructive git command must still be denied when the payload also "
        f"carries a lone UTF-16 surrogate -- got {response!r}"
    )
    assert "reset --hard" in _reason(response) or "destructive" in _reason(response).lower(), (
        f"The deny must come from the real destructive-git guard, not a generic "
        f"size-measurement-crash fallback -- got reason {_reason(response)!r}"
    )


def test_a_lone_surrogate_in_file_path_does_not_crash_the_daemon(
    surrogate_daemon_process: dict[str, Any],
) -> None:
    """B2's own vector (``file_path``, not ``content``) carrying the SAME
    surrogate shape: the daemon must return a well-formed decision, not
    close the connection or hang past the round-trip timeout.
    """
    project_root = surrogate_daemon_process["project_root"]
    socket_path = surrogate_daemon_process["socket_path"]

    response = _send_pre_tool_use(
        socket_path,
        project_root,
        tool_name="Write",
        tool_input={
            "file_path": f"/tmp/{_LONE_SURROGATE}-notes.txt",
            "content": "hello",
        },
    )

    # Not asserting a SPECIFIC decision here (no destructive pattern in this
    # payload) -- only that the daemon produced a real, well-formed verdict
    # rather than crashing or hanging. `_send_pre_tool_use` above already
    # raises on a closed/unparseable connection.
    assert _decision(response) in {"", _DENY, "allow"}, response
