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
from tests.dispatch_timeouts import DispatchTestTimeout

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
    # No `dir="/tmp"` — mkdtemp's own default tempdir keeps the path short
    # enough for AF_UNIX's ~108-byte sun_path cap (pytest's `tmp_path` nests
    # too deep) without hardcoding a literal path bandit's B108 flags.
    short_dir = Path(tempfile.mkdtemp(prefix="hd-"))
    sock_path = short_dir / "fake.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    stop = threading.Event()

    def _handle(conn: socket.socket) -> None:
        with conn:
            conn.settimeout(DispatchTestTimeout.GENEROUS)
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
    # See _fake_server above: no `dir="/tmp"`, same reasoning.
    short_dir = Path(tempfile.mkdtemp(prefix="hd-"))
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

    def test_a_socket_timeout_below_the_chain_deadline_is_named(
        self, project: Path, hanging_socket: Path
    ) -> None:
        """Plan 00466 N24 review 2: the deny stays, and says what caused it.

        An operator's ``CLAUDE_HOOKS_SOCKET_TIMEOUT`` below the daemon's chain
        deadline makes the client give up before the daemon can answer, so
        every slow chain is denied. The reason must name the variable.
        """
        response = _send(project, hanging_socket, "PreToolUse", _BASH_TOOL_INPUT)
        reason = response["hookSpecificOutput"]["permissionDecisionReason"]
        assert f"CLAUDE_HOOKS_SOCKET_TIMEOUT={_FAST_TIMEOUT}" in reason
        assert "shorter than the daemon's chain deadline" in reason

    def test_the_client_copy_of_the_chain_deadline_matches_the_daemon(self) -> None:
        """init.sh cannot import the constant, so it carries a pinned copy."""
        assert (
            f"_CHAIN_DEADLINE_DEFAULT_SECONDS = {Timeout.CHAIN_DEADLINE_DEFAULT}\n"
            in INIT_SH.read_text()
        )


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


@pytest.fixture
def backlog_full_socket() -> Iterator[Path]:
    """A real AF_UNIX socket that is listening but never calls ``accept()``,
    with its kernel accept backlog pre-filled -- the shape review 3's MA1
    found: a GIL-wedged daemon has stopped accepting, so once the backlog is
    full a fresh ``connect()`` no longer blocks until the client's socket
    timeout, it raises ``BlockingIOError``/``EAGAIN`` immediately. That used
    to fall into the generic ``except Exception`` -> an opaque error_type
    never in the PreToolUse fail-closed allowlist -> silent ALLOW, even
    though the daemon process is provably still there (just wedged).
    """
    short_dir = Path(tempfile.mkdtemp(prefix="hd-"))
    sock_path = short_dir / "fake.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(100)  # matches asyncio's own default backlog

    held: list[socket.socket] = []
    try:
        # Never call server.accept(): each of these queues in the kernel
        # backlog until it overflows, at which point connect() itself starts
        # failing instead of completing -- mirroring review 3's probe
        # (probe_n24r3_gil.py), which filled a live daemon's asyncio-default
        # backlog (100) the same way and hit BlockingIOError right after.
        # The attempt bound is generous headroom above `somaxconn`, which can
        # exceed the requested backlog on some kernels.
        # Unlike AF_INET, an AF_UNIX stream connect() has no handshake to be
        # "in progress" -- it either completes immediately or fails
        # immediately, so BlockingIOError here means the queue is full, not
        # "retry me later".
        err: OSError | None = None
        for _ in range(5000):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.setblocking(False)
            try:
                s.connect(str(sock_path))
                held.append(s)
            except OSError as exc:
                err = exc
                s.close()
                break
        assert err is not None, (
            "backlog never overflowed -- the fixture's assumption "
            "(a small listen() backlog fills after a handful of connects) "
            "no longer holds on this platform"
        )
        yield sock_path
    finally:
        for s in held:
            s.close()
        server.close()
        shutil.rmtree(short_dir, ignore_errors=True)


class TestBacklogFullFailsClosedForPreToolUse:
    """Plan 00466 N24 review 3 MA1: connect() raising BlockingIOError/EAGAIN
    because the daemon's accept backlog is full must DENY PreToolUse, the
    same as a reached-but-stuck daemon -- not ALLOW like a genuinely absent
    one."""

    def test_a_pretooluse_call_is_denied(self, project: Path, backlog_full_socket: Path) -> None:
        response = _send(project, backlog_full_socket, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "denied for safety" in hso["permissionDecisionReason"]

    def test_the_recovery_command_is_not_denied(
        self, project: Path, backlog_full_socket: Path
    ) -> None:
        recovery_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "bin/hooks-daemon restart"},
        }
        response = _send(project, backlog_full_socket, "PreToolUse", recovery_input)
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


class TestDaemonNotReachableFailsClosedForPreToolUse:
    """Plan 00466 N24 review 3 MA4 (owner decision): 'the socket is missing'
    no longer means fail-open for PreToolUse -- it means the daemon could
    not be reached at all, and this project's install/CI story keeps
    ensure_daemon's auto-start ahead of every real call site, so this is
    the wedged/crashed/never-started shape, not the fresh-clone-before-
    install one (that stays fail-open, upstream of this transport, via
    emit_hook_error's own NOT_INSTALLED/VENV_MISSING branches)."""

    @pytest.fixture
    def nonexistent_socket(self) -> Iterator[Path]:
        """A path with no socket at it, short enough that connect() raises a
        genuine ``FileNotFoundError`` rather than AF_UNIX's ~108-byte
        ``ENAMETOOLONG`` -- pytest's own ``tmp_path`` nests too deep for
        that (see the ``_fake_server``/``connection_reset_socket`` fixtures
        above for the same reasoning)."""
        short_dir = Path(tempfile.mkdtemp(prefix="hd-"))
        try:
            yield short_dir / "does-not-exist.sock"
        finally:
            shutil.rmtree(short_dir, ignore_errors=True)

    def test_no_socket_at_all_denies_for_pretooluse(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        response = _send(project, nonexistent_socket, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "denied for safety" in hso["permissionDecisionReason"]

    def test_the_recovery_command_is_not_denied(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        recovery_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "bin/hooks-daemon restart"},
        }
        response = _send(project, nonexistent_socket, "PreToolUse", recovery_input)
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso

    def test_no_socket_at_all_still_fails_open_for_a_non_pretooluse_event(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        """Only PreToolUse changed; every other event keeps the original
        fail-open `additionalContext` contract."""
        response = _send(project, nonexistent_socket, "PostToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso
