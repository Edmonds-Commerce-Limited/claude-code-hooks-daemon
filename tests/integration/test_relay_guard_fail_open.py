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
from claude_code_hooks_daemon.install.forwarder_generator import generate_forwarder_content

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / ".claude" / "init.sh"
_RELAY_BINARY = _REPO_ROOT / "untracked" / "relay-build" / "hooks-relay-x86_64-unknown-linux-musl"

_TIMEOUT_SECONDS = 15


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


def _write_generated_forwarder(
    tmp_path: Path,
    event_file_name: str,
    event_pascal: str,
    transport: TransportConfig,
    untracked_dir: Path,
) -> Path:
    source = _FORWARDER_TEMPLATE.format(event_pascal=event_pascal)
    content = generate_forwarder_content(source, event_file_name, transport, untracked_dir)
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


@pytest.fixture
def live_pid_file(tmp_path: Path) -> Path:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text(f"{os.getpid()}\n")
    return pid_path


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
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}).encode()

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
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "pwd"}}).encode()

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
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo hi"}}).encode()

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
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "true"}}).encode()

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


def test_nc_rung_round_trip_completes_promptly(live_pid_file: Path) -> None:
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
        hostname_suffix = "-" + os.environ.get("HOSTNAME", "localhost").lower().replace(" ", "-")
        events_dir = untracked_dir / f"events{hostname_suffix}"
        events_dir.mkdir(parents=True)
        event_sock = events_dir / "pre-tool-use.sock"
        canned = (
            b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"via-nc"}}'
        )
        server = _RecordingSocketServer(event_sock, canned)
        server.start()

        payload = json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "nc-roundtrip"}}
        ).encode()
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
        # Rewrite the guard's socket suffix computation target to match our
        # unsuffixed test layout: patch _rl_sock's directory to the literal
        # events dir we created (no hostname suffix complexity needed here).
        content = forwarder.read_text()
        content = content.replace(
            '_rl_sock="$_rl_dir/events$_rl_sfx/pre-tool-use.sock"',
            f'_rl_sock="{events_dir}/pre-tool-use.sock"',
        )
        forwarder.write_text(content)

        canned = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"ok"}}\n'
        server = _RecordingSocketServer(sock_path, canned)
        server.start()
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "reentry"}}).encode()

        env = _base_env(sock_path, live_pid_file)
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
