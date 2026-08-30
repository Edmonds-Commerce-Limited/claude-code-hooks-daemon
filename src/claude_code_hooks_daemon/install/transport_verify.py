"""Real-invocation-context verification probes for the transport toggle (Plan 00294).

Every toggle of ``daemon.transport.relay_enabled`` must be verified in the
HOST's own invocation manner before it is trusted — the Plan 00290 dogfood
shipped four defects live while every test surface was green, because each
surface invoked the hooks differently from how Claude Code does
(``CLAUDE/development/LESSONS.md`` "Test in the host's invocation context").
The probes here pin all three host-boundary contracts:

1. **How the host calls you**: stdin is a genuine SOCKET (socketpair +
   ``SHUT_WR``, the manner of ``tests/integration/test_forwarder_socket_stdin.py``),
   never a pipe — a ``< /dev/stdin`` re-open fails ENXIO only on a socket.
2. **What the host sends**: payloads are what Claude Code actually sends,
   with nothing hand-added that any layer under test injects (the status-line
   payload deliberately carries no ``hook_event_name``).
3. **What the host does with the answer**: a PreToolUse answer must parse as
   a JSON decision object, a status-line answer must be RAW text (raw_stdout
   contract), and a blockable Stop must exit 2 with the reason on stderr
   (the Plan 00101 Phase 9 hard-reentry contract).

Plus two state checks: the deployed forwarders' guard blocks match the
configured transport state, and the daemon's per-event listeners are bound
(relay on) or not serving (relay off).
"""

from __future__ import annotations

import json
import logging
import os
import socket

# SECURITY: subprocess runs only ["bash", <repo-owned forwarder path>] with a
# fixed argument list, no shell, no user input, and a bounded timeout.
import subprocess  # nosec B404
import tempfile
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.events import wired_event_metas
from claude_code_hooks_daemon.daemon.paths import (
    get_event_socket_dir,
    get_event_socket_dir_from_untracked,
)
from claude_code_hooks_daemon.install.forwarder_generator import (
    RELAY_EXCLUDED_EVENT_FILE_NAMES,
    load_transport_config,
    strip_relay_guard_block,
)
from claude_code_hooks_daemon.install.relay_deploy import resolve_relay_binary_path

logger = logging.getLogger(__name__)

#: Per-probe subprocess budget, seconds — matches the socket-stdin
#: integration suite's own bound, and keeps the whole verification pass
#: bounded even when a forwarder hangs.
PROBE_TIMEOUT_SECONDS = 60

#: Bytes echoed into a probe's failure detail — enough to diagnose, small
#: enough to keep a toggle's output readable.
_DETAIL_SNIPPET_BYTES = 400

_ENXIO_MARKER = b"No such device or address"
_DAEMON_ERROR_MARKER = b"HOOKS DAEMON ERROR"

_EXIT_HARD_BLOCK = 2

#: Marker text present in every generated relay guard block (the header
#: comment ``forwarder_generator`` emits verbatim).
_GUARD_MARKER = "relay hot path"

_PROBE_SESSION_ID = "transport-toggle-probe"


@dataclass(frozen=True)
class ProbeResult:
    """One verification probe's outcome."""

    name: str
    passed: bool
    detail: str


def _pre_tool_use_payload() -> bytes:
    """A real PreToolUse payload — exactly the shape Claude Code sends."""
    return json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "hook_event_name": "PreToolUse",
            "session_id": _PROBE_SESSION_ID,
        }
    ).encode()


def _status_line_payload(project_root: Path) -> bytes:
    """A real status-line payload.

    Deliberately carries NO ``hook_event_name`` — Claude Code's real
    status-line payload never does (the transport/daemon is responsible for
    injecting it, which is exactly the enrichment defect the Plan 00290
    dogfood shipped). Hand-adding it here would validate the author's
    assumptions instead of the host's behaviour.
    """
    return json.dumps(
        {
            "session_id": _PROBE_SESSION_ID,
            "model": {"display_name": "Probe"},
            "workspace": {"current_dir": str(project_root)},
        }
    ).encode()


def run_forwarder_with_socket_stdin(
    forwarder: Path,
    payload: bytes,
    cwd: Path | None = None,
) -> tuple[int, bytes, bytes]:
    """Invoke ``forwarder`` with stdin genuinely being a SOCKET.

    The canonical probe manner (socketpair, sendall, ``SHUT_WR``, child fd as
    stdin) — a pipe-fed invocation cannot see the ``< /dev/stdin`` ENXIO
    class of defect this exists to catch.
    """
    return _run_argv_with_socket_stdin(["bash", str(forwarder)], payload, cwd=cwd)


def _run_argv_with_socket_stdin(
    argv: list[str],
    payload: bytes,
    cwd: Path | None = None,
) -> tuple[int, bytes, bytes]:
    parent, child = socket.socketpair()
    try:
        parent.sendall(payload)
        parent.shutdown(socket.SHUT_WR)
        # SECURITY: fixed argv (bash/relay binary + repo-owned paths), no
        # shell, no user input, bounded timeout.
        proc = subprocess.Popen(  # nosec B603 B607
            argv,
            stdin=child.fileno(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
        )
        child.close()
        out, err = proc.communicate(timeout=PROBE_TIMEOUT_SECONDS)
        return proc.returncode, out, err
    finally:
        parent.close()


def _snippet(raw: bytes) -> str:
    return raw[:_DETAIL_SNIPPET_BYTES].decode(errors="replace")


def _common_failures(returncode: int, out: bytes, err: bytes) -> str | None:
    """Failure shared by every socket-stdin probe, or None when clean."""
    if _ENXIO_MARKER in err:
        return f"stdin socket re-open failed (ENXIO): {_snippet(err)}"
    if _DAEMON_ERROR_MARKER in out:
        return f"transport emitted a daemon error: {_snippet(out)}"
    if returncode != 0:
        return f"exit={returncode} stderr={_snippet(err)}"
    return None


def probe_pre_tool_use(hooks_dir: Path) -> ProbeResult:
    """A relay-eligible event answers with a JSON decision object."""
    name = "pre-tool-use-json"
    forwarder = hooks_dir / "pre-tool-use"
    if not forwarder.is_file():
        return ProbeResult(name, False, f"forwarder missing: {forwarder}")
    try:
        returncode, out, err = run_forwarder_with_socket_stdin(
            forwarder, _pre_tool_use_payload(), cwd=hooks_dir
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(name, False, f"timed out after {PROBE_TIMEOUT_SECONDS}s")
    failure = _common_failures(returncode, out, err)
    if failure is not None:
        return ProbeResult(name, False, failure)
    try:
        parsed = json.loads(out.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ProbeResult(name, False, f"response is not JSON: {_snippet(out)}")
    if not isinstance(parsed, dict):
        return ProbeResult(name, False, f"response is not a JSON object: {_snippet(out)}")
    return ProbeResult(name, True, "JSON decision object received")


def probe_status_line(hooks_dir: Path) -> ProbeResult:
    """A raw_stdout event answers with RAW text, never a JSON envelope."""
    name = "status-line-raw"
    forwarder = hooks_dir / "status-line"
    if not forwarder.is_file():
        return ProbeResult(name, False, f"forwarder missing: {forwarder}")
    try:
        returncode, out, err = run_forwarder_with_socket_stdin(
            forwarder, _status_line_payload(hooks_dir.parent.parent), cwd=hooks_dir
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(name, False, f"timed out after {PROBE_TIMEOUT_SECONDS}s")
    failure = _common_failures(returncode, out, err)
    if failure is not None:
        return ProbeResult(name, False, failure)
    text = out.strip()
    if not text:
        return ProbeResult(name, False, "status line produced no output")
    if text.startswith(b"{"):
        try:
            envelope: object = json.loads(text.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            # The PASSING outcome, made explicit: brace-leading bytes that do
            # not decode as JSON are still raw text, which is exactly what
            # the raw_stdout contract wants on stdout.
            logger.debug(
                "status-line output starts with '{' but is not JSON (%s) — raw text, as required",
                exc,
            )
            envelope = None
        if isinstance(envelope, dict):
            return ProbeResult(
                name,
                False,
                f"raw_stdout event answered with a JSON envelope: {_snippet(out)}",
            )
    return ProbeResult(name, True, "raw text received")


def probe_stop_hard_block(hooks_dir: Path) -> ProbeResult:
    """A genuinely-blockable Stop exits 2 with the reason on stderr."""
    name = "stop-hard-block"
    forwarder = hooks_dir / "stop"
    if not forwarder.is_file():
        return ProbeResult(name, False, f"forwarder missing: {forwarder}")
    with tempfile.TemporaryDirectory(prefix="transport-probe-stop-") as tmp:
        isolated_cwd = Path(tmp)
        transcript = isolated_cwd / "transcript.jsonl"
        transcript.write_text("", encoding="utf-8")
        payload = json.dumps(
            {
                "hook_event_name": "Stop",
                "stop_hook_active": False,
                "transcript_path": str(transcript),
                "session_id": _PROBE_SESSION_ID,
                "cwd": str(isolated_cwd),
            }
        ).encode()
        try:
            returncode, out, err = run_forwarder_with_socket_stdin(
                forwarder, payload, cwd=isolated_cwd
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(name, False, f"timed out after {PROBE_TIMEOUT_SECONDS}s")
    if _ENXIO_MARKER in err:
        return ProbeResult(name, False, f"stdin socket re-open failed (ENXIO): {_snippet(err)}")
    if returncode != _EXIT_HARD_BLOCK:
        return ProbeResult(
            name,
            False,
            f"expected exit 2 on a blockable Stop, got exit={returncode} "
            f"stdout={_snippet(out)} stderr={_snippet(err)}",
        )
    try:
        parsed = json.loads(out.decode().strip())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ProbeResult(name, False, f"stdout is not the daemon JSON: {_snippet(out)}")
    if parsed.get("decision") != "block":
        return ProbeResult(name, False, f"stdout carries no block decision: {_snippet(out)}")
    reason = parsed.get("reason", "")
    if not reason or reason.encode() not in err:
        return ProbeResult(
            name,
            False,
            f"block reason not echoed to stderr: reason={reason!r} stderr={_snippet(err)}",
        )
    return ProbeResult(name, True, "exit 2 with reason on stderr")


def resolve_events_dir(project_root: Path) -> Path:
    """The per-event socket dir, honouring the same overrides the daemon and
    the generated guard honour (``HOOKS_DAEMON_EVENTS_DIR``, then the
    ``CLAUDE_HOOKS_SOCKET_PATH`` parent the daemon itself derives from)."""
    env_dir = os.environ.get("HOOKS_DAEMON_EVENTS_DIR")
    if env_dir:
        return Path(env_dir)
    socket_env = os.environ.get("CLAUDE_HOOKS_SOCKET_PATH")
    if socket_env:
        return get_event_socket_dir_from_untracked(Path(socket_env).parent)
    return get_event_socket_dir(project_root)


def probe_listener_count(project_root: Path) -> ProbeResult:
    """Relay on: every wired event has its per-event socket bound."""
    name = "listener-count"
    events_dir = resolve_events_dir(project_root)
    metas = wired_event_metas()
    missing = [
        meta.bash_key for meta in metas if not (events_dir / f"{meta.bash_key}.sock").is_socket()
    ]
    if missing:
        return ProbeResult(
            name,
            False,
            f"{len(metas) - len(missing)}/{len(metas)} per-event sockets bound in "
            f"{events_dir}; missing: {', '.join(sorted(missing))}",
        )
    return ProbeResult(name, True, f"{len(metas)}/{len(metas)} per-event sockets bound")


def probe_no_event_listeners(project_root: Path) -> ProbeResult:
    """Relay off: no per-event socket is still ACCEPTING connections.

    A stale socket FILE is harmless (the regenerated forwarders carry no
    guard to reach it); only a live listener means the daemon is still
    serving the relay path.
    """
    name = "no-event-listeners"
    events_dir = resolve_events_dir(project_root)
    live: list[str] = []
    for meta in wired_event_metas():
        socket_path = events_dir / f"{meta.bash_key}.sock"
        if not socket_path.is_socket():
            continue
        probe_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe_sock.settimeout(1.0)
        try:
            probe_sock.connect(str(socket_path))
        except OSError as exc:
            # The PASSING outcome, made explicit: a socket file nothing
            # accepts on is a stale leftover, not a live relay listener.
            logger.debug(
                "no listener accepting on %s (%s) — expected for the off state",
                socket_path,
                exc,
            )
            connected = False
        else:
            connected = True
        finally:
            probe_sock.close()
        if connected:
            live.append(meta.bash_key)
    if live:
        return ProbeResult(
            name, False, f"live per-event listeners still accepting: {', '.join(sorted(live))}"
        )
    return ProbeResult(name, True, "no live per-event listeners")


def probe_forwarder_guard_state(hooks_dir: Path, *, expect_relay: bool) -> ProbeResult:
    """The deployed forwarders' guard blocks match the configured state.

    Only the catalogue's WIRED forwarder file names are examined (canary run
    4, defect D1): clients legitimately ship their own files in
    ``.claude/hooks/`` (helper scripts, docs, their own hook handlers), and
    judging those as forwarders made verification fail on every real client.
    The expected file set derives from the event catalogue, never from
    directory contents.
    """
    name = "forwarder-guard-state"
    guarded: list[str] = []
    eligible_unguarded: list[str] = []
    excluded_guarded: list[str] = []
    for meta in wired_event_metas():
        path = hooks_dir / meta.bash_key
        if not path.is_file():
            continue
        content = path.read_text()
        has_guard = strip_relay_guard_block(content) != content
        if has_guard:
            guarded.append(meta.bash_key)
            if meta.bash_key in RELAY_EXCLUDED_EVENT_FILE_NAMES:
                excluded_guarded.append(meta.bash_key)
        elif meta.bash_key not in RELAY_EXCLUDED_EVENT_FILE_NAMES:
            eligible_unguarded.append(meta.bash_key)
    if expect_relay:
        if not guarded:
            return ProbeResult(
                name, False, f"no wired forwarder in {hooks_dir} carries a relay guard"
            )
        if excluded_guarded:
            return ProbeResult(
                name,
                False,
                f"relay-INELIGIBLE forwarders carry a guard (raw_stdout/stop "
                f"correctness regression): {', '.join(excluded_guarded)}",
            )
        if eligible_unguarded:
            return ProbeResult(
                name,
                False,
                f"relay-eligible forwarders missing their guard: {', '.join(eligible_unguarded)}",
            )
        return ProbeResult(name, True, f"{len(guarded)} wired forwarder(s) carry the relay guard")
    if guarded:
        return ProbeResult(
            name, False, f"wired forwarders still carry a relay guard: {', '.join(guarded)}"
        )
    return ProbeResult(name, True, "no wired forwarder carries a relay guard")


def probe_relay_rung_active(project_root: Path) -> ProbeResult:
    """Relay on: the relay BINARY itself answers, with fallback disabled.

    The forwarder-level probes exercise the whole ladder, so a broken or
    absent relay that silently falls through to the legacy transport still
    looks green there (canary run 4, defect D2). This probe drives the
    resolved relay binary directly against the pre-tool-use per-event socket
    with ``--no-fallback``, so only the relay rung itself can produce the
    answer.
    """
    name = "relay-rung-active"
    transport = load_transport_config(project_root)
    binary = resolve_relay_binary_path(project_root, transport)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return ProbeResult(name, False, f"relay binary missing or not executable: {binary}")
    socket_path = resolve_events_dir(project_root) / "pre-tool-use.sock"
    timeout_ms = transport.timeout_seconds * 1000
    try:
        returncode, out, err = _run_argv_with_socket_stdin(
            [
                str(binary),
                str(socket_path),
                "--timeout-ms",
                str(timeout_ms),
                "--no-fallback",
            ],
            _pre_tool_use_payload(),
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(name, False, f"relay timed out after {PROBE_TIMEOUT_SECONDS}s")
    if returncode != 0:
        return ProbeResult(
            name,
            False,
            f"relay (no-fallback) exited {returncode}: stderr={_snippet(err)}",
        )
    try:
        parsed = json.loads(out.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ProbeResult(name, False, f"relay response is not JSON: {_snippet(out)}")
    if not isinstance(parsed, dict):
        return ProbeResult(name, False, f"relay response is not a JSON object: {_snippet(out)}")
    return ProbeResult(name, True, "relay answered directly (fallback disabled)")


def run_probes(project_root: Path, hooks_dir: Path, *, expect_relay: bool) -> list[ProbeResult]:
    """Run the full verification pass for one transport state.

    Cheap state checks first, then the socket-stdin probes; every probe runs
    regardless of earlier failures so a toggle's failure report is complete
    rather than first-fault.
    """
    results = [probe_forwarder_guard_state(hooks_dir, expect_relay=expect_relay)]
    if expect_relay:
        results.append(probe_listener_count(project_root))
        results.append(probe_relay_rung_active(project_root))
    else:
        results.append(probe_no_event_listeners(project_root))
    results.append(probe_pre_tool_use(hooks_dir))
    results.append(probe_status_line(hooks_dir))
    results.append(probe_stop_hard_block(hooks_dir))
    return results
