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

import contextlib
import errno
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.paths import PID_MAX_LIMIT
from tests.daemon_like_process import (
    DAEMON_CLI_MODULE,
    answering_daemon_socket,
    daemon_like_process,
)
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
    return _make_project(tmp_path / "proj")


def _make_project(root: Path) -> Path:
    """A client project at ``root`` with a copy of ``init.sh`` and both launchers.

    The daemon is installed under ``.claude/hooks-daemon``, so its launcher is
    ``.claude/hooks-daemon/bin/hooks-daemon``. The root ``bin/hooks-daemon``
    links to it, so both spellings the carve-out accepts run this install.
    """
    (root / ".claude" / "hooks-daemon" / "untracked").mkdir(parents=True)
    shutil.copy(INIT_SH, root / ".claude" / "init.sh")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".claude" / "hooks-daemon.env").write_text(
        'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'
    )
    installs_launcher = root / _INSTALL_LAUNCHER
    installs_launcher.parent.mkdir(parents=True)
    installs_launcher.write_text("#!/bin/bash\n")
    (root / _ROOT_LAUNCHER).parent.mkdir()
    (root / _ROOT_LAUNCHER).symlink_to(installs_launcher)
    return root


_INSTALL_LAUNCHER = ".claude/hooks-daemon/bin/hooks-daemon"
_ROOT_LAUNCHER = "bin/hooks-daemon"
#: In ``cli.py``'s order: the daemon clone's launcher first.
_RECOVERY_LAUNCHERS = (_INSTALL_LAUNCHER, _ROOT_LAUNCHER)


def _recovery_input(
    cwd: Path | str | None, command: str = "bin/hooks-daemon restart"
) -> dict[str, Any]:
    """A Bash hook_input for ``command`` whose Bash tool runs in ``cwd``.

    ``cwd`` is what Claude Code puts in every hook input, and the directory a
    relative launcher path resolves against; ``None`` omits the key.
    """
    hook_input: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        hook_input["cwd"] = str(cwd)
    return hook_input


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
    relay_failure: str | None = None,
) -> dict[str, Any]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_HOOKS_", "HOOKS_DAEMON_"))
    }
    env["HOSTNAME"] = "pretooluse-fail-closed-fixture"
    env["CLAUDE_HOOKS_SOCKET_PATH"] = str(socket_path)
    env["CLAUDE_HOOKS_SOCKET_TIMEOUT"] = socket_timeout
    if relay_failure is not None:
        env["HOOKS_DAEMON_RELAY_FAILED"] = relay_failure
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
    parsed: dict[str, Any] = json.loads(result.stdout.strip())
    return parsed


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
        response = _send(project, hanging_socket, "PreToolUse", _recovery_input(project))
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso

    def test_a_compound_recovery_command_is_still_denied(
        self, project: Path, hanging_socket: Path
    ) -> None:
        """No compound commands: this must NOT ride along with the exemption."""
        compound_input = _recovery_input(project, "bin/hooks-daemon restart && rm -rf /")
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
        recovery_input = _recovery_input(project, ".claude/hooks-daemon/bin/hooks-daemon status")
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
        response = _send(project, connection_reset_socket, "PreToolUse", _recovery_input(project))
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
        response = _send(project, backlog_full_socket, "PreToolUse", _recovery_input(project))
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


@pytest.fixture
def nonexistent_socket() -> Iterator[Path]:
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


class TestDaemonNotReachableFailsClosedForPreToolUse:
    """Plan 00466 N24 review 3 MA4 (owner decision): 'the socket is missing'
    no longer means fail-open for PreToolUse -- it means the daemon could
    not be reached at all, and this project's install/CI story keeps
    ensure_daemon's auto-start ahead of every real call site, so this is
    the wedged/crashed/never-started shape, not the fresh-clone-before-
    install one (that stays fail-open, upstream of this transport, via
    emit_hook_error's own NOT_INSTALLED/VENV_MISSING branches)."""

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
        response = _send(project, nonexistent_socket, "PreToolUse", _recovery_input(project))
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


class TestUnclassifiedConnectErrorsFailClosedForPreToolUse:
    """Plan 00466 N24 review 4 R4-MA1: a connect() failure the transport's
    ``except`` clauses do not name explicitly must still DENY PreToolUse --
    the generic ``except Exception`` used to classify these under an
    ``error_type`` never in the old fail-closed allowlist, silently
    ALLOWing every later call once one of these fired (e.g. an agent's own
    ``chmod 000`` of the socket switching every subsequent PreToolUse to
    ALLOW)."""

    def test_not_a_directory_denies(self, project: Path, tmp_path: Path) -> None:
        """A path component that is a regular file, not a directory, makes
        ``connect()`` raise ``NotADirectoryError`` -- unclassified by any of
        init.sh's named ``except`` clauses."""
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        response = _send(project, blocker / "fake.sock", "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "denied for safety" in hso["permissionDecisionReason"]

    def test_not_a_directory_recovery_command_is_not_denied(
        self, project: Path, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "not-a-dir-2"
        blocker.write_text("x")
        response = _send(project, blocker / "fake.sock", "PreToolUse", _recovery_input(project))
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso

    def test_socket_path_over_the_sun_path_limit_denies(
        self, project: Path, tmp_path: Path
    ) -> None:
        """A path past AF_UNIX's ~108-byte ``sun_path`` cap makes ``connect()``
        raise a plain ``OSError`` (``ENAMETOOLONG``) -- also unclassified."""
        overlong = tmp_path / ("x" * 200) / "fake.sock"
        response = _send(project, overlong, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "denied for safety" in hso["permissionDecisionReason"]

    def test_not_a_directory_still_fails_open_for_a_non_pretooluse_event(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Only PreToolUse changed; every other event keeps the original
        fail-open `additionalContext` contract."""
        blocker = tmp_path / "not-a-dir-3"
        blocker.write_text("x")
        response = _send(project, blocker / "fake.sock", "PostToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso


class TestConnectionRefusedFailsClosedForPreToolUse:
    """Plan 00466 N24 review 3 MA4 follow-up: a socket FILE that exists but
    nothing is listening behind it is a distinct transport failure from
    ``socket_not_found`` (no file at all) -- ``connect()`` raises
    ``ConnectionRefusedError`` rather than ``FileNotFoundError`` -- and must
    DENY PreToolUse the same way. init.sh's ``connection_refused`` branch was
    added alongside ``socket_not_found`` in MA4 itself but, per that round's
    own handoff notes, never got its own dedicated end-to-end test; this is
    that test."""

    @pytest.fixture
    def refused_socket(self) -> Iterator[Path]:
        """A real AF_UNIX socket file that is bound but never ``listen()``s,
        so a client's ``connect()`` gets ``ECONNREFUSED`` immediately rather
        than queuing or timing out -- the daemon crashed/shut down after
        creating its socket file but before (or instead of) accepting
        connections on it, leaving the stale file behind."""
        short_dir = Path(tempfile.mkdtemp(prefix="hd-"))
        sock_path = short_dir / "fake.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        # Deliberately no listen()/accept(): an unbound-to-nothing socket
        # file refuses every connection attempt outright.
        try:
            yield sock_path
        finally:
            server.close()
            shutil.rmtree(short_dir, ignore_errors=True)

    def test_a_pretooluse_call_is_denied(self, project: Path, refused_socket: Path) -> None:
        response = _send(project, refused_socket, "PreToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "denied for safety" in hso["permissionDecisionReason"]

    def test_the_recovery_command_is_not_denied(self, project: Path, refused_socket: Path) -> None:
        response = _send(project, refused_socket, "PreToolUse", _recovery_input(project))
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso

    def test_still_fails_open_for_a_non_pretooluse_event(
        self, project: Path, refused_socket: Path
    ) -> None:
        """Only PreToolUse changed; every other event keeps the original
        fail-open `additionalContext` contract."""
        response = _send(project, refused_socket, "PostToolUse", _BASH_TOOL_INPUT)
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso


def _plant_launcher(directory: Path) -> Path:
    """Write an impostor ``bin/hooks-daemon`` under ``directory``."""
    planted = directory / "bin" / "hooks-daemon"
    planted.parent.mkdir(parents=True)
    planted.write_text("#!/bin/bash\necho planted\n")
    return planted


def _denied(response: dict[str, Any]) -> bool:
    return bool(response["hookSpecificOutput"].get("permissionDecision") == "deny")


class TestRecoveryCarveOutJudgesTheResolvedLauncher:
    """Plan 00466 N67: the carve-out exempts the launcher a command will RUN.

    A relative ``bin/hooks-daemon`` resolves against the Bash tool's working
    directory, the hook input's ``cwd``. Matching the command text alone let
    a launcher planted in any other directory run while every guard was
    down. Only a command that resolves to the project's own launcher is
    exempt, and anything that cannot be resolved is denied.
    """

    def test_a_launcher_planted_in_a_subdirectory_is_denied(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        sub = project / "sub"
        _plant_launcher(sub)
        response = _send(project, nonexistent_socket, "PreToolUse", _recovery_input(sub))
        assert _denied(response)

    def test_a_launcher_planted_outside_the_project_is_denied(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        _plant_launcher(elsewhere)
        response = _send(project, nonexistent_socket, "PreToolUse", _recovery_input(elsewhere))
        assert _denied(response)

    def test_the_long_spelling_planted_in_a_subdirectory_is_denied(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        sub = project / "sub"
        _plant_launcher(sub / ".claude" / "hooks-daemon")
        hook_input = _recovery_input(sub, ".claude/hooks-daemon/bin/hooks-daemon restart")
        response = _send(project, nonexistent_socket, "PreToolUse", hook_input)
        assert _denied(response)

    def test_a_missing_cwd_is_denied(self, project: Path, nonexistent_socket: Path) -> None:
        response = _send(project, nonexistent_socket, "PreToolUse", _recovery_input(None))
        assert _denied(response)

    @pytest.mark.parametrize("cwd", ["", ".", "sub", 7, None, ["/"]])
    def test_a_cwd_that_is_not_an_absolute_path_is_denied(
        self, project: Path, nonexistent_socket: Path, cwd: object
    ) -> None:
        hook_input = _recovery_input(None)
        hook_input["cwd"] = cwd
        response = _send(project, nonexistent_socket, "PreToolUse", hook_input)
        assert _denied(response)

    def test_a_project_without_the_launcher_is_denied(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        """Nothing to resolve to means nothing to exempt."""
        (project / "bin" / "hooks-daemon").unlink()
        response = _send(project, nonexistent_socket, "PreToolUse", _recovery_input(project))
        assert _denied(response)

    def test_a_directory_named_like_the_launcher_is_denied(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        launcher = project / "bin" / "hooks-daemon"
        launcher.unlink()
        launcher.mkdir()
        response = _send(project, nonexistent_socket, "PreToolUse", _recovery_input(project))
        assert _denied(response)

    def test_a_symlink_to_the_project_launcher_is_exempt(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        """What runs is judged, not how it is spelled: a link to the real
        launcher runs the real launcher, which anchors to its own location."""
        sub = project / "sub"
        (sub / "bin").mkdir(parents=True)
        (sub / "bin" / "hooks-daemon").symlink_to(project / "bin" / "hooks-daemon")
        response = _send(project, nonexistent_socket, "PreToolUse", _recovery_input(sub))
        assert not _denied(response)

    def test_a_cwd_that_links_to_the_project_root_is_exempt(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        link = tmp_path / "link-to-project"
        link.symlink_to(project)
        response = _send(project, nonexistent_socket, "PreToolUse", _recovery_input(link))
        assert not _denied(response)


@pytest.fixture
def undecodable_socket() -> Iterator[Path]:
    """Answers with bytes that are not UTF-8: the daemon was reached, and the
    client's decode raises an error none of its named clauses classify."""
    yield from _fake_server(respond=b"\xff\xfe\xfd\n")


def _reason(response: dict[str, Any]) -> str:
    hso = response["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    return str(hso["permissionDecisionReason"])


class TestDenyReasonNamesWhatHappened:
    """Plan 00466 N69: a fail-closed deny says whether the daemon was reached.

    "Reached" is true only once ``connect()`` has succeeded. A missing or
    refused socket, a full accept backlog and an unclassified connect error
    all fail before that, so each is "unreachable"; any failure after it,
    classified or not, is "reached".
    """

    def test_a_missing_socket_is_unreachable(self, project: Path, nonexistent_socket: Path) -> None:
        reason = _reason(_send(project, nonexistent_socket, "PreToolUse", _BASH_TOOL_INPUT))
        assert reason.startswith("Hooks daemon unreachable"), reason

    def test_a_refused_connection_is_unreachable(self, project: Path) -> None:
        short_dir = Path(tempfile.mkdtemp(prefix="hd-"))
        sock_path = short_dir / "fake.sock"
        bound = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound.bind(str(sock_path))
        try:
            reason = _reason(_send(project, sock_path, "PreToolUse", _BASH_TOOL_INPUT))
        finally:
            bound.close()
            shutil.rmtree(short_dir)
        assert reason.startswith("Hooks daemon unreachable"), reason

    def test_a_full_accept_backlog_is_unreachable(
        self, project: Path, backlog_full_socket: Path
    ) -> None:
        """The kernel refused the connection, so the daemon never saw it."""
        reason = _reason(_send(project, backlog_full_socket, "PreToolUse", _BASH_TOOL_INPUT))
        assert reason.startswith("Hooks daemon unreachable"), reason

    def test_an_unclassified_connect_error_is_unreachable_and_says_so(
        self, project: Path, tmp_path: Path
    ) -> None:
        """The deny's context must not reuse the fail-open wording: guards
        are not "inactive" (they are denying), and the Skill tool it names
        is itself a PreToolUse call denied the same way."""
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        response = _send(project, blocker / "fake.sock", "PreToolUse", _BASH_TOOL_INPUT)
        assert _reason(response).startswith("Hooks daemon unreachable")
        context = response["hookSpecificOutput"]["additionalContext"]
        assert "could not connect" in context
        assert "inactive" not in context
        assert "Skill tool" not in context

    def test_a_timeout_after_connecting_is_reached(
        self, project: Path, hanging_socket: Path
    ) -> None:
        reason = _reason(_send(project, hanging_socket, "PreToolUse", _BASH_TOOL_INPUT))
        assert reason.startswith("Hooks daemon reached"), reason

    def test_an_unclassified_error_after_connecting_is_reached(
        self, project: Path, undecodable_socket: Path
    ) -> None:
        reason = _reason(_send(project, undecodable_socket, "PreToolUse", _BASH_TOOL_INPUT))
        assert reason.startswith("Hooks daemon reached"), reason


_RELAY_FAILURE = "timeout: socket read: timed out"


class TestARelayHandOffIsJudgedWithoutAskingTheDaemonAgain:
    """Plan 00466 N126: hooks-relay hands a failed PreToolUse exchange to the
    forwarder with ``HOOKS_DAEMON_RELAY_FAILED`` set. The transport must not
    ask the wedged daemon again (``valid_empty_socket`` would ALLOW if it
    did), and must deny through the same recovery carve-out."""

    def test_an_ordinary_call_is_denied_without_contacting_the_daemon(
        self, project: Path, valid_empty_socket: Path
    ) -> None:
        response = _send(
            project,
            valid_empty_socket,
            "PreToolUse",
            _BASH_TOOL_INPUT,
            relay_failure=_RELAY_FAILURE,
        )
        reason = _reason(response)
        assert reason.startswith("Hooks daemon reached"), reason
        assert "relay_exchange_failed" in reason
        assert _RELAY_FAILURE in response["hookSpecificOutput"]["additionalContext"]

    def test_the_projects_own_restart_is_exempt(
        self, project: Path, valid_empty_socket: Path
    ) -> None:
        response = _send(
            project,
            valid_empty_socket,
            "PreToolUse",
            _recovery_input(project),
            relay_failure=_RELAY_FAILURE,
        )
        hso = response["hookSpecificOutput"]
        assert "permissionDecision" not in hso
        assert "relay_exchange_failed" in hso["additionalContext"]

    def test_a_planted_launcher_is_denied(
        self, project: Path, tmp_path: Path, valid_empty_socket: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        _plant_launcher(elsewhere)
        response = _send(
            project,
            valid_empty_socket,
            "PreToolUse",
            _recovery_input(elsewhere),
            relay_failure=_RELAY_FAILURE,
        )
        assert _denied(response)

    def test_another_event_ignores_it(self, project: Path, valid_empty_socket: Path) -> None:
        """The relay hands over PreToolUse only; any other event still asks
        the daemon."""
        response = _send(
            project,
            valid_empty_socket,
            "PostToolUse",
            _BASH_TOOL_INPUT,
            relay_failure=_RELAY_FAILURE,
        )
        assert response == {}

    def test_it_is_not_inherited_past_init_sh(self, project: Path) -> None:
        """Captured and unset at source time, so a daemon this hook starts
        never runs with it."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_")}
        env["HOOKS_DAEMON_RELAY_FAILED"] = _RELAY_FAILURE
        script = 'source .claude/init.sh; printf "%s" "${HOOKS_DAEMON_RELAY_FAILED-unset}"'
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
        assert result.stdout == "unset"


def _run_script(
    project: Path,
    script: str,
    hook_input: dict[str, Any] | str | None,
    *,
    socket_path: Path,
    relay_failure: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``script`` in ``project`` with ``hook_input`` on stdin (a string as it is)."""
    return subprocess.run(
        [BASH, "-c", script],
        cwd=project,
        env=_script_env(socket_path, relay_failure=relay_failure, extra_env=extra_env),
        input=_stdin_text(hook_input),
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )


def _script_env(
    socket_path: Path,
    *,
    relay_failure: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """The environment a hook script runs in here: no daemon or CI settings
    of the caller's, and ``socket_path`` as the daemon's socket."""
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_HOOKS_", "HOOKS_DAEMON_"))
    }
    for ci_var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "TF_BUILD"):
        env.pop(ci_var, None)
    env["HOSTNAME"] = "pretooluse-fail-closed-fixture"
    env["CLAUDE_HOOKS_SOCKET_PATH"] = str(socket_path)
    env["CLAUDE_HOOKS_SOCKET_TIMEOUT"] = _FAST_TIMEOUT
    if relay_failure is not None:
        env["HOOKS_DAEMON_RELAY_FAILED"] = relay_failure
    if extra_env:
        env.update(extra_env)
    return env


def _stdin_text(hook_input: dict[str, Any] | str | None) -> str:
    if hook_input is None:
        return ""
    if isinstance(hook_input, str):
        return hook_input
    return json.dumps(hook_input)


def _verdict(result: subprocess.CompletedProcess[str]) -> str:
    """``deny`` or ``no-decision`` for a hook's stdout; anything else fails."""
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout.strip())
    hso = parsed.get("hookSpecificOutput", {})
    if hso.get("permissionDecision") == "deny" or parsed.get("decision") == "deny":
        return "deny"
    assert set(parsed) == {"hookSpecificOutput"}, parsed
    assert "permissionDecision" not in hso, parsed
    return "no-decision"


class TestRecoveryCommandTextMatchesExactly:
    """Plan 00466 N67 round 2 (S1): only spaces and tabs may pad the command.

    ``str.strip()`` also removes vertical tab, form feed, the file/group/
    record/unit separators, NEL and the Unicode line separators, so a
    command with one of them appended matched the exemption while bash ran
    the launcher with a different argument.
    """

    @pytest.mark.parametrize(
        "extra",
        ["\x1c", "\x1d", "\x1e", "\x1f", "\x0b", "\x0c", "\x85", "\N{LINE SEPARATOR}", "\n", "\r"],
    )
    def test_a_control_character_appended_is_denied(
        self, project: Path, nonexistent_socket: Path, extra: str
    ) -> None:
        hook_input = _recovery_input(project, "bin/hooks-daemon restart" + extra)
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    @pytest.mark.parametrize("extra", ["\x1c", "\n", "\x0b"])
    def test_a_control_character_prepended_is_denied(
        self, project: Path, nonexistent_socket: Path, extra: str
    ) -> None:
        hook_input = _recovery_input(project, extra + "bin/hooks-daemon restart")
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_spaces_and_tabs_around_it_are_still_exempt(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        hook_input = _recovery_input(project, " \t bin/hooks-daemon restart \t ")
        assert not _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))


class TestRepairIsARecoveryCommand:
    """Plan 00466 round 2 (coordinator ruling): ``repair`` rebuilds a broken
    venv, which ``restart`` cannot fix, so it joins the recovery set under
    the same exact-match and launcher rule."""

    @pytest.mark.parametrize("launcher", _RECOVERY_LAUNCHERS)
    def test_the_projects_own_repair_is_exempt(
        self, project: Path, nonexistent_socket: Path, launcher: str
    ) -> None:
        hook_input = _recovery_input(project, f"{launcher} repair")
        assert not _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_a_repair_that_runs_a_planted_launcher_is_denied(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        _plant_launcher(elsewhere)
        hook_input = _recovery_input(elsewhere, "bin/hooks-daemon repair")
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_a_repair_with_arguments_is_denied(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        hook_input = _recovery_input(project, "bin/hooks-daemon repair --force")
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))


class TestTheAbsoluteLauncherIsExemptFromAnyDirectory:
    """Plan 00466 round 2 (m1): a session whose Bash tool sits in a worktree
    could not recover, because every exempt spelling was relative. The
    project's own launcher by absolute path is exempt from any ``cwd``, and
    every deny names that command."""

    @pytest.mark.parametrize("launcher", _RECOVERY_LAUNCHERS)
    def test_the_absolute_launcher_is_exempt_from_another_directory(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path, launcher: str
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        _plant_launcher(elsewhere)
        hook_input = _recovery_input(elsewhere, f"{project / launcher} restart")
        assert not _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_the_absolute_launcher_is_exempt_with_no_cwd(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        """The absolute path runs the same file whatever the directory."""
        hook_input = _recovery_input(None, f"{project / 'bin' / 'hooks-daemon'} status")
        assert not _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_another_checkouts_absolute_launcher_is_denied(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        other = _make_project(tmp_path / "other")
        hook_input = _recovery_input(project, f"{other / 'bin' / 'hooks-daemon'} restart")
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_an_absolute_path_that_is_not_the_launcher_is_denied(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        (project / "bin" / "hooks-daemon").unlink()
        hook_input = _recovery_input(project, f"{project / 'bin' / 'hooks-daemon'} restart")
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_a_path_that_needs_quoting_is_exempt_only_quoted(
        self, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """Unquoted, bash would split the path at the space and run another
        program, so only the quoted spelling is the launcher."""
        spaced = _make_project(tmp_path / "with space" / "proj")
        launcher = spaced / "bin" / "hooks-daemon"
        script = "source .claude/init.sh; send_request_stdin PreToolUse"
        unquoted = _recovery_input(tmp_path, f"{launcher} restart")
        quoted = _recovery_input(tmp_path, f"'{launcher}' restart")
        unquoted_result = _run_script(spaced, script, unquoted, socket_path=nonexistent_socket)
        quoted_result = _run_script(spaced, script, quoted, socket_path=nonexistent_socket)
        assert _verdict(unquoted_result) == "deny"
        assert _verdict(quoted_result) == "no-decision"
        context = json.loads(unquoted_result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert f"'{spaced / _INSTALL_LAUNCHER}' restart" in context, context

    def test_the_transport_deny_names_the_absolute_command(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        response = _send(project, nonexistent_socket, "PreToolUse", _BASH_TOOL_INPUT)
        context = response["hookSpecificOutput"]["additionalContext"]
        assert f"{project / _INSTALL_LAUNCHER} restart" in context, context

    def test_the_timeout_deny_names_the_absolute_command(
        self, project: Path, hanging_socket: Path
    ) -> None:
        response = _send(project, hanging_socket, "PreToolUse", _BASH_TOOL_INPUT)
        context = response["hookSpecificOutput"]["additionalContext"]
        assert f"{project / _INSTALL_LAUNCHER} restart" in context, context

    def test_the_startup_failure_deny_names_the_absolute_command(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        result = _run_script(
            project,
            "source .claude/init.sh; emit_hook_error PreToolUse daemon_startup_failed x",
            _BASH_TOOL_INPUT,
            socket_path=nonexistent_socket,
        )
        assert _verdict(result) == "deny"
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert f"{project / _INSTALL_LAUNCHER} restart" in reason, reason

    def test_a_client_project_names_its_only_launcher(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        """A client has no ``bin/hooks-daemon``; the deny names the one it has."""
        (project / "bin" / "hooks-daemon").unlink()
        response = _send(project, nonexistent_socket, "PreToolUse", _BASH_TOOL_INPUT)
        context = response["hookSpecificOutput"]["additionalContext"]
        long_form = project / ".claude" / "hooks-daemon" / "bin" / "hooks-daemon"
        assert f"{long_form} restart" in context, context


def _plant_unrelated_root_launcher(project: Path) -> Path:
    """Replace the root ``bin/hooks-daemon`` link with a script of the project's own."""
    unrelated = project / _ROOT_LAUNCHER
    unrelated.unlink()
    unrelated.write_text("#!/bin/bash\necho the project's own tool\n")
    return unrelated


def _make_self_install(root: Path) -> Path:
    """The daemon's own repository: the install IS the project root.

    ``bin/hooks-daemon`` is the launcher, and the clone-path spelling links
    to it, as this repository's own checkout does.
    """
    project = _make_project(root)
    (project / ".claude" / "hooks-daemon.env").write_text('HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"\n')
    (project / _ROOT_LAUNCHER).unlink()
    (project / _INSTALL_LAUNCHER).rename(project / _ROOT_LAUNCHER)
    (project / _INSTALL_LAUNCHER).symlink_to(project / _ROOT_LAUNCHER)
    return project


class TestOnlyThisInstallsLauncherIsExempt:
    """Plan 00466 round 3 (m-A): the carve-out exempts the launcher that runs
    THIS daemon install, and every deny names it first, in ``cli.py``'s order
    (the clone's ``.claude/hooks-daemon/bin/hooks-daemon``, then the root
    ``bin/hooks-daemon``). A client project's own unrelated
    ``bin/hooks-daemon`` was exempt and was the command every deny named."""

    @pytest.mark.parametrize("absolute", [False, True])
    def test_an_unrelated_root_launcher_is_denied(
        self, project: Path, nonexistent_socket: Path, absolute: bool
    ) -> None:
        unrelated = _plant_unrelated_root_launcher(project)
        command = f"{unrelated} restart" if absolute else f"{_ROOT_LAUNCHER} restart"
        hook_input = _recovery_input(project, command)
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_an_unrelated_root_launcher_is_denied_on_a_hand_off(
        self, project: Path, valid_empty_socket: Path
    ) -> None:
        _plant_unrelated_root_launcher(project)
        response = _send(
            project,
            valid_empty_socket,
            "PreToolUse",
            _recovery_input(project),
            relay_failure=_RELAY_FAILURE,
        )
        assert _denied(response)

    def test_the_installs_launcher_is_still_exempt_beside_it(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        _plant_unrelated_root_launcher(project)
        hook_input = _recovery_input(project, f"{_INSTALL_LAUNCHER} restart")
        assert not _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_the_deny_names_the_installs_launcher_not_the_unrelated_one(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        unrelated = _plant_unrelated_root_launcher(project)
        response = _send(project, nonexistent_socket, "PreToolUse", _BASH_TOOL_INPUT)
        context = response["hookSpecificOutput"]["additionalContext"]
        assert f"{project / _INSTALL_LAUNCHER} restart" in context, context
        assert f"{unrelated} restart" not in context, context

    def test_the_startup_deny_never_names_an_unrelated_launcher(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        """With the clone's launcher gone, the deny names where this install's
        launcher belongs, never the project's own script."""
        unrelated = _plant_unrelated_root_launcher(project)
        (project / _INSTALL_LAUNCHER).unlink()
        result = _run_script(
            project,
            "source .claude/init.sh; emit_hook_error PreToolUse daemon_startup_failed x",
            _BASH_TOOL_INPUT,
            socket_path=nonexistent_socket,
        )
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert f"{project / _INSTALL_LAUNCHER} restart" in reason, reason
        assert f"{unrelated} restart" not in reason, reason

    @pytest.mark.parametrize("launcher", _RECOVERY_LAUNCHERS)
    def test_a_self_install_exempts_both_spellings(
        self, tmp_path: Path, nonexistent_socket: Path, launcher: str
    ) -> None:
        project = _make_self_install(tmp_path / "self")
        hook_input = _recovery_input(project, f"{launcher} restart")
        assert not _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_a_self_install_names_the_clone_spelling_first(
        self, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        project = _make_self_install(tmp_path / "self")
        response = _send(project, nonexistent_socket, "PreToolUse", _BASH_TOOL_INPUT)
        context = response["hookSpecificOutput"]["additionalContext"]
        assert f"{project / _INSTALL_LAUNCHER} restart" in context, context


class TestADaemonRootOfAnotherProjectIsUnknown:
    """Plan 00466 round 4 (P3-1): ``HOOKS_DAEMON_ROOT_DIR`` can be inherited
    from whatever started Claude Code, or set in ``.claude/hooks-daemon.env``.
    The launcher manages the project it derives from its own location, so a
    root that names another project's install recovers that project, never
    this one. Such a root is unknown: nothing is exempt, and the deny says
    why and what a human can run."""

    def _point_root_elsewhere(self, project: Path, tmp_path: Path) -> Path:
        other = _make_project(tmp_path / "other")
        (project / ".claude" / "hooks-daemon.env").write_text(
            f'HOOKS_DAEMON_ROOT_DIR="{other / ".claude" / "hooks-daemon"}"\n'
        )
        return other

    def test_the_other_installs_launcher_is_denied(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        other = self._point_root_elsewhere(project, tmp_path)
        hook_input = _recovery_input(project, f"{other / _INSTALL_LAUNCHER} restart")
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    @pytest.mark.parametrize("launcher", _RECOVERY_LAUNCHERS)
    def test_this_projects_launcher_is_denied_too(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path, launcher: str
    ) -> None:
        """Fail closed: which launcher recovers this project is unknown."""
        self._point_root_elsewhere(project, tmp_path)
        hook_input = _recovery_input(project, f"{launcher} restart")
        assert _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))

    def test_the_deny_names_the_mismatch_and_a_human_command(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        other = self._point_root_elsewhere(project, tmp_path)
        response = _send(project, nonexistent_socket, "PreToolUse", _BASH_TOOL_INPUT)
        context = response["hookSpecificOutput"]["additionalContext"]
        assert "no daemon command is exempt" in context, context
        assert f"({other / '.claude' / 'hooks-daemon'})" in context, context
        assert f"! {project / _INSTALL_LAUNCHER} restart" in context, context
        assert f"run exactly {other / _INSTALL_LAUNCHER}" not in context, context

    def test_the_startup_deny_names_the_mismatch(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        self._point_root_elsewhere(project, tmp_path)
        result = _run_script(
            project,
            "source .claude/init.sh; emit_hook_error PreToolUse daemon_startup_failed x",
            _BASH_TOOL_INPUT,
            socket_path=nonexistent_socket,
        )
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert "no daemon command is exempt" in reason, reason

    def test_a_root_inherited_from_the_environment_is_checked_too(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        other = _make_project(tmp_path / "other")
        (project / ".claude" / "hooks-daemon.env").unlink()
        hook_input = _recovery_input(project, f"{other / _INSTALL_LAUNCHER} restart")
        result = _run_script(
            project,
            "source .claude/init.sh; send_request_stdin PreToolUse",
            hook_input,
            socket_path=nonexistent_socket,
            extra_env={"HOOKS_DAEMON_ROOT_DIR": str(other / ".claude" / "hooks-daemon")},
        )
        assert _verdict(result) == "deny"

    def test_a_root_that_links_to_this_install_is_still_exempt(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        link = tmp_path / "linked-root"
        link.symlink_to(project / ".claude" / "hooks-daemon")
        (project / ".claude" / "hooks-daemon.env").write_text(f'HOOKS_DAEMON_ROOT_DIR="{link}"\n')
        hook_input = _recovery_input(project, f"{_INSTALL_LAUNCHER} restart")
        assert not _denied(_send(project, nonexistent_socket, "PreToolUse", hook_input))


#: The real PreToolUse forwarder's body after it sources ``init.sh``.
_FORWARDER_BODY = """
if ! ensure_daemon; then
    emit_hook_error "PreToolUse" "daemon_startup_failed" "daemon failed to start"
    exit 0
fi
send_request_stdin "PreToolUse"
"""

#: Forces ensure_daemon's daemon-down path without a real venv: nothing is
#: running and a start fails. Each state below then adds its own diagnosis.
_DAEMON_DOWN = """
is_daemon_running() { return 1; }
start_daemon() { : > "$START_MARKER"; return 1; }
_is_ci_environment() { return 1; }
_is_ci_enforced() { return 1; }
_detect_stale_clone() { return 1; }
_is_daemon_installed() { return 1; }
_daemon_clone_present() { return 1; }
_daemon_orphan_venv_present() { return 1; }
"""

#: Every fail-open (or differently shaped) state ensure_daemon can diagnose.
_DAEMON_DOWN_STATES = {
    "not_installed": "",
    "venv_missing": "_daemon_clone_present() { return 0; }\n_clone_version() { return 1; }",
    "version_mismatch": (
        "_detect_stale_clone() { _HOOKS_DAEMON_CLONE_VERSION=1.0.0; "
        "_HOOKS_DAEMON_TRACKED_VERSION=2.0.0; return 0; }"
    ),
    "ci_passthrough": "_is_ci_environment() { return 0; }",
    "ci_passthrough_flag": (
        '_is_ci_environment() { return 0; }\n: > "$START_MARKER.flag"\n'
        '_passthrough_flag_path() { echo "$START_MARKER.flag"; }'
    ),
    "ci_enforced": "_is_ci_enforced() { return 0; }",
    "installed_but_down": "_is_daemon_installed() { return 0; }",
}


class TestARelayHandOffReachesOnlyTheCarveOut:
    """Plan 00466 N126 round 2 (F1): the relay hands a failed call to the
    WHOLE forwarder, which runs ``ensure_daemon`` first. Every fail-open
    state that can diagnose (not installed, venv missing, version mismatch,
    CI passthrough) allowed the in-flight call the relay had already failed.
    Under a hand-off the only outcomes are the carve-out's allow and a deny,
    and the daemon is neither started nor asked again (``valid_empty_socket``
    would allow if it were)."""

    def _forward(
        self, project: Path, socket_path: Path, state: str, hook_input: dict[str, Any]
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        marker = project / "start-attempted"
        script = (
            "set -euo pipefail\nsource .claude/init.sh\n"
            + _DAEMON_DOWN
            + _DAEMON_DOWN_STATES[state]
            + _FORWARDER_BODY
        )
        result = _run_script(
            project,
            script,
            hook_input,
            socket_path=socket_path,
            relay_failure=_RELAY_FAILURE,
            extra_env={"START_MARKER": str(marker)},
        )
        return result, marker

    @pytest.mark.parametrize("state", sorted(_DAEMON_DOWN_STATES))
    def test_an_ordinary_call_is_denied(
        self, project: Path, valid_empty_socket: Path, state: str
    ) -> None:
        result, _ = self._forward(project, valid_empty_socket, state, _BASH_TOOL_INPUT)
        assert _verdict(result) == "deny", result.stdout

    @pytest.mark.parametrize("state", sorted(_DAEMON_DOWN_STATES))
    def test_the_projects_own_restart_is_exempt(
        self, project: Path, valid_empty_socket: Path, state: str
    ) -> None:
        result, _ = self._forward(project, valid_empty_socket, state, _recovery_input(project))
        assert _verdict(result) == "no-decision", result.stdout

    @pytest.mark.parametrize("state", sorted(_DAEMON_DOWN_STATES))
    def test_a_planted_launcher_is_denied(
        self, project: Path, tmp_path: Path, valid_empty_socket: Path, state: str
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        _plant_launcher(elsewhere)
        result, _ = self._forward(project, valid_empty_socket, state, _recovery_input(elsewhere))
        assert _verdict(result) == "deny", result.stdout

    def test_the_daemon_is_not_started(self, project: Path, valid_empty_socket: Path) -> None:
        """A start could take the whole hand-off budget; the next call,
        which the relay cannot connect for, starts it as usual."""
        result, marker = self._forward(
            project, valid_empty_socket, "not_installed", _BASH_TOOL_INPUT
        )
        assert _verdict(result) == "deny"
        assert not marker.exists()

    def test_an_unnamed_event_is_judged_as_the_pretooluse_call_it_is(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        """init.sh's source-time guards name no event. A hand-off is always a
        PreToolUse call, so their fail-open answer must not reach it."""
        script = "source .claude/init.sh; emit_hook_error '' hooks_daemon_repo_detected x"
        ordinary = _run_script(
            project,
            script,
            _BASH_TOOL_INPUT,
            socket_path=nonexistent_socket,
            relay_failure=_RELAY_FAILURE,
        )
        restart = _run_script(
            project,
            script,
            _recovery_input(project),
            socket_path=nonexistent_socket,
            relay_failure=_RELAY_FAILURE,
        )
        assert _verdict(ordinary) == "deny"
        assert _verdict(restart) == "no-decision"


class TestExportedFunctionsCarryTheirOwnRecoverySource:
    """Plan 00466 round 2 (m3): ``send_request_stdin`` and
    ``_hooks_daemon_stdin_is_recovery_command`` are exported, and a child
    bash inherits them without sourcing ``init.sh``. They read the recovery
    source from a variable that was not exported, so in that child the
    transport raised NameError and wrote no JSON at all."""

    def test_a_child_shell_applies_the_carve_out(
        self, project: Path, nonexistent_socket: Path
    ) -> None:
        script = "source .claude/init.sh; bash -c 'send_request_stdin PreToolUse'"
        restart = _run_script(
            project, script, _recovery_input(project), socket_path=nonexistent_socket
        )
        ordinary = _run_script(project, script, _BASH_TOOL_INPUT, socket_path=nonexistent_socket)
        assert _verdict(restart) == "no-decision"
        assert _verdict(ordinary) == "deny"

    def test_a_child_shell_judges_stdin(self, project: Path, nonexistent_socket: Path) -> None:
        script = (
            "source .claude/init.sh; "
            "bash -c 'if _hooks_daemon_stdin_is_recovery_command; "
            "then echo rc=0; else echo rc=1; fi'"
        )
        result = _run_script(
            project, script, _recovery_input(project), socket_path=nonexistent_socket
        )
        assert result.stdout.strip() == "rc=0", result.stderr

    def test_a_child_shell_judges_the_pid_file(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """``is_daemon_running`` is exported, and so must be all it calls."""
        pid_path = tmp_path / "daemon.pid"
        script = (
            "source .claude/init.sh; "
            "bash -c 'if is_daemon_running; then echo rc=0; else echo rc=$?; fi'"
        )
        with daemon_like_process(project) as pid:
            pid_path.write_text(str(pid))
            result = _run_script(
                project,
                script,
                None,
                socket_path=nonexistent_socket,
                extra_env={"CLAUDE_HOOKS_PID_PATH": str(pid_path)},
            )
        assert result.stdout.strip() == "rc=0", result.stderr

    def test_the_daemon_launch_does_not_inherit_hook_state(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """What the hook carries for itself stays out of the daemon it starts."""
        env_dump = tmp_path / "daemon-env.txt"
        fake_python = tmp_path / "fake-python"
        fake_python.write_text(f'#!/bin/bash\nenv > "{env_dump}"\n')
        fake_python.chmod(0o755)
        script = (
            "source .claude/init.sh\n"
            "validate_venv() { return 0; }\n"
            f"PYTHON_CMD={fake_python}\n"
            "DAEMON_STARTUP_TIMEOUT=1\n"
            "if start_daemon; then echo rc=0; else echo rc=1; fi\n"
        )
        result = _run_script(
            project,
            script,
            None,
            socket_path=nonexistent_socket,
            relay_failure=_RELAY_FAILURE,
        )
        assert "rc=1" in result.stdout, result.stderr
        daemon_env = env_dump.read_text()
        names = {line.split("=", 1)[0] for line in daemon_env.splitlines()}
        assert not {"BASH_FUNC__hooks_daemon_recovery_py%%", "_hooks_daemon_recovery_py"} & names
        assert "def _is_daemon_recovery_command" not in daemon_env
        assert "HOOKS_DAEMON_RELAY_FAILED" not in names
        assert _RELAY_FAILURE not in daemon_env


class TestIsDaemonRunningRemovesOnlyItsOwnStalePidFile:
    """Plan 00466 round 2 (S2): ``is_daemon_running`` removed the PID file
    whenever its pid could not be signalled, even if a successor had written
    its own pid there in the meantime, orphaning that live daemon."""

    #: A pid no process holds: the highest free one below the kernel's limit.
    _UNREAL_PID = next(
        pid for pid in range(PID_MAX_LIMIT - 1, 1, -1) if not Path(f"/proc/{pid}").exists()
    )

    def _probe(
        self, project: Path, pid_path: Path, socket_path: Path, prelude: str = ""
    ) -> subprocess.CompletedProcess[str]:
        """``is_daemon_running``'s status, with the daemon's helpers run by
        this test's own interpreter (the fixture project has no venv)."""
        script = (
            f"source .claude/init.sh\nPYTHON_CMD={sys.executable}\n{prelude}\n"
            "if is_daemon_running; then echo rc=0; else echo rc=$?; fi\n"
        )
        return _run_script(
            project,
            script,
            None,
            socket_path=socket_path,
            extra_env={"CLAUDE_HOOKS_PID_PATH": str(pid_path)},
        )

    @staticmethod
    def _eperm_prelude() -> str:
        """Root may signal anything, so ``kill -0`` is shadowed with the
        failure the builtin reports for EPERM."""
        return (
            'kill() { if [[ "$1" == "-0" ]]; then '
            f'{_kill_failure_message(errno.EPERM)} return 1; fi; builtin kill "$@"; }}'
        )

    def test_a_stale_pid_file_is_removed(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(self._UNREAL_PID))
        result = self._probe(project, pid_path, nonexistent_socket)
        assert "rc=1" in result.stdout, result.stderr
        assert not pid_path.exists()

    def test_a_stale_pid_file_is_removed_only_through_the_start_lock(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """Plan 00466 round 4 (Sh-A): a daemon start writes its pid under the
        start lock, so the removal takes it too. A lock that cannot be opened
        (here a planted symlink, refused) leaves the file."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(self._UNREAL_PID))
        target = tmp_path / "planted-target"
        Path(f"{nonexistent_socket}.start.lock").symlink_to(target)
        result = self._probe(project, pid_path, nonexistent_socket)
        assert "rc=1" in result.stdout, result.stderr
        assert pid_path.read_text() == str(self._UNREAL_PID)
        assert not target.exists()

    @pytest.mark.parametrize("text", ["0", "-1", "1", "", "007", "junk", str(PID_MAX_LIMIT + 1)])
    def test_a_corrupt_pid_file_is_never_running_and_is_removed(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path, text: str
    ) -> None:
        """Plan 00466 round 4 (Sh-B): ``kill -0 0`` probes this shell's own
        process group and succeeds, and pid 1 is init, so a file holding
        either read as a daemon running for ever."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(text)
        result = self._probe(project, pid_path, nonexistent_socket)
        assert "rc=1" in result.stdout, result.stderr
        assert not pid_path.exists()

    def test_a_successors_pid_file_is_left_alone(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """The successor writes its pid while the stale one is being probed."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(self._UNREAL_PID))
        successor = str(os.getpid())
        # Shadows the builtin for signal 0 only: the probe of the stale pid
        # is where a successor's write lands. The stale pid really is gone,
        # so the failure is the one the builtin reports for it.
        prelude = (
            'kill() { if [[ "$1" == "-0" ]]; then '
            f'printf %s {successor} > "$PID_PATH"; '
            f'{_kill_failure_message(errno.ESRCH)} return 1; fi; builtin kill "$@"; }}'
        )
        result = self._probe(project, pid_path, nonexistent_socket, prelude)
        assert "rc=1" in result.stdout, result.stderr
        assert pid_path.read_text() == successor

    def test_a_pid_it_may_not_signal_is_unknown_and_keeps_its_file(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """Plan 00466 N139, round 4 (N139-A): ``kill -0`` on another user's
        process fails with EPERM. The process exists, so its PID file stays,
        but nothing proves it is this daemon: the answer is unknown (2)."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(self._UNREAL_PID))
        result = self._probe(project, pid_path, nonexistent_socket, self._eperm_prelude())
        assert "rc=2" in result.stdout, result.stderr
        assert pid_path.read_text() == str(self._UNREAL_PID)

    def test_a_pid_it_may_not_signal_runs_when_the_socket_answers(
        self, project: Path, tmp_path: Path
    ) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(self._UNREAL_PID))
        socket_dir = Path(tempfile.mkdtemp(prefix="hd-live-"))
        try:
            with answering_daemon_socket(socket_dir / "daemon.sock", project, self._UNREAL_PID):
                result = self._probe(
                    project, pid_path, socket_dir / "daemon.sock", self._eperm_prelude()
                )
        finally:
            shutil.rmtree(socket_dir)
        assert "rc=0" in result.stdout, result.stderr

    @pytest.mark.parametrize("answers_as", ["nothing", "another project"])
    def test_a_socket_proves_only_an_answer_as_this_projects_daemon(
        self, project: Path, tmp_path: Path, answers_as: str
    ) -> None:
        """Round 6 (Sh-2): any listener accepted the probe, so whoever bound
        the path first (another user can, under the /tmp fallback) proved a
        pid it may not signal to be this daemon."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(self._UNREAL_PID))
        socket_dir = Path(tempfile.mkdtemp(prefix="hd-live-"))
        socket_path = socket_dir / "daemon.sock"
        try:
            with contextlib.ExitStack() as stack:
                if answers_as == "nothing":
                    listener = stack.enter_context(socket.socket(socket.AF_UNIX))
                    listener.bind(str(socket_path))
                    listener.listen(1)
                else:
                    other = _make_project(tmp_path / "other")
                    stack.enter_context(
                        answering_daemon_socket(socket_path, other, self._UNREAL_PID)
                    )
                result = self._probe(project, pid_path, socket_path, self._eperm_prelude())
        finally:
            shutil.rmtree(socket_dir)
        assert "rc=2" in result.stdout, result.stderr

    @staticmethod
    def _fake_procfs(tmp_path: Path, pid: int, uid: int) -> Path:
        """A procfs root holding ``pid``'s real command line and a status
        naming ``uid`` as its owner: root may signal every process, so only
        a faked owner can be another user's here."""
        procfs = tmp_path / "procfs"
        (procfs / str(pid)).mkdir(parents=True)
        (procfs / str(pid) / "cmdline").write_bytes(Path(f"/proc/{pid}/cmdline").read_bytes())
        (procfs / str(pid) / "status").write_text(
            f"Name:\tpython\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nGid:\t0\t0\t0\t0\n"
        )
        return procfs

    @pytest.mark.parametrize(
        ("owner", "expected"), [("this user", "rc=0"), ("another user", "rc=2")]
    )
    def test_a_command_line_proves_only_a_process_this_user_owns(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path, owner: str, expected: str
    ) -> None:
        """Round 6 (P5-1, Sh-G): the command-line proof was reached through
        ``kill -0``, and root may signal any process, so another user's
        process naming this project in its arguments was proven. The owner's
        uid decides now; the helper (``/bin/false``) proves nothing here."""
        uid = os.geteuid() if owner == "this user" else os.geteuid() + 4242
        with daemon_like_process(project) as pid:
            pid_path = tmp_path / "daemon.pid"
            pid_path.write_text(str(pid))
            prelude = (
                f"_HOOKS_DAEMON_PROCFS={self._fake_procfs(tmp_path, pid, uid)}\n"
                "PYTHON_CMD=/bin/false"
            )
            result = self._probe(project, pid_path, nonexistent_socket, prelude)
        assert expected in result.stdout, result.stderr

    def test_a_command_line_never_proves_a_pid_it_may_not_signal(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """Round 5 (P4-2): another user's process can name this project in
        its arguments, so for a pid this user may not signal only the socket
        answering proves it. The bash side never reads that command line; the
        helper is ``/bin/false`` here, and its own refusal is
        ``TestPidIsThisProjectsDaemon`` (root may signal anything, so no real
        process here can give the helper EPERM)."""
        with daemon_like_process(project) as pid:
            pid_path = tmp_path / "daemon.pid"
            pid_path.write_text(str(pid))
            prelude = self._eperm_prelude() + "\nPYTHON_CMD=/bin/false"
            result = self._probe(project, pid_path, nonexistent_socket, prelude)
        assert "rc=2" in result.stdout, result.stderr
        assert pid_path.read_text() == str(pid)

    def test_a_live_pid_that_is_not_this_daemon_is_unknown(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """Round 5 (Sh-D): ``kill -0`` succeeding proves a process, and after
        a reboot a stale file's pid can be any process of this user's. It
        read as running, so no start was tried and every call was denied."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(os.getpid()))
        result = self._probe(project, pid_path, nonexistent_socket)
        assert "rc=2" in result.stdout, result.stderr
        assert pid_path.read_text() == str(os.getpid())

    def test_its_own_command_line_proves_a_pid_without_the_helper(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """The hot path: a daemon launched by ``start_daemon`` is proven from
        its command line, without the half-second venv helper (here a
        ``PYTHON_CMD`` that always fails)."""
        with daemon_like_process(project) as pid:
            pid_path = tmp_path / "daemon.pid"
            pid_path.write_text(str(pid))
            result = self._probe(project, pid_path, nonexistent_socket, "PYTHON_CMD=/bin/false")
        assert "rc=0" in result.stdout, result.stderr

    def test_an_argument_holding_a_launch_across_newlines_is_not_one(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """Round 6 (R5-2): procfs's arguments were joined with newlines, so
        one argument holding a launch split by newlines read as that launch,
        which ``process_verification`` rejects. This process's arguments
        really are that: the helper (``/bin/false``) proves nothing here."""
        smuggled = "\n".join(["x", "-m", _CLI_MODULE, "--project-root", str(project), "start"])
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.read()", smuggled],
            stdin=subprocess.PIPE,
        )
        try:
            pid_path = tmp_path / "daemon.pid"
            pid_path.write_text(str(process.pid))
            result = self._probe(project, pid_path, nonexistent_socket, "PYTHON_CMD=/bin/false")
        finally:
            assert process.stdin is not None
            process.stdin.close()
            process.wait(timeout=Timeout.REQUEST_LONG)
        assert "rc=2" in result.stdout, result.stderr

    def test_another_projects_daemon_of_this_user_is_unknown(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        with daemon_like_process(_make_project(tmp_path / "other")) as pid:
            pid_path = tmp_path / "daemon.pid"
            pid_path.write_text(str(pid))
            result = self._probe(project, pid_path, nonexistent_socket)
        assert "rc=2" in result.stdout, result.stderr

    def test_the_helper_runs_only_under_this_installs_root(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Round 5 (Sh-F): the helper runs the venv under
        ``HOOKS_DAEMON_ROOT_DIR``, which is trusted only when it is an install
        of this project (P3-1). A root of another project's proves nothing,
        even with this daemon's socket answering."""
        other = _make_project(tmp_path / "other")
        (project / ".claude" / "hooks-daemon.env").write_text(
            f'HOOKS_DAEMON_ROOT_DIR="{other / ".claude" / "hooks-daemon"}"\n'
        )
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(self._UNREAL_PID))
        socket_dir = Path(tempfile.mkdtemp(prefix="hd-live-"))
        try:
            with answering_daemon_socket(socket_dir / "daemon.sock", project, self._UNREAL_PID):
                result = self._probe(
                    project, pid_path, socket_dir / "daemon.sock", self._eperm_prelude()
                )
        finally:
            shutil.rmtree(socket_dir)
        assert "rc=2" in result.stdout, result.stderr

    def test_a_pid_it_may_not_signal_does_not_stop_an_auto_start(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """Round 4 (N139-A): the hook started no daemon while the stale PID
        file named another user's process, and every event lost its guards
        until someone ran restart. ``cli start`` decides, under its REUSE gate."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(self._UNREAL_PID))
        marker = tmp_path / "start-attempted"
        prelude = (
            self._eperm_prelude()
            + f"\nstart_daemon() {{ : > {marker}; return 0; }}\n"
            + "_is_ci_environment() { return 1; }\n"
        )
        script = (
            f"source .claude/init.sh\nPYTHON_CMD={sys.executable}\n{prelude}\n"
            "if ensure_daemon; then echo rc=0; else echo rc=$?; fi\n"
        )
        result = _run_script(
            project,
            script,
            None,
            socket_path=nonexistent_socket,
            extra_env={"CLAUDE_HOOKS_PID_PATH": str(pid_path)},
        )
        assert "rc=0" in result.stdout, result.stderr
        assert marker.exists(), result.stderr
        assert pid_path.read_text() == str(self._UNREAL_PID)

    def _ensure_in_ci(
        self, project: Path, tmp_path: Path, statuses: str, *, flagged: bool
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
        """``ensure_daemon`` in an unenforced CI whose start fails, with
        ``is_daemon_running`` answering ``statuses`` in turn (the last one
        from then on); returns the result, the start marker and the flag."""
        marker = tmp_path / "start-attempted"
        flag = tmp_path / "passthrough-flag"
        if flagged:
            flag.touch()
        prelude = (
            f"_statuses=({statuses})\n"
            "is_daemon_running() { local s=${_statuses[0]}; "
            '((${#_statuses[@]} > 1)) && _statuses=("${_statuses[@]:1}"); return "$s"; }\n'
            f"start_daemon() {{ : > {marker}; return 1; }}\n"
            f"_passthrough_flag_path() {{ echo {flag}; }}\n"
            "_is_ci_environment() { return 0; }\n_is_ci_enforced() { return 1; }\n"
        )
        script = (
            f"source .claude/init.sh\n{prelude}\n"
            "if ensure_daemon; then echo rc=0; else echo rc=$?; fi\n"
        )
        result = _run_script(project, script, None, socket_path=tmp_path / "none.sock")
        return result, marker, flag

    @pytest.mark.parametrize("flagged", [True, False], ids=["flag-set", "no-flag"])
    def test_an_unknown_answer_is_never_a_ci_passthrough(
        self, project: Path, tmp_path: Path, flagged: bool
    ) -> None:
        """Round 6 (R5-3): ``if is_daemon_running`` read unknown (2) as down,
        so an unenforced CI allowed every call without trying the start the
        contract asks for. The start is tried; while the answer stays unknown
        the failure is reported, not passed through."""
        result, marker, flag = self._ensure_in_ci(project, tmp_path, "2", flagged=flagged)
        assert "rc=1" in result.stdout, result.stderr
        assert marker.exists(), result.stderr
        assert flag.exists() == flagged

    def test_a_real_down_after_a_failed_start_takes_the_ci_passthrough(
        self, project: Path, tmp_path: Path
    ) -> None:
        result, marker, flag = self._ensure_in_ci(project, tmp_path, "2 1", flagged=False)
        assert "rc=0" in result.stdout, result.stderr
        assert marker.exists(), result.stderr
        assert flag.exists()

    def test_a_real_down_with_the_flag_skips_the_start(self, project: Path, tmp_path: Path) -> None:
        result, marker, _flag = self._ensure_in_ci(project, tmp_path, "1", flagged=True)
        assert "rc=0" in result.stdout, result.stderr
        assert not marker.exists()

    def test_a_pid_file_that_names_no_pid_is_removed(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path
    ) -> None:
        """Only a failure the builtin attributes to a live process counts as
        alive: text that is not a pid names no process at all."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text("not-a-pid")
        result = self._probe(project, pid_path, nonexistent_socket)
        assert "rc=1" in result.stdout, result.stderr
        assert not pid_path.exists()

    def test_the_client_pid_limit_matches_the_daemons(self) -> None:
        """``init.sh``'s ``_HOOKS_DAEMON_PID_MAX`` is ``paths.PID_MAX_LIMIT``."""
        assert f"_HOOKS_DAEMON_PID_MAX={PID_MAX_LIMIT}\n" in INIT_SH.read_text()


_CLI_MODULE = DAEMON_CLI_MODULE


def _launch_lines(project: Path) -> list[tuple[list[str], bool]]:
    """Command lines, each with whether ``init.sh`` must prove it serves
    ``project`` without the helper: every form a daemon of it is launched
    with. The rest are other projects', not daemon servers, or a launch's
    arguments away from the positions a launch puts them (round 6, P5-3)."""
    client_python = f"{project}/.claude/hooks-daemon/untracked/venv-x/bin/python"
    self_python = f"{project}/untracked/venv-x/bin/python"
    other = f"{project}-other"
    root = str(project)
    return [
        # start_daemon
        ([client_python, "-m", _CLI_MODULE, "--project-root", root, "start"], True),
        # bin/hooks-daemon, and every start or restart naming no root, which
        # cli.main re-runs naming it (round 6, Sh-1)
        ([client_python, "-m", _CLI_MODULE, "--project-root", root, "restart"], True),
        # Neither subcommand takes an argument, so its parser refuses the
        # launch and no daemon runs with it (N203).
        (["python3", "-m", _CLI_MODULE, "--project-root", root, "restart", "-x"], False),
        # Naming no root, a daemon serves whatever its working directory
        # found; only its socket can say which (round 6, Sh-1).
        ([client_python, "-m", _CLI_MODULE, "start"], False),
        ([self_python, "-I", "-m", _CLI_MODULE, "restart"], False),
        ([client_python, "-m", _CLI_MODULE, "--project-root", other, "start"], False),
        ([client_python, "-m", _CLI_MODULE, "--project-root", f"{root}x", "start"], False),
        ([client_python, "-m", _CLI_MODULE, "--project-root", root, "status"], False),
        ([client_python, "-m", _CLI_MODULE, "status"], False),
        ([client_python, "-m", _CLI_MODULE, "--project-root", other, "restart"], False),
        (["python3", "-m", _CLI_MODULE, "start"], False),
        ([f"{other}/untracked/venv/bin/python", "-m", _CLI_MODULE, "start"], False),
        ([client_python, "-m", _CLI_MODULE, "--project-root=" + other, "start"], False),
        # The flag names the project wherever it stands, even after `start`.
        ([client_python, "-m", _CLI_MODULE, "start", "--project-root", other], False),
        (
            [
                client_python,
                "-m",
                _CLI_MODULE,
                "--project-root",
                root,
                "start",
                "--project-root",
                other,
            ],
            False,
        ),
        (["--project-root=" + other, "-m", _CLI_MODULE, "--project-root", root, "start"], False),
        ([client_python, "-c", "pass", "--project-root", root, "start"], False),
        # The launch tokens anywhere but where a launch puts them.
        ([client_python, "-c", "pass", "-m", _CLI_MODULE, "--project-root", root, "start"], False),
        ([client_python, "-I", "-m", _CLI_MODULE, "--project-root", root, "start"], False),
        ([client_python, "-m", _CLI_MODULE, "--project-root", root, "-v", "start"], False),
        (["sh", "x", "-m", _CLI_MODULE, "--project-root", root, "start"], False),
        ([client_python, "-m", f"{_CLI_MODULE}x", "--project-root", root, "start"], False),
    ]


def _cmdline_bytes(argv: list[str]) -> bytes:
    """``argv`` as procfs holds it: each argument NUL-terminated."""
    return b"".join(argument.encode() + b"\0" for argument in argv)


def _psutil_argv(data: bytes) -> list[str]:
    """The arguments psutil reads from procfs ``data`` (``_pslinux.cmdline``)."""
    text = data.decode()
    if text.endswith("\0"):
        text = text[:-1]
    argv = text.split("\0")
    if len(argv) == 1 and " " in text:
        argv = text.split(" ")
    return argv


class TestTheHooksCommandLineProofIsSound:
    """Plan 00466 round 5 (Sh-D): ``init.sh`` proves a live pid of this
    user's from its command line without the half-second venv helper. Its
    rule is narrower than ``process_verification``'s: whatever it proves,
    the daemon's rule proves too, and it proves every launch form. Round 6
    (R5-2) reads procfs with the argument boundaries it keeps, so both
    sides see the same arguments."""

    @staticmethod
    def _daemon_proves(cmdline: list[str], project: Path) -> bool:
        """``process_verification``'s rule for a command line naming a root.
        A line its parser refuses names none (N203)."""
        from claude_code_hooks_daemon.daemon.process_verification import (
            _is_daemon_server_process,
            _root_from_flag,
            _UnreadableLaunch,
        )

        if not _is_daemon_server_process(cmdline):
            return False
        try:
            root = _root_from_flag(cmdline)
        except _UnreadableLaunch:
            return False
        return root is not None and os.path.realpath(root) == os.path.realpath(project)

    @staticmethod
    def _init_sh_proves(project: Path, function: str, argument: str) -> bool:
        script = (
            "source .claude/init.sh\n"
            f'if {function} "$ARGUMENT"; then echo rc=0; else echo rc=1; fi\n'
        )
        result = _run_script(
            project,
            script,
            None,
            socket_path=project / "none.sock",
            extra_env={"ARGUMENT": argument},
        )
        assert result.stdout.strip() in ("rc=0", "rc=1"), result.stderr
        return result.stdout.strip() == "rc=0"

    def _procfs_proves(self, project: Path, data: bytes) -> bool:
        """``init.sh``'s proof for a procfs ``cmdline`` file holding ``data``."""
        cmdline = project.parent / "cmdline"
        cmdline.write_bytes(data)
        return self._init_sh_proves(
            project, "_hooks_daemon_cmdline_proves_this_project", str(cmdline)
        )

    def test_procfs_proves_the_launch_forms_and_nothing_the_daemon_would_not(
        self, tmp_path: Path
    ) -> None:
        project = _make_project(tmp_path / "with space")
        for cmdline, launched in _launch_lines(project):
            proven = self._procfs_proves(project, _cmdline_bytes(cmdline))
            assert proven == launched, cmdline
            assert not proven or self._daemon_proves(cmdline, project), cmdline

    def test_ps_proves_the_launch_forms_and_nothing_the_daemon_would_not(
        self, tmp_path: Path
    ) -> None:
        """``ps`` joins the arguments with spaces, so its words are read as
        them: a project whose path holds a space is left to the helper."""
        for name, provable in (("plain", True), ("with space", False)):
            project = _make_project(tmp_path / name)
            for cmdline, launched in _launch_lines(project):
                proven = self._init_sh_proves(
                    project, "_hooks_daemon_ps_args_prove_this_project", " ".join(cmdline)
                )
                assert proven == (launched and provable), cmdline
                assert not proven or self._daemon_proves(cmdline, project), cmdline

    def test_a_symlinked_project_is_proven_by_its_real_path(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path / "real")
        (tmp_path / "link").symlink_to(project)
        cmdline = ["python3", "-m", _CLI_MODULE, "--project-root", str(project), "start"]
        assert self._procfs_proves(tmp_path / "link", _cmdline_bytes(cmdline))

    def test_argument_boundaries_count_where_procfs_keeps_them(self, tmp_path: Path) -> None:
        """One argument holding a whole launch line is not a launch."""
        project = _make_project(tmp_path / "proj")
        cmdline = ["bash", "-c", f"x -m {_CLI_MODULE} --project-root {project} start"]
        assert not self._daemon_proves(cmdline, project)
        assert not self._procfs_proves(project, _cmdline_bytes(cmdline))

    @pytest.mark.parametrize(
        ("case", "launched"),
        [
            ("an argument holding the launch across newlines", False),
            ("a launch whose last argument ends in a newline", False),
            ("a launch with no final NUL", True),
            ("a launch followed by an empty argument", False),
            ("a root cut in two by a NUL", False),
        ],
    )
    def test_procfs_bytes_are_read_as_the_daemon_reads_them(
        self, tmp_path: Path, case: str, launched: bool
    ) -> None:
        """Round 6 (R5-2): the arguments were joined with newlines, so one
        argument holding a newline-separated launch read as that launch,
        which ``process_verification`` rejects."""
        project = _make_project(tmp_path / "proj")
        root = str(project).encode()
        module = _CLI_MODULE.encode()
        launch = [b"python3", b"-m", module, b"--project-root", root, b"start"]
        data = {
            "an argument holding the launch across newlines": (
                b"sleep\0x\n" + b"\n".join(launch[1:]) + b"\0"
            ),
            "a launch whose last argument ends in a newline": b"\0".join(launch) + b"\n\0",
            "a launch with no final NUL": b"\0".join(launch),
            "a launch followed by an empty argument": b"\0".join(launch) + b"\0\0",
            "a root cut in two by a NUL": b"\0".join(
                [*launch[:4], root[:4] + b"\0" + root[4:], b"start"]
            ),
        }[case]
        proven = self._procfs_proves(project, data)
        assert proven == launched
        assert proven == self._daemon_proves(_psutil_argv(data), project)


class TestTheStartupPollIsBoundedByTheClock:
    """Plan 00466 round 5 (R4-1): the startup poll counted ticks, and every
    tick could run the daemon's venv helper, about half a second. With a PID
    file the hook cannot clear and a start that crashes, 150 ticks ran past
    the 60 s hook timeout, and PreToolUse failed open. Nothing is stubbed
    below but the crash itself and ``sleep``, which counts its ticks."""

    #: The startup budget these runs give ``start_daemon``, in deciseconds.
    _BUDGET = 20
    #: What each ``sleep 0.1`` of the poll really takes here.
    _TICK_SECONDS = 0.5

    def _crashing_start(
        self, project: Path, tmp_path: Path, pid_path: Path, prelude: str
    ) -> tuple[subprocess.CompletedProcess[str], int, int]:
        """The whole PreToolUse forwarder, with a daemon that crashes as it
        starts; returns the result, the helper's runs and the poll's ticks."""
        helper_runs = tmp_path / "helper-runs"
        ticks = tmp_path / "ticks"
        fake_python = tmp_path / "fake-python"
        fake_python.write_text(
            "#!/bin/bash\n"
            'if [[ "$1" == -m ]]; then echo "ERROR: Daemon crashed: simulated" >&2; exit 1; fi\n'
            f'if [[ "$2" == *"daemon.cli import"* || "$2" == *"daemon.server import"* ]]; then '
            f'echo run >> "{helper_runs}"; fi\n'
            f'exec "{sys.executable}" "$@"\n'
        )
        fake_python.chmod(0o755)
        fake_bin = tmp_path / "fake-bin"
        fake_bin.mkdir()
        real_sleep = shutil.which("sleep")
        assert real_sleep is not None
        (fake_bin / "sleep").write_text(
            f'#!/bin/bash\necho tick >> "{ticks}"\nexec "{real_sleep}" {self._TICK_SECONDS}\n'
        )
        (fake_bin / "sleep").chmod(0o755)
        script = (
            f"source .claude/init.sh\nPYTHON_CMD={fake_python}\n{prelude}\n"
            "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
            f"DAEMON_STARTUP_TIMEOUT={self._BUDGET}\nPATH={fake_bin}:$PATH\n{_FORWARDER_BODY}"
        )
        result = _run_script(
            project,
            script,
            _BASH_TOOL_INPUT,
            socket_path=tmp_path / "no-daemon.sock",
            extra_env={"CLAUDE_HOOKS_PID_PATH": str(pid_path)},
        )

        def count(path: Path) -> int:
            return len(path.read_text().splitlines()) if path.exists() else 0

        return result, count(helper_runs), count(ticks)

    def test_a_pid_it_may_not_signal_and_a_crashing_start_are_denied_in_time(
        self, project: Path, tmp_path: Path
    ) -> None:
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(TestIsDaemonRunningRemovesOnlyItsOwnStalePidFile._UNREAL_PID))
        result, helper_runs, ticks = self._crashing_start(
            project,
            tmp_path,
            pid_path,
            TestIsDaemonRunningRemovesOnlyItsOwnStalePidFile._eperm_prelude(),
        )
        assert _verdict(result) == "deny", result.stderr
        assert "Daemon crashed: simulated" in result.stdout + result.stderr
        assert helper_runs == 1, result.stderr
        # A tick really takes _TICK_SECONDS, so a clock-bounded poll ends
        # after a fraction of the ticks a count-bounded one would take.
        assert 0 < ticks < self._BUDGET, ticks

    def test_a_stale_file_it_cannot_remove_and_a_crashing_start_are_denied_in_time(
        self, project: Path, tmp_path: Path
    ) -> None:
        """The start lock cannot be opened (a planted symlink), so the stale
        file stays, and every tick asked the helper to remove it again."""
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(str(TestIsDaemonRunningRemovesOnlyItsOwnStalePidFile._UNREAL_PID))
        Path(f"{tmp_path / 'no-daemon.sock'}.start.lock").symlink_to(tmp_path / "planted")
        result, helper_runs, ticks = self._crashing_start(project, tmp_path, pid_path, "")
        assert _verdict(result) == "deny", result.stderr
        assert helper_runs == 1, result.stderr
        assert 0 < ticks < self._BUDGET, ticks


def _init_sh_value(pattern: str) -> str:
    """The one value ``pattern``'s group captures in ``init.sh``."""
    found = re.findall(pattern, INIT_SH.read_text(), re.MULTILINE)
    assert len(found) == 1, (pattern, found)
    return str(found[0])


class TestAStartNeverRunsTheHookPastItsTimeout:
    """Plan 00466 review 8, R8-1: a PreToolUse hook that reaches its timeout
    lets the call run unjudged. The hook waited on the launcher, and the
    launcher's own bounds (its interpreter, the start lock twice, a 30 s
    start budget) added to the 15 s poll after it came to about 65 s. The
    hook now bounds its own wait from its own start, and never waits on the
    launcher."""

    def test_the_bounds_on_the_start_path_sum_below_the_hook_timeout(self) -> None:
        """From the hook's start: the start deadline, which covers every wait
        before it, the start lock wait of the one helper run a hook makes,
        which may begin just before the deadline, and the request the
        started daemon then answers. The launcher's bounds are not on this
        path, which the test below proves."""
        start_deadline = int(_init_sh_value(r"^_HOOKS_DAEMON_START_DEADLINE=(\d+)$"))
        request = float(
            _init_sh_value(r"^def _resolve_socket_timeout\(\):\n.*\n.*\n\s+return (\d+\.\d+)$")
        )

        path = start_deadline + Timeout.FILE_LOCK + request

        assert start_deadline == Timeout.HOOK_START_DEADLINE_SEC
        assert request == Timeout.SOCKET_DISPATCH_ROUNDTRIP
        assert Timeout.HOOK_START_MARGIN_SEC > 0
        assert path + Timeout.HOOK_START_MARGIN_SEC <= Timeout.REGISTERED_HOOK_TIMEOUT

    def test_a_start_still_under_way_at_the_deadline_is_denied_as_starting(
        self, project: Path, tmp_path: Path
    ) -> None:
        """The launcher waits until this test releases it, so the hook can
        only answer by not waiting on it. The deadline is shortened, as the
        start poll's budget is above; nothing else is stubbed but the
        launcher and the venv check."""
        release = tmp_path / "release"
        fake_python = tmp_path / "fake-python"
        fake_python.write_text(
            "#!/bin/bash\n"
            'if [[ "$1" == -m ]]; then\n'
            f'    until [[ -e "{release}" ]]; do sleep 0.1; done\n'
            "    exit 1\n"
            "fi\n"
            f'exec "{sys.executable}" "$@"\n'
        )
        fake_python.chmod(0o755)
        script = (
            f"source .claude/init.sh\nPYTHON_CMD={fake_python}\n"
            "validate_venv() { return 0; }\n"
            "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
            f"_HOOKS_DAEMON_START_DEADLINE=2\n{_FORWARDER_BODY}"
        )
        hook = subprocess.Popen(
            [BASH, "-c", script],
            cwd=project,
            env=_script_env(tmp_path / "no-daemon.sock"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = hook.communicate(
                _stdin_text(_BASH_TOOL_INPUT), timeout=Timeout.REQUEST_LONG
            )
        except subprocess.TimeoutExpired:
            release.touch()
            hook.communicate()
            pytest.fail("the hook waited on a launcher that had not finished")
        finally:
            release.touch()

        result = subprocess.CompletedProcess(hook.args, hook.returncode, stdout, stderr)
        assert _verdict(result) == "deny", stderr
        reason = _reason(json.loads(stdout))
        assert "starting" in reason, reason
        assert "retry" in reason.lower(), reason


def _kill_failure_message(error: int) -> str:
    """The shell statement printing the builtin's own failure for ``error``,
    ``bash: kill: (<pid>) - <strerror>``, for a ``kill -0 <pid>`` shadow."""
    return f'printf "bash: kill: (%s) - %s\\n" "$2" "{os.strerror(error)}" >&2;'


#: Deeper than CPython's json parser recurses (Plan 00466 N140).
_TOO_DEEP = 1000


def _nested_call(depth: int) -> str:
    """An MCP-shaped PreToolUse input whose tool_input nests ``depth`` lists."""
    return (
        '{"tool_name": "mcp__deep__tool", "tool_input": {"value": '
        + "[" * depth
        + "]" * depth
        + "}}"
    )


_TRANSPORT = "source .claude/init.sh; send_request_stdin PreToolUse"


class TestInputThatCannotBeParsedIsDenied:
    """Plan 00466 N140: PreToolUse input the forwarder cannot parse was
    answered with context only, which allows the call. JSON nested about
    1000 deep raises RecursionError in ``json.loads``; a little shallower,
    it parses and the request envelope's ``json.dumps`` raised outside any
    handler, so the forwarder wrote nothing. Either way no guard judged the
    call, so it is denied with a reason that says so."""

    def test_deep_nesting_is_denied_on_the_plain_forwarder(
        self, project: Path, valid_deny_socket: Path
    ) -> None:
        result = _run_script(
            project, _TRANSPORT, _nested_call(_TOO_DEEP), socket_path=valid_deny_socket
        )
        assert _verdict(result) == "deny"
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert "invalid_hook_input" in reason, reason
        assert "could not be parsed" in reason, reason

    def test_deep_nesting_is_denied_on_a_relay_hand_off(
        self, project: Path, valid_empty_socket: Path
    ) -> None:
        result = _run_script(
            project,
            _TRANSPORT,
            _nested_call(_TOO_DEEP),
            socket_path=valid_empty_socket,
            relay_failure=_RELAY_FAILURE,
        )
        assert _verdict(result) == "deny"

    def test_every_depth_near_the_limit_gets_a_verdict(
        self, project: Path, valid_deny_socket: Path
    ) -> None:
        """Parsed and forwarded, the daemon's deny comes back; not parsed or
        not wrapped, the transport's own. Never no answer at all."""
        for depth in range(_TOO_DEEP - 20, _TOO_DEEP + 1):
            result = _run_script(
                project, _TRANSPORT, _nested_call(depth), socket_path=valid_deny_socket
            )
            assert result.stdout.strip(), f"depth {depth}: no answer; stderr: {result.stderr}"
            assert _verdict(result) == "deny", depth

    def test_text_that_is_not_json_is_denied(self, project: Path, valid_empty_socket: Path) -> None:
        result = _run_script(project, _TRANSPORT, "{not json", socket_path=valid_empty_socket)
        assert _verdict(result) == "deny"

    def test_bytes_that_are_not_utf8_are_denied(
        self, project: Path, valid_empty_socket: Path
    ) -> None:
        script = "source .claude/init.sh; printf '\\xff\\xfe{}' | send_request_stdin PreToolUse"
        result = _run_script(project, script, None, socket_path=valid_empty_socket)
        assert _verdict(result) == "deny"

    def test_another_event_still_fails_open(self, project: Path, valid_empty_socket: Path) -> None:
        script = "source .claude/init.sh; send_request_stdin PostToolUse"
        result = _run_script(
            project, script, _nested_call(_TOO_DEEP), socket_path=valid_empty_socket
        )
        assert _verdict(result) == "no-decision"


def _path_without_python3(tmp_path: Path, *, with_jq: bool) -> str:
    """A PATH holding no python3; with ``jq`` when asked and the host has it."""
    bin_dir = tmp_path / ("bin-jq" if with_jq else "bin-bare")
    bin_dir.mkdir()
    jq = shutil.which("jq")
    if with_jq and jq is not None:
        (bin_dir / "jq").symlink_to(jq)
    return str(bin_dir)


class TestADenyNeedsNoPython3:
    """Plan 00466 round 3 (R2-1): the deny names its recovery command by
    running python3 in a command substitution. Under ``set -e`` a missing
    python3 ended the forwarder there with no JSON, which Claude Code treats
    as a non-blocking hook error: the call ran. The transport itself is
    python3 too. Without it, both still deny."""

    @pytest.mark.parametrize("with_jq", [True, False])
    def test_the_daemon_down_deny_survives(
        self, project: Path, tmp_path: Path, nonexistent_socket: Path, with_jq: bool
    ) -> None:
        script = (
            "set -euo pipefail\nsource .claude/init.sh\n"
            f"PATH={_path_without_python3(tmp_path, with_jq=with_jq)}\n"
            "emit_hook_error PreToolUse daemon_startup_failed x\n"
        )
        result = _run_script(project, script, _BASH_TOOL_INPUT, socket_path=nonexistent_socket)
        assert _verdict(result) == "deny", result.stderr
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert "python3" in reason, reason

    def test_the_transport_deny_survives(
        self, project: Path, tmp_path: Path, valid_empty_socket: Path
    ) -> None:
        script = (
            "set -euo pipefail\nsource .claude/init.sh\n"
            f"PATH={_path_without_python3(tmp_path, with_jq=True)}\n"
            "send_request_stdin PreToolUse\n"
        )
        result = _run_script(project, script, _BASH_TOOL_INPUT, socket_path=valid_empty_socket)
        assert _verdict(result) == "deny", result.stderr

    def test_another_event_is_not_turned_into_a_deny(
        self, project: Path, tmp_path: Path, valid_empty_socket: Path
    ) -> None:
        script = (
            "source .claude/init.sh\n"
            f"PATH={_path_without_python3(tmp_path, with_jq=True)}\n"
            "send_request_stdin PostToolUse\n"
        )
        result = _run_script(project, script, _BASH_TOOL_INPUT, socket_path=valid_empty_socket)
        assert result.stdout == "", result.stdout


def _path_with_a_failing_python3(tmp_path: Path) -> str:
    """A PATH whose python3 runs the real one, then exits 7 whatever it did,
    as a flush error at interpreter shutdown would."""
    real = shutil.which("python3")
    assert real is not None
    bin_dir = tmp_path / "bin-failing-python3"
    bin_dir.mkdir()
    wrapper = bin_dir / "python3"
    wrapper.write_text(f'#!/bin/bash\n"{real}" "$@"\nexit 7\n')
    wrapper.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


class TestAPython3ThatFailsAfterAnsweringGivesOneAnswer:
    """Plan 00466 round 4 (D-PATH note on R2-1): the fixed deny was printed
    whenever python3 exited non-zero, after anything it had already written,
    so stdout could carry two JSON documents."""

    def test_pretooluse_gets_the_fixed_deny_alone(
        self, project: Path, tmp_path: Path, valid_empty_socket: Path
    ) -> None:
        script = (
            "set -euo pipefail\nsource .claude/init.sh\n"
            f"PATH={_path_with_a_failing_python3(tmp_path)}\n"
            "send_request_stdin PreToolUse\n"
        )
        result = _run_script(project, script, _BASH_TOOL_INPUT, socket_path=valid_empty_socket)
        assert _verdict(result) == "deny", result.stdout

    def test_another_event_keeps_its_answer_byte_for_byte(
        self, project: Path, tmp_path: Path, valid_empty_socket: Path
    ) -> None:
        plain = _run_script(
            project,
            "source .claude/init.sh\nsend_request_stdin PostToolUse\n",
            _BASH_TOOL_INPUT,
            socket_path=valid_empty_socket,
        )
        failing = _run_script(
            project,
            "source .claude/init.sh\n"
            f"PATH={_path_with_a_failing_python3(tmp_path)}\n"
            "send_request_stdin PostToolUse\n",
            _BASH_TOOL_INPUT,
            socket_path=valid_empty_socket,
        )
        assert plain.stdout.endswith("\n"), plain.stdout
        assert failing.stdout == plain.stdout
