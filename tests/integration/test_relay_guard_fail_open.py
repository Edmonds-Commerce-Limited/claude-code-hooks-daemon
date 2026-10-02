"""Acceptance tests for the Plan 00290 relay guard's fail-open ladder (Task 4.2).

Drives REAL deployed-shape forwarders (generated via
``generate_forwarder_content``) through the actual scenarios the fallback
ladder (DESIGN-socket-relay.md §5) must survive:

1. **daemon-down** — relay binary present, socket absent/stale: connect
   fails, the relay execs the bash fallback (``--no-relay``) with stdin
   intact, which reaches ``ensure_daemon`` exactly as today.
2. **binary-missing** — the relay binary path in the guard does not exist
   (or is not executable): the guard's own ``-x`` test fails and the script
   falls straight through to `source init.sh` — no relay invocation at all.
3. **nc-missing** — ``nc`` absent from PATH (or the nc-capability env flag
   unset): ``send_request_stdin``'s nc rung is skipped entirely and the
   python3 transport serves the request, unchanged.
4. **`--no-relay` re-entry loop-safety** — a forwarder invoked with
   ``--no-relay`` (exactly as the relay's fallback exec does) must skip its
   OWN guard block rather than trying the relay again.

Where a real Rust relay binary is available on disk (built by
``relay/build.sh`` into ``untracked/relay-build/``) these run genuinely
end-to-end against it. Where it is not (e.g. a CI runner without a musl
toolchain), the daemon-down scenario is skipped rather than faked — a
skip is honest about what did not run; faking the binary's fallback-exec
contract would test this file's assumptions about the binary, not the
binary itself.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon.paths import _get_hostname_suffix
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    PROBE_AS_FIELD,
    SYNTHETIC_SOURCE_FIELD,
    TEST_PROBE,
    ProbeThread,
)
from claude_code_hooks_daemon.install.forwarder_generator import (
    RELAY_DAEMON_ROOT_ENV,
    generate_forwarder_content,
)
from claude_code_hooks_daemon.utils.cli_command import install_recovery_command
from tests.daemon_like_process import daemon_like_process
from tests.deep_json import TOO_DEEP_FOR_ANY_PYTHON, nested_call

#: A probe sent through a hook forwarder is marked (Plan 00466 N12).
_MAIN_PROBE = {SYNTHETIC_SOURCE_FIELD: TEST_PROBE, PROBE_AS_FIELD: ProbeThread.MAIN.value}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / ".claude" / "init.sh"
_RELAY_BINARY = _REPO_ROOT / "untracked" / "relay-build" / "hooks-relay-x86_64-unknown-linux-musl"

# A build older than relay/hooks_relay.rs fails with one "rebuild" message (N319).
pytestmark = pytest.mark.usefixtures("fresh_relay_build")

_TIMEOUT_SECONDS = 15

#: The daemon clone's launcher, which ``cli.py`` and a deny name first.
_CLONE_LAUNCHER = ".claude/hooks-daemon/bin/hooks-daemon"


class _RecordingSocketServer:
    """Minimal Unix-socket server: records one request, replies canned bytes."""

    def __init__(self, sock_path: Path, response: bytes) -> None:
        self.sock_path = sock_path
        self.response = response
        self.received: bytes | None = None
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.settimeout(10.0)
        self._srv.bind(str(sock_path))
        self._srv.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        with conn:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            self.received = data
            conn.sendall(self.response)

    def join(self, timeout: float = 10.0) -> None:
        self._thread.join(timeout)

    def close(self) -> None:
        self._srv.close()


#: Self-contained forwarder shape — deliberately NOT read from this
#: repository's own `.claude/hooks/*`, which is daemon-owned and can be
#: mid-regeneration by a concurrent transport-config change (Plan 00290
#: Phase 6 found exactly this: a concurrent dogfood flip had already
#: guard-injected the live files, silently contaminating every test here
#: that read them). A fixed template keeps this suite's outcomes a function
#: of the code under test, never of this repo's current deploy state.
_FORWARDER_TEMPLATE = """#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

if ! ensure_daemon; then
    emit_hook_error "{event_pascal}" "daemon_startup_failed" "daemon failed to start"
    exit 0
fi

send_request_stdin "{event_pascal}"
"""

#: Mirrors the real `.claude/hooks/stop`/`subagent-stop` shape: `set -uo
#: pipefail` (not `-e` — `forward_stop_event` returning 2 on block is
#: desired) and `exit $?` propagating the translated exit code.
_STOP_FORWARDER_TEMPLATE = """#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

if ! ensure_daemon; then
    emit_hook_error "{event_pascal}" "daemon_startup_failed" "daemon failed to start"
    exit 0
fi

forward_stop_event "{event_pascal}"
exit $?
"""


def _write_generated_forwarder(
    tmp_path: Path,
    event_file_name: str,
    event_pascal: str,
    transport: TransportConfig,
    untracked_dir: Path,
    *,
    template: str = _FORWARDER_TEMPLATE,
) -> Path:
    source = template.format(event_pascal=event_pascal)
    # `tmp_path` is both the checkout the forwarder is generated for and the
    # one it runs from, so the guard's checkout test passes and these probes
    # exercise the relay branch (Plan 00364 Task 5.1).
    content = generate_forwarder_content(
        source, event_file_name, transport, untracked_dir, tmp_path
    )
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "init.sh").parent.mkdir(parents=True, exist_ok=True)
    forwarder = hooks_dir / event_file_name
    forwarder.write_text(content)
    forwarder.chmod(0o755)
    # SCRIPT_DIR/../init.sh must resolve to the real init.sh.
    (tmp_path / ".claude" / "init.sh").write_text(_INIT_SH.read_text())
    return forwarder


def _base_env(sock_path: Path, pid_path: Path) -> dict[str, str]:
    """Base env for a forwarder subprocess, isolated from this repo's OWN
    (possibly concurrently-modified — e.g. a dogfood transport flip)
    `untracked/` state.

    `HOOKS_DAEMON_ROOT_DIR` governs where `init.sh` resolves `_untracked_dir`
    — and therefore where the nc rung's per-event socket lookup lands — so it
    must point at THIS test's own isolated root (`sock_path`'s parent, which
    every caller already derives from `tmp_path` or an equivalent short-lived
    dir) rather than the real repo checkout. Nothing these tests exercise
    needs the real repo's venv/CLI: `ensure_daemon` always short-circuits on
    `live_pid_file` before reaching anything that would.
    """
    env = os.environ.copy()
    env["HOOKS_DAEMON_ROOT_DIR"] = str(sock_path.parent)
    env["CLAUDE_HOOKS_SOCKET_PATH"] = str(sock_path)
    env["CLAUDE_HOOKS_PID_PATH"] = str(pid_path)
    return env


@contextlib.contextmanager
def _live_pid_file(project: Path, directory: Path) -> Iterator[Path]:
    """A PID file in ``directory`` naming a process launched as the daemon of
    the checkout ``_write_generated_forwarder`` builds at ``project`` is, so
    is_daemon_running() proves it running (Plan 00466 round 5, Sh-D)."""
    pid_path = directory / "daemon.pid"
    with daemon_like_process(project) as pid:
        pid_path.write_text(f"{pid}\n")
        yield pid_path


@pytest.fixture
def live_pid_file(tmp_path: Path) -> Iterator[Path]:
    with _live_pid_file(tmp_path, tmp_path) as pid_path:
        yield pid_path


@pytest.fixture
def sock_path(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "daemon.sock"
    yield path
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# 1. daemon-down: relay execs the fallback with stdin intact
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
def test_daemon_down_relay_execs_fallback_and_reaches_daemon(
    tmp_path: Path, sock_path: Path, live_pid_file: Path
) -> None:
    """Relay binary present, per-event socket ABSENT (daemon never started
    the listener) -> the guard's own `-S` test is false, so relay is never
    even invoked; the script falls straight to the legacy path and reaches
    the (fake) daemon over the legacy socket exactly as today."""
    untracked_dir = tmp_path / "untracked"
    transport = TransportConfig(relay_enabled=True, relay_binary=str(_RELAY_BINARY))
    forwarder = _write_generated_forwarder(
        tmp_path, "pre-tool-use", "PreToolUse", transport, untracked_dir
    )

    canned = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"ok"}}\n'
    server = _RecordingSocketServer(sock_path, canned)
    server.start()
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}, **_MAIN_PROBE}
    ).encode()

    result = subprocess.run(
        ["bash", str(forwarder)],
        input=payload,
        capture_output=True,
        env=_base_env(sock_path, live_pid_file),
        timeout=_TIMEOUT_SECONDS,
    )
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None, "legacy daemon never reached"
    request = json.loads(server.received)
    assert request["hook_input"]["tool_input"]["command"] == "ls"


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
def test_relay_connect_fail_execs_fallback_with_stdin_intact(tmp_path: Path) -> None:
    """Direct binary-level pin (no generated forwarder involved): connect
    failure execs `/bin/bash <fallback> --no-relay` and stdin survives the
    exec unmodified — the exact contract the guard block depends on."""
    fallback = tmp_path / "fallback.sh"
    fallback.write_text('#!/bin/bash\necho "ARGS:$*"\ncat\n')
    fallback.chmod(0o755)

    result = subprocess.run(
        [str(_RELAY_BINARY), str(tmp_path / "no-such-socket.sock"), "--fallback", str(fallback)],
        input=b'{"payload":"data"}',
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stderr.decode()
    stdout = result.stdout.decode()
    assert "ARGS:--no-relay" in stdout
    assert '{"payload":"data"}' in stdout


@pytest.fixture
def wedged_pretooluse_socket() -> Iterator[Path]:
    """A ``pre-tool-use.sock`` whose daemon accepts and never answers: the
    B2 GIL-hang shape, which runs the relay's budget out mid-exchange."""
    short_dir = Path(tempfile.mkdtemp(prefix="hd-"))
    sock = short_dir / "pre-tool-use.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock))
    server.listen(8)
    # A short accept timeout lets the loop see `stop` promptly: closing a
    # socket from another thread does not wake a blocked accept() on Linux.
    server.settimeout(0.2)
    held: list[socket.socket] = []
    stop = threading.Event()

    def _accept_and_hold() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            held.append(conn)

    acceptor = threading.Thread(target=_accept_and_hold, daemon=True)
    acceptor.start()
    try:
        yield sock
    finally:
        stop.set()
        acceptor.join(_TIMEOUT_SECONDS)
        server.close()
        for conn in held:
            conn.close()
        shutil.rmtree(short_dir)


def _run_relay(
    sock: Path, payload: bytes, *extra: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(_RELAY_BINARY), str(sock), "--timeout-ms", "500", *extra],
        input=payload,
        capture_output=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
def test_an_over_cap_timeout_from_an_old_forwarder_is_clamped(tmp_path: Path) -> None:
    """Plan 00466 round 4: a forwarder deployed before the config clamp still
    passes its old ``--timeout-ms``; the relay takes the cap instead."""
    over = (Timeout.RELAY_TIMEOUT_CAP + 1) * Timeout.MILLISECONDS_PER_SECOND
    result = subprocess.run(
        [str(_RELAY_BINARY), str(tmp_path / "absent.sock"), "--timeout-ms", str(over)],
        input=b"{}",
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
    )
    cap_ms = Timeout.RELAY_TIMEOUT_CAP * Timeout.MILLISECONDS_PER_SECOND
    assert f"--timeout-ms {over} is over the cap; using {cap_ms}".encode() in result.stderr


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
def test_relay_pretooluse_timeout_deny_names_the_timeout(wedged_pretooluse_socket: Path) -> None:
    """Plan 00466 N69: a daemon that accepts and never answers runs the
    relay's budget out, and the deny says so in words. An expired socket
    timeout surfaces as EAGAIN, which Rust prints as "Resource temporarily
    unavailable (os error 11)" -- a label that names no cause."""
    result = _run_relay(wedged_pretooluse_socket, b'{"k":1}')

    assert result.returncode == 0, result.stderr.decode()
    hso = json.loads(result.stdout)["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    reason = hso["permissionDecisionReason"]
    assert "timed out" in reason, reason
    assert "os error" not in reason, reason


def _judging_project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A project whose forwarder the relay can hand a failed exchange to.

    Returns the forwarder and its env. Under a relay hand-off
    ``ensure_daemon`` returns before it looks at the daemon (N126 round 2,
    F1), so the only judge left is ``init.sh``'s own recovery carve-out. The
    PID file names no process, so a start would be tried if that ever
    regressed. The project has its own ``bin/hooks-daemon``.
    """
    untracked_dir = tmp_path / "untracked"
    forwarder = _write_generated_forwarder(
        tmp_path, "pre-tool-use", "PreToolUse", TransportConfig(), untracked_dir
    )
    launcher = tmp_path / "bin" / "hooks-daemon"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/bash\n")
    return forwarder, _base_env(tmp_path / "legacy.sock", tmp_path / "no-daemon.pid")


def _bash_call(command: str, cwd: Path) -> bytes:
    return json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd), **_MAIN_PROBE}
    ).encode()


def test_the_deeply_nested_probe_carries_its_markers() -> None:
    """The live-probe scan cannot read a payload built by ``nested_call``."""
    parsed = json.loads(nested_call(3, _MAIN_PROBE))
    assert parsed["tool_input"] == {"value": [[[]]]}
    assert parsed.items() >= _MAIN_PROBE.items()


def _decision(result: subprocess.CompletedProcess[bytes]) -> str | None:
    assert result.returncode == 0, result.stderr.decode()
    hso = json.loads(result.stdout)["hookSpecificOutput"]
    decision: str | None = hso.get("permissionDecision")
    return decision


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
class TestRelayMidExchangeFailureIsJudgedByTheOneCarveOut:
    """Plan 00466 N126: a wedged daemon must not deny its own restart.

    On the PreToolUse socket the relay cannot hand a failed exchange to the
    daemon, and it must not judge the payload itself (a second copy of the
    carve-out would drift, as N67's two copies did). It hands the whole
    request to the bash forwarder, whose ``init.sh`` applies the same judged
    carve-out as every other transport failure.
    """

    def test_the_projects_own_restart_is_not_denied(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        forwarder, env = _judging_project(tmp_path)
        result = _run_relay(
            wedged_pretooluse_socket,
            _bash_call("bin/hooks-daemon restart", tmp_path),
            "--fallback",
            str(forwarder),
            env=env,
        )
        assert _decision(result) is None

    def test_a_restart_that_runs_a_planted_launcher_is_denied(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        forwarder, env = _judging_project(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "bin").mkdir(parents=True)
        (elsewhere / "bin" / "hooks-daemon").write_text("#!/bin/bash\necho planted\n")
        result = _run_relay(
            wedged_pretooluse_socket,
            _bash_call("bin/hooks-daemon restart", elsewhere),
            "--fallback",
            str(forwarder),
            env=env,
        )
        assert _decision(result) == "deny"

    def test_any_other_call_is_denied_and_the_reason_names_the_relay_failure(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        forwarder, env = _judging_project(tmp_path)
        result = _run_relay(
            wedged_pretooluse_socket,
            _bash_call("git reset --hard", tmp_path),
            "--fallback",
            str(forwarder),
            env=env,
        )
        assert _decision(result) == "deny"
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert "relay_exchange_failed" in reason, reason
        assert "Hooks daemon reached" in reason, reason

    def test_input_nested_too_deeply_to_parse_is_denied(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        """Plan 00466 N140: the forwarder answered unparseable input with
        context only, and the relay accepts that shape as the carve-out's
        allow. It must deny, and say why."""
        forwarder, env = _judging_project(tmp_path)
        payload = nested_call(TOO_DEEP_FOR_ANY_PYTHON, _MAIN_PROBE).encode()
        result = _run_relay(
            wedged_pretooluse_socket, payload, "--fallback", str(forwarder), env=env
        )
        assert _decision(result) == "deny"
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert "invalid_hook_input" in reason, reason

    def test_a_fallback_that_answers_nothing_leaves_the_relays_own_deny(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        """The hand-off must fail closed: silence from the forwarder is not
        an answer, so the relay writes its own deny."""
        silent = tmp_path / "silent.sh"
        silent.write_text("#!/bin/bash\ncat > /dev/null\nexit 0\n")
        silent.chmod(0o755)
        result = _run_relay(
            wedged_pretooluse_socket,
            _bash_call("bin/hooks-daemon restart", tmp_path),
            "--fallback",
            str(silent),
        )
        assert _decision(result) == "deny"

    def test_a_fallback_that_fails_leaves_the_relays_own_deny(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        failing = tmp_path / "failing.sh"
        failing.write_text('#!/bin/bash\ncat > /dev/null\necho "{}"\nexit 3\n')
        failing.chmod(0o755)
        result = _run_relay(
            wedged_pretooluse_socket,
            _bash_call("bin/hooks-daemon restart", tmp_path),
            "--fallback",
            str(failing),
        )
        assert _decision(result) == "deny"

    def test_the_fallback_receives_the_whole_request(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        """The request is replayed byte for byte, however large."""
        recorded = tmp_path / "recorded.bin"
        recorder = tmp_path / "recorder.sh"
        recorder.write_text(f'#!/bin/bash\ncat > "{recorded}"\necho "{{}}"\n')
        recorder.chmod(0o755)
        payload = _bash_call("echo " + "x" * (1024 * 1024), tmp_path)
        result = _run_relay(wedged_pretooluse_socket, payload, "--fallback", str(recorder))
        assert result.returncode == 0, result.stderr.decode()
        assert recorded.read_bytes() == payload


def _answering_fallback(tmp_path: Path, answer: bytes) -> Path:
    """A fallback that drains stdin, writes ``answer`` and exits 0."""
    answer_file = tmp_path / "answer.bin"
    answer_file.write_bytes(answer)
    script = tmp_path / "answering.sh"
    script.write_text(f'#!/bin/bash\ncat > /dev/null\ncat "{answer_file}"\n')
    script.chmod(0o755)
    return script


def _relays_own_deny(result: subprocess.CompletedProcess[bytes]) -> bool:
    assert result.returncode == 0, result.stderr.decode()
    hso = json.loads(result.stdout)["hookSpecificOutput"]
    return bool(
        hso["permissionDecision"] == "deny"
        and hso["permissionDecisionReason"].startswith("BLOCKED [transport-fail-closed]")
    )


def _hso(**fields: str) -> bytes:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **fields}}).encode()


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
class TestTheRelayAcceptsOnlyAVerdictFromTheHandOff:
    """Plan 00466 N126 round 2 (F2): the relay took any non-empty exit-0
    output from the forwarder as the verdict, so ``{}``, truncated JSON or a
    shape Claude Code ignores became an allow where the relay would have
    denied. It now accepts only a complete PreToolUse document that is a
    deny with a reason, or the carve-out's context-only answer; anything
    else gets the relay's own deny."""

    @pytest.mark.parametrize(
        "answer",
        [
            b"{}",
            b"{}\n",
            b'{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalCon',
            b'{"hookSpecificOutput": {"hookEventName": "PreToolUse"}}',
            b'{"systemMessage": "fail-open advisory"}',
            b"[]",
            b"null",
            b'"deny"',
            _hso(permissionDecision="allow"),
            _hso(permissionDecision="ask", permissionDecisionReason="r"),
            _hso(permissionDecision="deny"),
            _hso(permissionDecision="deny", permissionDecisionReason="r") + b"{}",
            _hso(additionalContext="c", permissionDecisionReason="r"),
            _hso(additionalContext="c", continue_="x"),
            json.dumps(
                {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "c"}}
            ).encode(),
            json.dumps(
                {"hookSpecificOutput": {"hookEventName": "PreToolUse"}, "decision": "approve"}
            ).encode(),
            b'{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "a",'
            b' "additionalContext": "b"}}',
            b'{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "\\ud800"}}',
            b'{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "\xff"}}',
            b'{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "a\nb"}}',
        ],
    )
    def test_anything_but_a_verdict_gets_the_relays_own_deny(
        self, tmp_path: Path, wedged_pretooluse_socket: Path, answer: bytes
    ) -> None:
        fallback = _answering_fallback(tmp_path, answer)
        result = _run_relay(
            wedged_pretooluse_socket,
            _bash_call("bin/hooks-daemon restart", tmp_path),
            "--fallback",
            str(fallback),
        )
        assert _relays_own_deny(result), result.stdout

    @pytest.mark.parametrize(
        "answer",
        [
            _hso(
                permissionDecision="deny",
                permissionDecisionReason='judged \N{LATIN SMALL LETTER E WITH ACUTE} \\ "q"',
            ),
            _hso(
                permissionDecision="deny",
                permissionDecisionReason="judged",
                additionalContext="context",
            ),
            _hso(additionalContext="carve-out: the project's own restart"),
            b'  {"hookSpecificOutput" : {"additionalContext": "\\u00e9\\ud83d\\ude00",'
            b' "hookEventName": "PreToolUse"}}\n',
        ],
    )
    def test_a_verdict_passes_through_byte_for_byte(
        self, tmp_path: Path, wedged_pretooluse_socket: Path, answer: bytes
    ) -> None:
        fallback = _answering_fallback(tmp_path, answer)
        result = _run_relay(
            wedged_pretooluse_socket,
            _bash_call("bin/hooks-daemon restart", tmp_path),
            "--fallback",
            str(fallback),
        )
        assert result.returncode == 0, result.stderr.decode()
        assert result.stdout == answer

    def test_a_fallback_that_never_finishes_gets_the_relays_own_deny(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        """F3: the hand-off has its own deadline. Without one, a forwarder
        that hangs holds the hook until Claude Code cancels it, and a
        cancelled PreToolUse hook lets the call run unjudged."""
        hanging = tmp_path / "hanging.sh"
        hanging.write_text("#!/bin/bash\ncat > /dev/null\nexec sleep 3600\n")
        hanging.chmod(0o755)
        result = subprocess.run(
            [
                str(_RELAY_BINARY),
                str(wedged_pretooluse_socket),
                "--timeout-ms",
                "500",
                "--fallback",
                str(hanging),
            ],
            input=_bash_call("bin/hooks-daemon restart", tmp_path),
            capture_output=True,
            timeout=Timeout.REGISTERED_HOOK_TIMEOUT,
        )
        assert _relays_own_deny(result), result.stdout


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
class TestTheRelaysOwnDenyNamesTheAbsoluteLauncher:
    """Plan 00466 round 2 (m1): the relay's own deny names the same exempt
    command ``init.sh``'s denies do, the project's launcher by absolute path,
    so it can be run from any directory."""

    def _own_deny_reason(self, project: Path, wedged: Path, daemon_root: Path | None = None) -> str:
        """The relay's own deny, with ``daemon_root`` handed over as the
        generated forwarder hands it (none: a forwarder from before that)."""
        hooks = project / ".claude" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        failing = hooks / "pre-tool-use"
        failing.write_text("#!/bin/bash\ncat > /dev/null\nexit 3\n")
        failing.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_")}
        if daemon_root is not None:
            env[RELAY_DAEMON_ROOT_ENV] = str(daemon_root)
        result = _run_relay(
            wedged, _bash_call("true", project), "--fallback", str(failing), env=env
        )
        assert _relays_own_deny(result), result.stdout
        reason: str = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        return reason

    def _init_sh_command(self, project: Path, daemon_root: Path) -> str | None:
        """What init.sh names, or None when it knows no exempt command."""
        shutil.copy(_INIT_SH, project / ".claude" / "init.sh")
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_")}
        env["HOOKS_DAEMON_ROOT_DIR"] = str(daemon_root)
        result = subprocess.run(
            ["bash", "-c", "source .claude/init.sh; _hooks_daemon_recovery_command restart"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode == 3:
            return None
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    @staticmethod
    def _layout(project: Path, layout: str) -> Path:
        """Build ``layout`` at ``project``; returns its daemon root."""

        def script(path: Path, body: str = "#!/bin/bash\n") -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)

        clone = project / _CLONE_LAUNCHER
        root_launcher = project / "bin" / "hooks-daemon"
        (project / ".claude").mkdir(parents=True)
        if layout == "client":
            script(clone)
            return project / ".claude" / "hooks-daemon"
        if layout == "client, own root tool":
            script(clone)
            script(root_launcher, "#!/bin/bash\necho the project's own\n")
            return project / ".claude" / "hooks-daemon"
        if layout == "client, no clone launcher, own root tool":
            script(root_launcher, "#!/bin/bash\necho the project's own\n")
            return project / ".claude" / "hooks-daemon"
        if layout == "self-install, clone linked":
            script(root_launcher)
            clone.parent.mkdir(parents=True)
            clone.symlink_to(root_launcher)
            return project
        if layout == "self-install, real clone file":
            script(root_launcher)
            script(clone)
            return project
        if layout == "root of another project":
            other = project.parent / f"{project.name}-other"
            script(other / _CLONE_LAUNCHER)
            return other / ".claude" / "hooks-daemon"
        if layout == "root whose launcher links to another file of the project":
            script(project / "any" / "file")
            elsewhere = project.parent / f"{project.name}-elsewhere"
            (elsewhere / "bin").mkdir(parents=True)
            (elsewhere / "bin" / "hooks-daemon").symlink_to(project / "any" / "file")
            return elsewhere
        raise AssertionError(layout)

    #: Layouts whose daemon root is no install of the project: nothing is exempt.
    _UNKNOWN_INSTALLS = frozenset(
        {"root of another project", "root whose launcher links to another file of the project"}
    )

    @pytest.mark.parametrize(
        "layout",
        [
            "client",
            "client, own root tool",
            "client, no clone launcher, own root tool",
            "self-install, clone linked",
            "self-install, real clone file",
            "root of another project",
            "root whose launcher links to another file of the project",
        ],
    )
    @pytest.mark.parametrize("dirname", ["proj", "with space"])
    def test_init_sh_the_relay_and_the_daemon_name_one_launcher(
        self, tmp_path: Path, wedged_pretooluse_socket: Path, layout: str, dirname: str
    ) -> None:
        """Plan 00466 round 4 (P3-2): the relay named the first launcher FILE
        that existed, so a client's own ``bin/hooks-daemon`` or a real file at
        a self-install's clone path could be named while the carve-out denied
        it. One rule, over one table, in all three.

        Round 5 (R4-2): a launcher is a ``bin/hooks-daemon``. A root whose
        launcher links to any other file two levels below the project was
        taken for this install, and that file then ran as the exempt
        restart."""
        project = tmp_path / dirname
        daemon_root = self._layout(project, layout)
        from_init_sh = self._init_sh_command(project, daemon_root)
        from_daemon = install_recovery_command(project, daemon_root, "restart")
        reason = self._own_deny_reason(project, wedged_pretooluse_socket, daemon_root)
        assert from_daemon == from_init_sh, (from_daemon, from_init_sh)
        assert (from_init_sh is None) == (layout in self._UNKNOWN_INSTALLS), from_init_sh
        if from_init_sh is None:
            assert "No daemon command is exempt" in reason, reason
        else:
            assert reason.endswith(f"run: {from_init_sh}"), reason

    @pytest.mark.parametrize(
        ("launcher", "daemon_root"),
        [
            # The daemon's own repository: the install is the project root.
            ("bin/hooks-daemon", "."),
            # A client project: the install is the daemon clone.
            (_CLONE_LAUNCHER, ".claude/hooks-daemon"),
        ],
    )
    @pytest.mark.parametrize("dirname", ["proj", "with space"])
    def test_it_names_the_command_init_sh_names(
        self,
        tmp_path: Path,
        wedged_pretooluse_socket: Path,
        launcher: str,
        daemon_root: str,
        dirname: str,
    ) -> None:
        project = tmp_path / dirname
        (project / launcher).parent.mkdir(parents=True)
        (project / launcher).write_text("#!/bin/bash\n")
        reason = self._own_deny_reason(project, wedged_pretooluse_socket, project / daemon_root)
        command = self._init_sh_command(project, project / daemon_root)
        assert command is not None
        assert command.endswith(" restart") and str(project) in command, command
        assert f"run: {command}" in reason, reason

    def test_with_both_launchers_it_names_the_clones_first(
        self, tmp_path: Path, wedged_pretooluse_socket: Path
    ) -> None:
        """Plan 00466 round 3 (m-A): ``cli.py``'s order. A client project's
        own ``bin/hooks-daemon`` is not the daemon, so it is never named. No
        daemon root is handed over, as from a forwarder generated before it
        was: the relay then takes init.sh's default, the daemon clone."""
        project = tmp_path / "proj"
        for launcher in (_CLONE_LAUNCHER, "bin/hooks-daemon"):
            (project / launcher).parent.mkdir(parents=True)
            (project / launcher).write_text("#!/bin/bash\n")
        reason = self._own_deny_reason(project, wedged_pretooluse_socket)
        command = self._init_sh_command(project, project / ".claude" / "hooks-daemon")
        assert command == f"{project / _CLONE_LAUNCHER} restart", command
        assert f"run: {command}" in reason, reason


# ---------------------------------------------------------------------------
# 2. binary-missing: guard's own -x test fails, falls straight through
# ---------------------------------------------------------------------------


def test_binary_missing_falls_through_to_legacy_path(
    tmp_path: Path, sock_path: Path, live_pid_file: Path
) -> None:
    untracked_dir = tmp_path / "untracked"
    transport = TransportConfig(
        relay_enabled=True, relay_binary=str(tmp_path / "does-not-exist" / "hooks-relay")
    )
    forwarder = _write_generated_forwarder(
        tmp_path, "pre-tool-use", "PreToolUse", transport, untracked_dir
    )
    assert "relay hot path" in forwarder.read_text()

    canned = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"ok"}}\n'
    server = _RecordingSocketServer(sock_path, canned)
    server.start()
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "pwd"}, **_MAIN_PROBE}
    ).encode()

    result = subprocess.run(
        ["bash", str(forwarder)],
        input=payload,
        capture_output=True,
        env=_base_env(sock_path, live_pid_file),
        timeout=_TIMEOUT_SECONDS,
    )
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None, "legacy transport was never reached"
    request = json.loads(server.received)
    assert request["hook_input"]["tool_input"]["command"] == "pwd"


# ---------------------------------------------------------------------------
# 3. nc-missing: nc rung skipped, python3 serves the request unchanged
# ---------------------------------------------------------------------------


def _make_broken_nc_dir(base: Path) -> str:
    """A dir holding an `nc` shim that always fails — simulates 'nc present on
    PATH but not actually Unix-socket-capable' (or genuinely broken), the
    real-world shape of "nc missing" (mirrors `_make_broken_jq_dir` in
    test_forwarder_jq_free.py: prepend, don't strip the whole PATH, so every
    other tool the forwarder needs stays reachable)."""
    shim_dir = base / "broken-nc-bin"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "nc"
    shim.write_text("#!/bin/sh\nexit 127\n")
    shim.chmod(0o755)
    return str(shim_dir)


def test_nc_missing_falls_back_to_python3_transport(
    tmp_path: Path, sock_path: Path, live_pid_file: Path
) -> None:
    """`nc` present on PATH but non-functional: the nc rung's empty-capture
    check degrades cleanly and the legacy python3 transport serves the
    request unchanged — the payload is genuinely REPLAYED, not lost."""
    untracked_dir = tmp_path / "untracked"
    transport = TransportConfig(nc_enabled=True)
    forwarder = _write_generated_forwarder(
        tmp_path, "pre-tool-use", "PreToolUse", transport, untracked_dir
    )
    assert '"pre-tool-use"' in forwarder.read_text()

    canned = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"ok"}}\n'
    server = _RecordingSocketServer(sock_path, canned)
    server.start()
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "echo hi"}, **_MAIN_PROBE}
    ).encode()

    env = _base_env(sock_path, live_pid_file)
    shim_dir = _make_broken_nc_dir(tmp_path)
    env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
    env["HOOKS_DAEMON_NC_UNIX_CAPABLE"] = "1"
    # No per-event socket exists either — belt and braces: even a working
    # `nc` would have nothing to connect to.

    result = subprocess.run(
        ["bash", str(forwarder)],
        input=payload,
        capture_output=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
    )
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None, "python3 transport was never reached"
    request = json.loads(server.received)
    assert request["event"] == "PreToolUse"
    assert request["hook_input"]["tool_input"]["command"] == "echo hi"


def test_nc_capability_flag_unset_skips_nc_rung(
    tmp_path: Path, sock_path: Path, live_pid_file: Path
) -> None:
    """HOOKS_DAEMON_NC_UNIX_CAPABLE unset (probe never recorded capability):
    nc rung's own gate is false, python3 serves the request unchanged — even
    if a real per-event socket coincidentally exists."""
    untracked_dir = tmp_path / "untracked"
    transport = TransportConfig(nc_enabled=True)
    forwarder = _write_generated_forwarder(
        tmp_path, "pre-tool-use", "PreToolUse", transport, untracked_dir
    )

    canned = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"ok"}}\n'
    server = _RecordingSocketServer(sock_path, canned)
    server.start()
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "true"}, **_MAIN_PROBE}
    ).encode()

    env = _base_env(sock_path, live_pid_file)
    env.pop("HOOKS_DAEMON_NC_UNIX_CAPABLE", None)

    result = subprocess.run(
        ["bash", str(forwarder)],
        input=payload,
        capture_output=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
    )
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None
    request = json.loads(server.received)
    assert request["hook_input"]["tool_input"]["command"] == "true"


def test_nc_rung_round_trip_completes_promptly(tmp_path: Path) -> None:
    """Regression (Plan 00290 Phase 6 measurement): the nc rung's `nc -U -w`
    invocation, missing `-N` (shutdown-on-stdin-EOF), never sent EOF to the
    daemon's EOF-framed per-event socket — the daemon never saw the
    half-close, never responded, and every nc-rung call hung for the full
    `-w` budget (~30s) before falling through to python3. This drives a
    REAL EOF-framed server (the daemon's actual per-event protocol —
    `_RecordingSocketServer` reads to EOF, then replies, exactly as
    DESIGN-socket-relay.md §2 specifies) bound at the literal per-event
    socket path the guard computes, and asserts the nc rung itself serves
    the request well within a few seconds — not the legacy socket, which is
    deliberately left unreachable here so a silent fall-through to python3
    would surface as a daemon-down error response instead of the nc
    server's canned reply."""
    # AF_UNIX paths are capped ~108 bytes, and pytest's own `tmp_path` fixture
    # nests too deep for the socket paths this test needs — a short-lived
    # directory directly under /tmp is required instead.
    short_root = Path(tempfile.mkdtemp(prefix="ncrt-"))
    try:
        untracked_dir = short_root / "untracked"
        transport = TransportConfig(nc_enabled=True)
        forwarder = _write_generated_forwarder(
            short_root, "pre-tool-use", "PreToolUse", transport, untracked_dir
        )

        # send_request_stdin resolves its nc socket at RUNTIME from
        # $HOOKS_DAEMON_ROOT_DIR/untracked + init.sh's own
        # `_get_hostname_suffix` (unlike the relay guard's `_rl_dir`, which
        # is baked in as a literal at generation time) — so the server must
        # bind where THAT computation actually lands, and
        # HOOKS_DAEMON_ROOT_DIR must point at our short_root tree rather
        # than the real repo checkout.
        # Use the daemon's OWN resolver rather than re-deriving the suffix here.
        # This line previously read `os.environ.get("HOSTNAME", "localhost")`,
        # which silently omits the middle rung of the resolution chain both real
        # sides implement: $HOSTNAME -> socket.gethostname() -> "localhost".
        # bash auto-populates $HOSTNAME as a SHELL variable without exporting
        # it, so on a GitHub runner init.sh resolved a real OS hostname while
        # this test resolved "localhost" — the server bound one path, the nc
        # rung dialled another, and the reachability assertion failed with no
        # hint that a hostname was involved. test_hostname_suffix_parity.py
        # already pins bash/Python agreement for the production helpers; nothing
        # was pinning a TEST that re-implements them.
        hostname_suffix = _get_hostname_suffix()
        events_dir = untracked_dir / f"events{hostname_suffix}"
        events_dir.mkdir(parents=True)
        event_sock = events_dir / "pre-tool-use.sock"
        canned = (
            b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"via-nc"}}'
        )
        server = _RecordingSocketServer(event_sock, canned)
        server.start()

        payload = json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "nc-roundtrip"}, **_MAIN_PROBE}
        ).encode()
        with _live_pid_file(short_root, tmp_path) as live_pid_file:
            env = _base_env(short_root / "no-such-legacy-daemon.sock", live_pid_file)
            env["HOOKS_DAEMON_NC_UNIX_CAPABLE"] = "1"

            start = time.monotonic()
            result = subprocess.run(
                ["bash", str(forwarder)],
                input=payload,
                capture_output=True,
                env=env,
                timeout=_TIMEOUT_SECONDS,
            )
            elapsed = time.monotonic() - start
        server.join()

        assert result.returncode == 0, result.stderr.decode()
        assert elapsed < 5.0, f"nc rung took {elapsed:.1f}s — the -N EOF-shutdown fix regressed"
        assert server.received is not None, "the nc rung's own EOF-framed socket was never reached"
        # The per-event socket protocol is unwrapped (DESIGN-socket-relay.md
        # §2): the daemon receives exactly the raw stdin payload, not the
        # legacy socket's {"event", "hook_input"} envelope.
        request = json.loads(server.received)
        assert request["tool_input"]["command"] == "nc-roundtrip"
        assert result.stdout.decode().strip() == canned.decode()
    finally:
        shutil.rmtree(short_root, ignore_errors=True)


def test_nc_rung_honours_events_dir_env_override(tmp_path: Path) -> None:
    """Task 2.5 (Plan 00295): HOOKS_DAEMON_EVENTS_DIR must outrank the
    natural `$_untracked_dir/events$_hostname_suffix` path the nc rung
    otherwise computes -- matching resolve_events_dir (transport_verify.py)
    and the relay guard's own `${HOOKS_DAEMON_EVENTS_DIR:-...}` precedence.
    The per-event socket is bound ONLY at the override location; a forwarder
    that still ignored the override would find nothing there and silently
    fall through to the (deliberately unreachable) legacy socket."""
    short_root = Path(tempfile.mkdtemp(prefix="ncenv-"))
    # Created before the try block, alongside short_root: the finally clause
    # below unconditionally cleans it up, so it must be bound even if a step
    # between here and its old creation point raised (it previously was not).
    override_events_dir = Path(tempfile.mkdtemp(prefix="ncenv-override-"))
    try:
        untracked_dir = short_root / "untracked"
        transport = TransportConfig(nc_enabled=True)
        forwarder = _write_generated_forwarder(
            short_root, "pre-tool-use", "PreToolUse", transport, untracked_dir
        )

        event_sock = override_events_dir / "pre-tool-use.sock"
        canned = (
            b'{"hookSpecificOutput":{"hookEventName":"PreToolUse",'
            b'"additionalContext":"via-env-override"}}'
        )
        server = _RecordingSocketServer(event_sock, canned)
        server.start()

        # The NATURAL (unset-override) events dir is deliberately left
        # without a socket, so a forwarder that ignored the override would
        # find nothing there and fall through to the legacy socket instead
        # of silently "succeeding" via the wrong path.
        payload = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "env-override-roundtrip"},
                **_MAIN_PROBE,
            }
        ).encode()
        with _live_pid_file(short_root, tmp_path) as live_pid_file:
            env = _base_env(short_root / "no-such-legacy-daemon.sock", live_pid_file)
            env["HOOKS_DAEMON_NC_UNIX_CAPABLE"] = "1"
            env["HOOKS_DAEMON_EVENTS_DIR"] = str(override_events_dir)

            result = subprocess.run(
                ["bash", str(forwarder)],
                input=payload,
                capture_output=True,
                env=env,
                timeout=_TIMEOUT_SECONDS,
            )
        server.join()

        assert result.returncode == 0, result.stderr.decode()
        assert server.received is not None, "the override events dir's socket was never reached"
        request = json.loads(server.received)
        assert request["tool_input"]["command"] == "env-override-roundtrip"
    finally:
        shutil.rmtree(short_root, ignore_errors=True)
        shutil.rmtree(override_events_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. --no-relay re-entry: loop-safety
# ---------------------------------------------------------------------------


def test_no_relay_reentry_skips_own_guard(
    tmp_path: Path, sock_path: Path, live_pid_file: Path
) -> None:
    """A forwarder invoked with `--no-relay` (exactly as the relay's own
    fallback exec does) must skip its guard entirely — even with a relay
    binary and socket that WOULD otherwise be tried — and go straight to the
    legacy path. This is the loop-safety property: without it, a relay
    exec'ing its own fallback would recurse into the relay forever."""
    untracked_dir = tmp_path / "untracked"
    # Point at a real, executable "relay" that would (wrongly) succeed if
    # ever invoked, and a real socket file, so the ONLY thing preventing a
    # second relay attempt is the --no-relay re-entry check itself.
    fake_relay = tmp_path / "would-loop-relay.sh"
    fake_relay.write_text("#!/bin/bash\necho SHOULD_NEVER_RUN >&2\nexit 99\n")
    fake_relay.chmod(0o755)
    events_dir = untracked_dir / "events"
    events_dir.mkdir(parents=True)
    loop_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    loop_sock.bind(str(events_dir / "pre-tool-use.sock"))
    loop_sock.listen(1)
    try:
        transport = TransportConfig(relay_enabled=True, relay_binary=str(fake_relay))
        forwarder = _write_generated_forwarder(
            tmp_path, "pre-tool-use", "PreToolUse", transport, untracked_dir
        )

        canned = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"ok"}}\n'
        server = _RecordingSocketServer(sock_path, canned)
        server.start()
        payload = json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "reentry"}, **_MAIN_PROBE}
        ).encode()

        env = _base_env(sock_path, live_pid_file)
        # Test-isolation fix (Plan 00290 Phase 6 dogfood finding): redirect
        # the guard's events dir via env instead of patching the generated
        # content's baked path.
        env["HOOKS_DAEMON_EVENTS_DIR"] = str(events_dir)
        result = subprocess.run(
            ["bash", str(forwarder), "--no-relay"],
            input=payload,
            capture_output=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
        )
        server.join()

        assert result.returncode == 0, result.stderr.decode()
        assert (
            b"SHOULD_NEVER_RUN" not in result.stderr
        ), "the fake relay ran despite --no-relay re-entry — loop-safety broken"
        assert server.received is not None, "legacy transport was never reached"
        request = json.loads(server.received)
        assert request["hook_input"]["tool_input"]["command"] == "reentry"
    finally:
        loop_sock.close()


# ---------------------------------------------------------------------------
# 5. Stop/SubagentStop exclusion: the exit-code-2 hard-block contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_pascal,event_file_name", [("Stop", "stop"), ("SubagentStop", "subagent-stop")]
)
def test_stop_events_keep_exit_code_2_contract_even_with_relay_enabled(
    event_pascal: str,
    event_file_name: str,
    tmp_path: Path,
    sock_path: Path,
    live_pid_file: Path,
) -> None:
    """Regression (Plan 00290 Phase 6 dogfood finding): a relay-enabled Stop/
    SubagentStop forwarder must still translate the daemon's
    `decision=block` JSON into exit code 2 (Claude Code's hard re-entry
    contract, Plan 00101 Phase 9) — never exec the relay directly, which has
    no equivalent of that translation.

    Proven adversarially: a relay binary and a listening per-event socket
    ARE present and WOULD be selected by the guard if the exclusion were
    ever broken — this fails loudly (wrong exit code / relay's own exit 99
    leaking through) rather than passing vacuously because nothing was
    reachable.
    """
    untracked_dir = tmp_path / "untracked"
    fake_relay = tmp_path / "would-bypass-relay.sh"
    fake_relay.write_text("#!/bin/bash\necho SHOULD_NEVER_RUN >&2\nexit 99\n")
    fake_relay.chmod(0o755)
    events_dir = untracked_dir / "events"
    events_dir.mkdir(parents=True)
    loop_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    loop_sock.bind(str(events_dir / f"{event_file_name}.sock"))
    loop_sock.listen(1)
    try:
        transport = TransportConfig(relay_enabled=True, relay_binary=str(fake_relay))
        forwarder = _write_generated_forwarder(
            tmp_path,
            event_file_name,
            event_pascal,
            transport,
            untracked_dir,
            template=_STOP_FORWARDER_TEMPLATE,
        )
        assert "relay hot path" not in forwarder.read_text()

        reason = "STOPPING BECAUSE: acceptance probe"
        server = _RecordingSocketServer(
            sock_path, json.dumps({"decision": "block", "reason": reason}).encode() + b"\n"
        )
        server.start()
        payload = json.dumps({"stop_hook_active": False}).encode()

        env = _base_env(sock_path, live_pid_file)
        env["HOOKS_DAEMON_EVENTS_DIR"] = str(events_dir)
        result = subprocess.run(
            ["bash", str(forwarder)],
            input=payload,
            capture_output=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
        )
        server.join()

        assert b"SHOULD_NEVER_RUN" not in result.stderr, "the relay ran for a Stop event"
        assert (
            result.returncode == 2
        ), f"expected hard re-entry exit 2, got {result.returncode}: {result.stderr.decode()}"
        assert reason in result.stderr.decode()
    finally:
        loop_sock.close()


# ---------------------------------------------------------------------------
# 6. Env-override test isolation: HOOKS_DAEMON_EVENTS_DIR / _RELAY_BINARY
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _RELAY_BINARY.exists(), reason="no built relay binary on this machine")
def test_env_override_redirects_relay_away_from_baked_default(
    tmp_path: Path, sock_path: Path, live_pid_file: Path
) -> None:
    """The guard's baked `_rl_dir`/default relay binary point at a location
    with NO working relay+socket; `HOOKS_DAEMON_EVENTS_DIR` +
    `HOOKS_DAEMON_RELAY_BINARY` redirect it to a fixture-controlled one, and
    the relay is genuinely used from there — proving the override actually
    takes effect at runtime, not just in the generated string."""
    baked_untracked_dir = tmp_path / "baked-nonexistent" / "untracked"
    transport = TransportConfig(relay_enabled=True, relay_binary=str(_RELAY_BINARY))
    forwarder = _write_generated_forwarder(
        tmp_path, "pre-tool-use", "PreToolUse", transport, baked_untracked_dir
    )
    assert str(baked_untracked_dir) in forwarder.read_text()

    override_events_dir = tmp_path / "override-events"
    override_events_dir.mkdir(parents=True)
    canned = (
        b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"via-override"}}'
    )
    server = _RecordingSocketServer(override_events_dir / "pre-tool-use.sock", canned)
    server.start()

    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "override-me"}, **_MAIN_PROBE}
    ).encode()
    env = _base_env(sock_path, live_pid_file)  # legacy socket deliberately unreachable
    env["HOOKS_DAEMON_EVENTS_DIR"] = str(override_events_dir)

    result = subprocess.run(
        ["bash", str(forwarder)],
        input=payload,
        capture_output=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
    )
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None, "the override events dir's socket was never reached"
    request = json.loads(server.received)
    assert request["tool_input"]["command"] == "override-me"


def test_env_override_absent_falls_through_to_legacy(
    tmp_path: Path, sock_path: Path, live_pid_file: Path
) -> None:
    """`HOOKS_DAEMON_EVENTS_DIR` pointed at an empty directory (no socket for
    this event): the guard's `-S` test is false regardless of what the baked
    default would have resolved to, and the legacy path is reached — the
    override decouples the test from whatever the baked default happens to
    be, in either direction."""
    untracked_dir = tmp_path / "untracked"
    transport = TransportConfig(relay_enabled=True, relay_binary=str(_RELAY_BINARY))
    forwarder = _write_generated_forwarder(
        tmp_path, "pre-tool-use", "PreToolUse", transport, untracked_dir
    )

    empty_override_dir = tmp_path / "empty-override-events"
    empty_override_dir.mkdir(parents=True)

    canned = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"ok"}}\n'
    server = _RecordingSocketServer(sock_path, canned)
    server.start()
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "no-override-sock"}, **_MAIN_PROBE}
    ).encode()

    env = _base_env(sock_path, live_pid_file)
    env["HOOKS_DAEMON_EVENTS_DIR"] = str(empty_override_dir)

    result = subprocess.run(
        ["bash", str(forwarder)],
        input=payload,
        capture_output=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
    )
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None, "legacy transport was never reached"
    request = json.loads(server.received)
    assert request["hook_input"]["tool_input"]["command"] == "no-override-sock"
