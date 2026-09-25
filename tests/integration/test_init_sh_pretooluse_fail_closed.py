"""Plan 00466 n24 security review: PreToolUse must fail CLOSED on the
client, not just at the daemon.

The review proved a daemon-internal deadline cannot bound GIL-holding code
(B2: a backtracking regex held the GIL for the whole call, so nothing --
not even a timed wait on another thread -- could observe or interrupt it).
The client socket timeout is the only backstop left in that shape, and
``init.sh``'s ``send_request_stdin`` used to fail OPEN for every event
except Stop/SubagentStop on ANY transport failure, including a timeout
against a daemon that was demonstrably alive and simply stuck. This drives
the REAL script (sourced, not re-implemented) against controllable fake
Unix-socket servers to pin the new behaviour end-to-end.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"
BASH = shutil.which("bash") or "/bin/bash"

# Short so the socket_timeout tests do not slow the suite down; long enough
# that the malformed/empty-response tests (no artificial delay) never
# flake on a loaded CI box.
_FAST_TIMEOUT = "0.4"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / ".claude" / "hooks-daemon" / "untracked").mkdir(parents=True)
    shutil.copy(INIT_SH, root / ".claude" / "init.sh")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".claude" / "hooks-daemon.env").write_text(
        'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'
    )
    return root


def _fake_server(*, respond: bytes | None, delay: float = 0.0) -> Iterator[Path]:
    """Bind a real AF_UNIX socket; each connection reads to EOF (or a
    newline) then either sleeps past `delay` with no response
    (socket_timeout), or writes back `respond` and closes.

    Deliberately does not swallow socket errors inside the accept loop
    beyond the one that signals shutdown (`server.close()` breaking a
    blocking `accept()`) — a genuine failure in a request thread is left
    to terminate that thread loudly (Python prints its traceback), which
    is a test-infra concern, not something to hide.
    """
    short_dir = Path(tempfile.mkdtemp(prefix="hd-", dir="/tmp"))  # nosec B108
    sock_path = short_dir / "fake.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    stop = threading.Event()

    def _handle(conn: socket.socket) -> None:
        with conn:
            conn.settimeout(Timeout.DISPATCH_TEST_GENEROUS)
            chunks: list[bytes] = []
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            if delay:
                stop.wait(delay)
            if respond is not None:
                conn.sendall(respond)

    def _serve() -> None:
        server.settimeout(5.0)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                return  # server.close() below breaks the blocking accept()
            _handle(conn)

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    try:
        yield sock_path
    finally:
        stop.set()
        server.close()
        shutil.rmtree(short_dir, ignore_errors=True)


@pytest.fixture
def hanging_socket() -> Iterator[Path]:
    """Accepts and reads the request, then never responds -- the daemon is
    ALIVE and reachable but stuck (the B2 GIL-hang shape)."""
    yield from _fake_server(respond=None, delay=2.0)


@pytest.fixture
def malformed_socket() -> Iterator[Path]:
    """Accepts, reads, and responds with bytes that are not a valid
    PreToolUse decision."""
    yield from _fake_server(respond=b"not valid json at all\n")


@pytest.fixture
def connection_reset_socket() -> Iterator[Path]:
    """Accepts the connection, then immediately RSTs it (SO_LINGER 0) without
    reading anything -- forces the client's own ``sendall()`` to raise
    ``BrokenPipeError``/``ConnectionResetError`` (Plan 00466 N40 review 2
    mA1), the shape a legacy-socket peer past its drain cap produces on a
    large enough payload. ``connect()`` still succeeds first, so this is
    distinct from ``ConnectionRefusedError`` (never reached at all)."""
    short_dir = Path(tempfile.mkdtemp(prefix="hd-", dir="/tmp"))  # nosec B108
    sock_path = short_dir / "fake.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    stop = threading.Event()

    def _serve() -> None:
        server.settimeout(5.0)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                return
            # SO_LINGER (1, 0): close() sends a TCP-style RST rather than a
            # clean FIN, which is what actually produces BrokenPipeError/
            # ConnectionResetError on the peer's next write, not just EOF.
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            conn.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    try:
        yield sock_path
    finally:
        stop.set()
        server.close()
        shutil.rmtree(short_dir, ignore_errors=True)


@pytest.fixture
def wrong_shape_socket() -> Iterator[Path]:
    """Valid JSON, but not one of PreToolUse's two legitimate shapes."""
    yield from _fake_server(respond=b'{"decision": "block"}\n')


@pytest.fixture
def valid_empty_socket() -> Iterator[Path]:
    """A real, legitimate ALLOW-with-nothing-to-say response."""
    yield from _fake_server(respond=b"{}\n")


@pytest.fixture
def valid_deny_socket() -> Iterator[Path]:
    """A real, legitimate DENY response, echoed through unchanged."""
    yield from _fake_server(
        respond=(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "a real guard denied this",
                    }
                }
            )
            + "\n"
        ).encode()
    )


def _send(
    project: Path,
    socket_path: Path,
    event_name: str,
    hook_input: dict[str, Any],
    *,
    socket_timeout: str = _FAST_TIMEOUT,
) -> dict[str, Any]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_HOOKS_", "HOOKS_DAEMON_"))
    }
    env["HOSTNAME"] = "pretooluse-fail-closed-fixture"
    env["CLAUDE_HOOKS_SOCKET_PATH"] = str(socket_path)
    env["CLAUDE_HOOKS_SOCKET_TIMEOUT"] = socket_timeout
    script = (
        "source .claude/init.sh; "
        f"printf '%s' '{json.dumps(hook_input)}' | send_request_stdin '{event_name}'"
    )
    result = subprocess.run(
        [BASH, "-c", script],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), f"no stdout; stderr was: {result.stderr}"
    return json.loads(result.stdout.strip())


_BASH_TOOL_INPUT = {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}


class TestSocketTimeoutFailsClosedForPreToolUse:
    """The review's headline gap: a live-but-stuck daemon used to ALLOW."""

    def test_a_pretooluse_call_is_denied(self, project: Path, hanging_socket: Path) -> None:
        response = _send(project, hanging_socket, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "denied for safety" in hso["permissionDecisionReason"]

    def test_the_recovery_command_is_not_denied(self, project: Path, hanging_socket: Path) -> None:
        """The exact command that would fix a wedged daemon must stay usable."""
        recovery_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "bin/hooks-daemon restart"},
        }
        response = _send(project, hanging_socket, "PreToolUse", recovery_input)
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso

    def test_a_compound_recovery_command_is_still_denied(
        self, project: Path, hanging_socket: Path
    ) -> None:
        """No compound commands: this must NOT ride along with the exemption."""
        compound_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "bin/hooks-daemon restart && rm -rf /"},
        }
        response = _send(project, hanging_socket, "PreToolUse", compound_input)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"

    def test_stop_still_fails_open_unaffected(self, project: Path, hanging_socket: Path) -> None:
        """Regression guard: Stop's existing (deliberate) fail-open on timeout."""
        response = _send(project, hanging_socket, "Stop", {})
        assert response == {}


class TestMalformedResponseFailsClosedForPreToolUse:
    """The socket round-trip succeeded, but what came back is not a verdict."""

    def test_unparseable_bytes_deny(self, project: Path, malformed_socket: Path) -> None:
        response = _send(project, malformed_socket, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"

    def test_valid_json_wrong_shape_denies(self, project: Path, wrong_shape_socket: Path) -> None:
        response = _send(project, wrong_shape_socket, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"

    def test_recovery_command_still_not_denied(self, project: Path, malformed_socket: Path) -> None:
        recovery_input = {
            "tool_name": "Bash",
            "tool_input": {"command": ".claude/hooks-daemon/bin/hooks-daemon status"},
        }
        response = _send(project, malformed_socket, "PreToolUse", recovery_input)
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso


class TestConnectionLostFailsClosedForPreToolUse:
    """connect() succeeded, then the pipe broke -- the daemon WAS reached.

    Plan 00466 N40 review 2 mA1: a legacy-socket peer past the server's
    drain cap (``_drain_oversized_request``) gets exactly this shape --
    ``sendall()`` raises ``BrokenPipeError``/``ConnectionResetError``, which
    the generic ``except Exception`` used to classify as an opaque
    error_type never in the PreToolUse fail-closed allowlist, silently
    ALLOWing a call the daemon never judged.
    """

    def test_a_pretooluse_call_is_denied(
        self, project: Path, connection_reset_socket: Path
    ) -> None:
        response = _send(project, connection_reset_socket, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "denied for safety" in hso["permissionDecisionReason"]

    def test_the_recovery_command_is_not_denied(
        self, project: Path, connection_reset_socket: Path
    ) -> None:
        recovery_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "bin/hooks-daemon restart"},
        }
        response = _send(project, connection_reset_socket, "PreToolUse", recovery_input)
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso


class TestLegitimateResponsesPassThroughUnchanged:
    """The new validation must never reject a REAL verdict."""

    def test_empty_object_allow_passes_through(
        self, project: Path, valid_empty_socket: Path
    ) -> None:
        response = _send(project, valid_empty_socket, "PreToolUse", _BASH_TOOL_INPUT)
        assert response == {}

    def test_a_real_deny_passes_through_unchanged(
        self, project: Path, valid_deny_socket: Path
    ) -> None:
        response = _send(project, valid_deny_socket, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert hso["permissionDecisionReason"] == "a real guard denied this"


class TestDaemonNotReachableKeepsExistingPath:
    """'Daemon not running' is explicitly OUT of scope: existing fail-open."""

    def test_no_socket_at_all_still_fails_open_for_pretooluse(self, project: Path) -> None:
        nonexistent = project / ".claude" / "hooks-daemon" / "untracked" / "does-not-exist.sock"
        response = _send(project, nonexistent, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso
