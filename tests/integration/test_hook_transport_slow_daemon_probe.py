"""N762 (Plan 00474): what a hook gets when the daemon answers after the client's limit.

The N752 review asked whether a guard that runs past the client's wait fails
open. This probe answers it for each transport and event class with a stand-in
daemon: a Unix socket in a temporary directory that reads the whole request,
sleeps past the client's limit, and only then sends a verdict. The real daemon is
never contacted. The client limits are shortened (`--timeout-ms` for the relay,
`CLAUDE_HOOKS_SOCKET_TIMEOUT` for the bash/python3 transport) so the probe is
fast; the code paths are the ones a 30 s wait takes.

The answer pinned here:

- **PreToolUse fails CLOSED on both transports.** The relay hands the request to
  the forwarder (`init.sh`'s recovery carve-out), which denies; the python3
  transport denies on its socket timeout. The late verdict is never used.
- **Every other event fails OPEN.** On the relay a timeout gives `{}`. Stop and
  SubagentStop never use the relay, and the python3 transport lets a stop through
  on a read-side timeout (Plan 00177): a stop guard (branch stop guard, QA
  failure, goal ledger) that has not answered within the wait does not block.
  That is recorded in NIGGLES.md N762 as an owner decision, not changed here.

Before the client's wait runs out, the daemon's own chain deadline (20 s by
default, below the 30 s wait) denies a PreToolUse chain, or blocks a stop chain,
holding a SAFETY+BLOCKING handler that has not finished, so the client-side
timeout matters only for a daemon that cannot answer at all (wedged, the GIL-hang
shape) or a chain with no SAFETY+BLOCKING handler.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    PROBE_AS_FIELD,
    SYNTHETIC_SOURCE_FIELD,
    TEST_PROBE,
    ProbeThread,
)
from claude_code_hooks_daemon.install.forwarder_generator import generate_forwarder_content
from tests.daemon_like_process import daemon_like_process
from tests.relay_gate_guard import host_relay_build_path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / "init.sh"
_RELAY_BINARY = host_relay_build_path()

# A build older than relay/hooks_relay.rs fails with one "rebuild" message (N319).
pytestmark = pytest.mark.usefixtures("fresh_relay_build")

#: The relay's limit in the probe; the stand-in answers well after it.
_RELAY_LIMIT_MS = 500
#: The python3 transport's limit in the probe, in seconds.
_PYTHON_LIMIT_SECONDS = 1
#: How long the stand-in daemon sleeps before it answers: past both limits.
_DAEMON_DELAY_SECONDS = 4.0
#: Bound on every subprocess the probe runs.
_RUN_BOUND_SECONDS = 30

_MAIN_PROBE = {SYNTHETIC_SOURCE_FIELD: TEST_PROBE, PROBE_AS_FIELD: ProbeThread.MAIN.value}

#: The verdict the stand-in sends too late: an allow, which must never be used.
_LATE_ALLOW = b"{}"

_FORWARDER_TEMPLATE = """#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

if ! ensure_daemon; then
    emit_hook_error "{event}" "daemon_startup_failed" "daemon failed to start"
    exit 0
fi

send_request_stdin "{event}"
"""

#: The real `.claude/hooks/stop` shape: no `-e`, and the exit status is propagated.
_STOP_FORWARDER_TEMPLATE = """#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

if ! ensure_daemon; then
    emit_hook_error "{event}" "daemon_startup_failed" "daemon failed to start"
    exit 0
fi

forward_stop_event "{event}"
exit $?
"""


class _SlowDaemon:
    """Reads each request to EOF, sleeps past the client's limit, then answers."""

    def __init__(self, sock_path: Path, answer: bytes) -> None:
        self._answer = answer
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(sock_path))
        self._server.listen(8)
        self._server.settimeout(_RUN_BOUND_SECONDS)
        self._released = threading.Event()
        self.requests: list[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._server.accept()
        except OSError:
            return
        with conn:
            received = b""
            while chunk := conn.recv(4096):
                received += chunk
            self.requests.append(received)
            if self._released.wait(_DAEMON_DELAY_SECONDS):
                return
            try:
                conn.sendall(self._answer)
            except OSError:
                # The client has gone, which is what a timed-out client does.
                return

    def close(self) -> None:
        self._released.set()
        self._server.close()
        self._thread.join(_RUN_BOUND_SECONDS)


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A directory short enough for an AF_UNIX path."""
    directory = Path(tempfile.mkdtemp(prefix="hd-"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def _project(root: Path, event_file: str, event: str, template: str) -> Path:
    """A client project at ``root`` holding a generated forwarder and ``init.sh``."""
    content = generate_forwarder_content(
        template.format(event=event), event_file, TransportConfig(), root / "untracked", root
    )
    hooks_dir = root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    forwarder = hooks_dir / event_file
    forwarder.write_text(content)
    forwarder.chmod(0o755)
    (root / ".claude" / "init.sh").write_text(_INIT_SH.read_text())
    (root / "bin").mkdir()
    (root / "bin" / "hooks-daemon").write_text("#!/bin/bash\n")
    return forwarder


def _env(root: Path, sock_path: Path, pid_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOOKS_DAEMON_ROOT_DIR"] = str(root)
    env["CLAUDE_HOOKS_SOCKET_PATH"] = str(sock_path)
    env["CLAUDE_HOOKS_PID_PATH"] = str(pid_path)
    env["CLAUDE_HOOKS_SOCKET_TIMEOUT"] = str(_PYTHON_LIMIT_SECONDS)
    return env


def _bash_call(command: str, cwd: Path) -> bytes:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(cwd),
            **_MAIN_PROBE,
        }
    ).encode()


def _permission_decision(stdout: bytes) -> str | None:
    hso = json.loads(stdout)["hookSpecificOutput"]
    decision: str | None = hso.get("permissionDecision")
    return decision


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
class TestTheRelay:
    """The relay binary, invoked as the generated forwarder invokes it."""

    def test_a_pre_tool_use_answer_after_the_limit_is_denied(
        self, tmp_path: Path, short_dir: Path
    ) -> None:
        forwarder = _project(tmp_path, "pre-tool-use", "PreToolUse", _FORWARDER_TEMPLATE)
        daemon = _SlowDaemon(short_dir / "pre-tool-use.sock", _LATE_ALLOW)
        try:
            result = subprocess.run(
                [
                    str(_RELAY_BINARY),
                    str(short_dir / "pre-tool-use.sock"),
                    "--fallback",
                    str(forwarder),
                    "--timeout-ms",
                    str(_RELAY_LIMIT_MS),
                ],
                input=_bash_call("git status", tmp_path),
                capture_output=True,
                env=_env(tmp_path, tmp_path / "legacy.sock", tmp_path / "no-daemon.pid"),
                timeout=_RUN_BOUND_SECONDS,
            )
        finally:
            daemon.close()

        assert daemon.requests, "the stand-in daemon never received the request"
        assert b"hooks-relay: timeout:" in result.stderr, result.stderr.decode()
        assert result.returncode == 0, result.stderr.decode()
        assert _permission_decision(result.stdout) == "deny", result.stdout.decode()

    @pytest.mark.parametrize("socket_name", ["user-prompt-submit", "post-tool-use"])
    def test_any_other_event_after_the_limit_fails_open(
        self, short_dir: Path, socket_name: str
    ) -> None:
        daemon = _SlowDaemon(short_dir / f"{socket_name}.sock", b'{"decision":"block"}')
        try:
            result = subprocess.run(
                [
                    str(_RELAY_BINARY),
                    str(short_dir / f"{socket_name}.sock"),
                    "--timeout-ms",
                    str(_RELAY_LIMIT_MS),
                ],
                input=json.dumps({"prompt": "hello", **_MAIN_PROBE}).encode(),
                capture_output=True,
                timeout=_RUN_BOUND_SECONDS,
            )
        finally:
            daemon.close()

        assert b"hooks-relay: timeout:" in result.stderr, result.stderr.decode()
        assert result.returncode == 0, result.stderr.decode()
        assert json.loads(result.stdout) == {}

    def test_the_event_is_read_from_the_socket_name_not_the_payload(self, short_dir: Path) -> None:
        """A PreToolUse payload on a socket not named for PreToolUse fails open.

        The relay never parses the request, so only the deployed forwarder's socket
        path makes a timeout deny. Every generated PreToolUse forwarder names
        `pre-tool-use.sock`, which `tests/unit/install/test_forwarder_generator.py`
        pins.
        """
        daemon = _SlowDaemon(short_dir / "daemon.sock", _LATE_ALLOW)
        try:
            result = subprocess.run(
                [
                    str(_RELAY_BINARY),
                    str(short_dir / "daemon.sock"),
                    "--timeout-ms",
                    str(_RELAY_LIMIT_MS),
                ],
                input=_bash_call("pytest", short_dir),
                capture_output=True,
                timeout=_RUN_BOUND_SECONDS,
            )
        finally:
            daemon.close()

        assert b"hooks-relay: timeout:" in result.stderr, result.stderr.decode()
        assert result.returncode == 0
        assert json.loads(result.stdout) == {}


class TestThePythonTransport:
    """The bash/python3 transport: relay off, or an event the relay never carries."""

    def test_a_pre_tool_use_answer_after_the_limit_is_denied(
        self, tmp_path: Path, short_dir: Path
    ) -> None:
        forwarder = _project(tmp_path, "pre-tool-use", "PreToolUse", _FORWARDER_TEMPLATE)
        sock_path = short_dir / "daemon.sock"
        daemon = _SlowDaemon(sock_path, _LATE_ALLOW)
        try:
            with daemon_like_process(tmp_path) as pid:
                pid_path = tmp_path / "daemon.pid"
                pid_path.write_text(f"{pid}\n")
                result = subprocess.run(
                    ["bash", str(forwarder), "--no-relay"],
                    input=_bash_call("git status", tmp_path),
                    capture_output=True,
                    env=_env(tmp_path, sock_path, pid_path),
                    timeout=_RUN_BOUND_SECONDS,
                )
        finally:
            daemon.close()

        assert daemon.requests, "the stand-in daemon never received the request"
        assert b"socket_timeout" in result.stderr, result.stderr.decode()
        assert result.returncode == 0, result.stderr.decode()
        assert _permission_decision(result.stdout) == "deny", result.stdout.decode()

    @pytest.mark.parametrize("event", ["Stop", "SubagentStop"])
    def test_a_stop_block_after_the_limit_fails_open(
        self, tmp_path: Path, short_dir: Path, event: str
    ) -> None:
        """Owner decision in N762: a stop guard that has not answered lets the stop through."""
        event_file = "stop" if event == "Stop" else "subagent-stop"
        forwarder = _project(tmp_path, event_file, event, _STOP_FORWARDER_TEMPLATE)
        sock_path = short_dir / "daemon.sock"
        late_block = json.dumps({"decision": "block", "reason": "stop guard"}).encode()
        daemon = _SlowDaemon(sock_path, late_block)
        try:
            with daemon_like_process(tmp_path) as pid:
                pid_path = tmp_path / "daemon.pid"
                pid_path.write_text(f"{pid}\n")
                result = subprocess.run(
                    ["bash", str(forwarder)],
                    input=json.dumps({"hook_event_name": event, **_MAIN_PROBE}).encode(),
                    capture_output=True,
                    env=_env(tmp_path, sock_path, pid_path),
                    timeout=_RUN_BOUND_SECONDS,
                )
        finally:
            daemon.close()

        assert daemon.requests, "the stand-in daemon never received the request"
        assert b"socket_timeout" in result.stderr, result.stderr.decode()
        assert result.returncode == 0, result.stderr.decode()
        assert json.loads(result.stdout) == {}
