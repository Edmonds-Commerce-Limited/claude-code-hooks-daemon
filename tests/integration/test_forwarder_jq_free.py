"""Integration tests for the jq-free hook forwarder transport (Plan 00156, T2).

These tests pin the safety-critical per-event transport contract while the
`jq` dependency is removed from the hook wrappers. The JSON wrap/unwrap that
`jq` used to perform moves into the `python3` transport that every wrapper
already spawns (`send_request_stdin`).

Invariants pinned here:

1. **No jq in the hot path** — the deployed `.claude/hooks/*` wrappers and the
   `send_request_stdin` / `forward_stop_event` transport in `init.sh` contain no
   `jq` invocation (jq may remain only in `emit_hook_error`'s pure-error path).
2. **Wrapping is preserved** — a wrapper still sends
   ``{"event": "<Event>", "hook_input": <stdin payload>}`` to the daemon socket.
3. **jq-free operation** — with `jq` absent from ``PATH`` the wrappers still
   produce the correct request and relay the daemon's response.
4. **Control-character fidelity** — newlines/tabs/unicode inside the payload
   survive the round-trip (the reason JSON must never pass through a shell var).
5. **Status line** injects ``hook_event_name: "Status"`` and extracts ``.text``.
6. **Stop contract** — ``decision=block`` → exit 2 + reason on stderr;
   otherwise exit 0.

The tests drive the REAL deployed wrappers end-to-end against a fake Unix-socket
server, using the pytest process PID as a live "daemon" so ``ensure_daemon``'s
``is_daemon_running`` gate short-circuits without spawning a real daemon.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"
_INIT_SH = _REPO_ROOT / ".claude" / "init.sh"

# Test-harness timeouts (seconds). Generous — these guard against a hung
# subprocess/socket, not real latency.
_WRAPPER_TIMEOUT_SECONDS = 30
_SERVER_TIMEOUT_SECONDS = 10.0

# Wrappers that forward a single event through send_request_stdin. status-line,
# stop and subagent-stop have bespoke response/exit handling and are tested
# separately.
_STANDARD_WRAPPERS: dict[str, str] = {
    "pre-tool-use": "PreToolUse",
    "post-tool-use": "PostToolUse",
    "session-start": "SessionStart",
    "session-end": "SessionEnd",
    "pre-compact": "PreCompact",
    "user-prompt-submit": "UserPromptSubmit",
    "notification": "Notification",
    "permission-request": "PermissionRequest",
}


class _RecordingSocketServer:
    """Minimal Unix-socket server: records one request, replies canned bytes."""

    def __init__(self, sock_path: Path, response: bytes) -> None:
        self.sock_path = sock_path
        self.response = response
        self.received: bytes | None = None
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.settimeout(_SERVER_TIMEOUT_SECONDS)
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

    def join(self, timeout: float = _SERVER_TIMEOUT_SECONDS) -> None:
        self._thread.join(timeout)

    def close(self) -> None:
        self._srv.close()


def _make_broken_jq_dir(base: Path) -> str:
    """Create a dir holding a ``jq`` shim that fails if invoked.

    Prepending this to ``PATH`` simulates jq-absence robustly: bash, python3 and
    every other tool stay reachable on the real PATH, but any actual ``jq`` call
    aborts with exit 127. A wrapper that no longer depends on jq is unaffected.
    """
    shim_dir = base / "nojq-bin"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "jq"
    shim.write_text('#!/bin/sh\necho "jq must not be called (Plan 00156)" >&2\nexit 127\n')
    shim.chmod(0o755)
    return str(shim_dir)


def _run_wrapper(
    wrapper: str,
    payload: bytes,
    sock_path: Path,
    pid_path: Path,
    *,
    strip_jq: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    """Invoke a deployed wrapper against a fake live daemon socket."""
    env = os.environ.copy()
    # ESTABLISH THE PREMISE the wrapper needs, rather than inheriting it.
    #
    # `init.sh` refuses to run inside the hooks-daemon repo unless self-install
    # is evident, and it accepts either `HOOKS_DAEMON_ROOT_DIR == PROJECT_PATH`
    # or the presence of `.claude/hooks-daemon.env`. That `.env` is GITIGNORED,
    # so on a developer's self-installed tree the guard passed by accident and
    # on a fresh checkout it did not: every test here failed in CI with
    # `hooks_daemon_repo_detected` while passing locally. Setting the variable
    # explicitly is not a workaround — it is exactly what the untracked `.env`
    # sets in a real self-install session.
    env["HOOKS_DAEMON_ROOT_DIR"] = str(_REPO_ROOT)
    env["CLAUDE_HOOKS_SOCKET_PATH"] = str(sock_path)
    env["CLAUDE_HOOKS_PID_PATH"] = str(pid_path)
    if strip_jq:
        shim_dir = _make_broken_jq_dir(pid_path.parent)
        env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        ["bash", str(_HOOKS_DIR / wrapper)],
        input=payload,
        capture_output=True,
        env=env,
        timeout=_WRAPPER_TIMEOUT_SECONDS,
    )


@pytest.fixture
def live_pid_file(tmp_path: Path) -> Path:
    """A PID file naming a live process so is_daemon_running() returns true."""
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
# 1. No jq anywhere in the hot transport path
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    """Remove shell/python comments so prose mentioning ``jq`` is not matched.

    Drops whole-line comments (first non-space char is ``#``) and inline
    comments (a ``#`` preceded by whitespace — which never happens inside
    ``${var#pattern}`` parameter expansions, where ``#`` follows a word char).
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        hash_at = line.find(" #")
        if hash_at != -1:
            line = line[:hash_at]
        out.append(line)
    return "\n".join(out)


def _contains_jq_invocation(text: str) -> bool:
    """True if ``jq`` is invoked as a command (not merely mentioned in docs).

    Comments are stripped first, then ``jq`` is only flagged at a shell command
    position — the start of a line or immediately after a pipe. Every real jq
    call in these scripts appears that way (``jq -c '...'`` or ``... | jq -r``),
    while prose/docstring mentions of jq sit mid-sentence and are ignored.
    """
    import re

    return re.search(r"(?m)(?:^|\|)[ \t]*jq\b", _strip_comments(text)) is not None


def test_deployed_wrappers_contain_no_jq() -> None:
    """No deployed wrapper may invoke jq — the transport wraps/unwraps itself."""
    offenders: list[str] = []
    for hook_file in _HOOKS_DIR.iterdir():
        if not hook_file.is_file() or hook_file.name.endswith(".bak"):
            continue
        if _contains_jq_invocation(hook_file.read_text()):
            offenders.append(hook_file.name)
    assert offenders == [], f"jq still invoked in wrappers: {offenders}"


def test_init_transport_functions_contain_no_jq() -> None:
    """No definition of send_request_stdin / forward_stop_event may invoke jq.

    init.sh defines send_request_stdin three times (the main transport plus two
    daemon-unavailable overrides) — every one must be jq-free. jq is permitted
    only in emit_hook_error's pure-error path (not asserted here).
    """
    text = _INIT_SH.read_text()

    def _bodies(func: str) -> list[str]:
        marker = f"{func}() {{"
        bodies: list[str] = []
        search_from = 0
        while True:
            start = text.find(marker, search_from)
            if start == -1:
                break
            depth = 0
            end = len(text)
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            bodies.append(text[start:end])
            search_from = end
        return bodies

    for func in ("send_request_stdin", "forward_stop_event"):
        found = _bodies(func)
        assert found, f"no definition of {func} found in init.sh"
        for body in found:
            assert not _contains_jq_invocation(body), f"jq still invoked in {func}"


# ---------------------------------------------------------------------------
# 2 + 3. Wrapping preserved, works without jq
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
@pytest.mark.parametrize("wrapper,event", list(_STANDARD_WRAPPERS.items()))
def test_standard_wrapper_wraps_payload(
    wrapper: str,
    event: str,
    strip_jq: bool,
    sock_path: Path,
    live_pid_file: Path,
) -> None:
    """Each wrapper sends {event, hook_input:<payload>}, with or without jq."""
    canned = (
        b'{"hookSpecificOutput":{"hookEventName":"'
        + event.encode()
        + b'","additionalContext":"ok"}}\n'
    )
    server = _RecordingSocketServer(sock_path, canned)
    server.start()
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}).encode()

    result = _run_wrapper(wrapper, payload, sock_path, live_pid_file, strip_jq=strip_jq)
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None, "daemon socket received nothing"
    request = json.loads(server.received)
    assert request["event"] == event
    assert request["hook_input"] == {"tool_name": "Bash", "tool_input": {"command": "ls"}}


# ---------------------------------------------------------------------------
# 4. Control-character fidelity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
def test_control_characters_survive_round_trip(
    strip_jq: bool, sock_path: Path, live_pid_file: Path
) -> None:
    """Newlines/tabs/unicode inside the payload survive wrapping intact."""
    tricky = 'line1\nline2\ttab "quote" \\ backslash — unicode 🚀'
    server = _RecordingSocketServer(sock_path, b"{}\n")
    server.start()
    payload = json.dumps({"tool_input": {"command": tricky}}).encode()

    result = _run_wrapper("pre-tool-use", payload, sock_path, live_pid_file, strip_jq=strip_jq)
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None
    request = json.loads(server.received)
    assert request["hook_input"]["tool_input"]["command"] == tricky


# ---------------------------------------------------------------------------
# 5. Status line: inject hook_event_name, extract .text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
def test_status_line_injects_event_and_extracts_text(
    strip_jq: bool, sock_path: Path, live_pid_file: Path
) -> None:
    server = _RecordingSocketServer(sock_path, b'{"text":"my-status-line"}\n')
    server.start()
    payload = json.dumps({"model": {"display_name": "Opus"}}).encode()

    result = _run_wrapper("status-line", payload, sock_path, live_pid_file, strip_jq=strip_jq)
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None
    request = json.loads(server.received)
    assert request["event"] == "Status"
    assert request["hook_input"]["hook_event_name"] == "Status"
    assert result.stdout.decode().strip() == "my-status-line"


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
def test_status_line_reports_error_field(
    strip_jq: bool, sock_path: Path, live_pid_file: Path
) -> None:
    server = _RecordingSocketServer(sock_path, b'{"error":"boom"}\n')
    server.start()
    payload = json.dumps({"model": {}}).encode()

    result = _run_wrapper("status-line", payload, sock_path, live_pid_file, strip_jq=strip_jq)
    server.join()

    assert result.returncode == 0, result.stderr.decode()
    assert "boom" in result.stdout.decode()


# ---------------------------------------------------------------------------
# 6. Stop contract: block -> exit 2 + stderr reason; allow -> exit 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
@pytest.mark.parametrize("wrapper", ["stop", "subagent-stop"])
def test_stop_block_exits_2_with_reason(
    wrapper: str, strip_jq: bool, sock_path: Path, live_pid_file: Path
) -> None:
    reason = "STOPPING BECAUSE: not yet"
    server = _RecordingSocketServer(
        sock_path, json.dumps({"decision": "block", "reason": reason}).encode() + b"\n"
    )
    server.start()
    payload = json.dumps({"stop_hook_active": False}).encode()

    result = _run_wrapper(wrapper, payload, sock_path, live_pid_file, strip_jq=strip_jq)
    server.join()

    assert result.returncode == 2, f"expected hard re-entry exit 2, got {result.returncode}"
    assert reason in result.stderr.decode()


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
@pytest.mark.parametrize("wrapper", ["stop", "subagent-stop"])
def test_stop_allow_exits_0(
    wrapper: str, strip_jq: bool, sock_path: Path, live_pid_file: Path
) -> None:
    server = _RecordingSocketServer(sock_path, json.dumps({"decision": "approve"}).encode() + b"\n")
    server.start()
    payload = json.dumps({"stop_hook_active": False}).encode()

    result = _run_wrapper(wrapper, payload, sock_path, live_pid_file, strip_jq=strip_jq)
    server.join()

    assert result.returncode == 0, result.stderr.decode()


# ---------------------------------------------------------------------------
# 7. Malformed-payload behaviour (Plan 00156 review, findings 1 & 5)
#
# json.loads is the one branch whose behaviour diverges from the old jq path:
# a non-JSON stdin payload. Non-Stop events fail OPEN (advisory context, exit 0);
# Stop/SubagentStop fail CLOSED (decision=block -> exit 2). Both are pinned here
# so the divergence can never silently regress into a block->allow safety hole.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
def test_malformed_payload_standard_wrapper_fails_open(
    strip_jq: bool, sock_path: Path, live_pid_file: Path
) -> None:
    """A non-JSON payload on a normal event exits 0 with advisory context.

    The parse fails before the socket is touched, so no server is needed. The
    context must flag the invalid payload and must NOT tell the agent the daemon
    is down / to restart it (review finding 1) — the daemon is fine.
    """
    result = _run_wrapper(
        "pre-tool-use", b"not json {", sock_path, live_pid_file, strip_jq=strip_jq
    )

    assert result.returncode == 0, result.stderr.decode()
    response = json.loads(result.stdout.decode())
    context = response["hookSpecificOutput"]["additionalContext"]
    assert "invalid_hook_input" in context or "not valid JSON" in context
    assert "Not currently running" not in context
    assert "restart the daemon" not in context.lower()


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
@pytest.mark.parametrize("wrapper", ["stop", "subagent-stop"])
def test_malformed_payload_stop_wrapper_fails_closed(
    wrapper: str, strip_jq: bool, sock_path: Path, live_pid_file: Path
) -> None:
    """A non-JSON payload on a Stop event fails CLOSED: exit 2 (hard re-entry).

    Load-bearing safety property: a garbled Stop payload must never let the agent
    stop silently — it degrades to the same block the daemon-down path produces.
    """
    result = _run_wrapper(wrapper, b"not json {", sock_path, live_pid_file, strip_jq=strip_jq)

    assert result.returncode == 2, f"expected fail-closed exit 2, got {result.returncode}"


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
@pytest.mark.parametrize("wrapper", ["stop", "subagent-stop"])
def test_malformed_payload_stop_reason_is_accurate(
    wrapper: str, strip_jq: bool, sock_path: Path, live_pid_file: Path
) -> None:
    """A malformed Stop payload fails closed, but the block reason must be honest.

    The parse fails client-side before the socket is touched, so the daemon is
    almost certainly healthy. The old reason claimed 'Hooks daemon not running'
    (Plan 00157 review follow-up) — cosmetically wrong for this case. The reason
    must describe the malformed payload, not a phantom daemon-down. It surfaces on
    stderr: forward_stop_event prints .reason before exiting 2.
    """
    result = _run_wrapper(wrapper, b"not json {", sock_path, live_pid_file, strip_jq=strip_jq)

    assert result.returncode == 2, f"expected fail-closed exit 2, got {result.returncode}"
    stderr = result.stderr.decode().lower()
    assert "not running" not in stderr, stderr
    assert "malformed" in stderr, stderr


@pytest.mark.parametrize("strip_jq", [False, True], ids=["with-jq", "no-jq"])
def test_status_line_transport_failure_emits_stderr_diagnostic(
    strip_jq: bool, tmp_path: Path, live_pid_file: Path
) -> None:
    """A mid-render socket failure still renders the fallback AND logs to stderr.

    Review finding 3: the status branch of fail() must not silently swallow the
    diagnostic (project "no silent error suppression" standard). The pid file is
    live (ensure_daemon proceeds) but the socket does not exist, so the transport
    raises FileNotFoundError inside send_request_stdin.
    """
    missing_sock = tmp_path / "no-such-daemon.sock"  # never created -> connect fails
    result = _run_wrapper(
        "status-line", b'{"model":{}}', missing_sock, live_pid_file, strip_jq=strip_jq
    )

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.decode().strip() == "⚠️ NO STATUS DATA"
    assert "HOOKS DAEMON ERROR" in result.stderr.decode()


def test_precondition_jq_is_installed() -> None:
    """Visibility marker for the with-jq parametrisations.

    Not a behaviour assertion — the with-jq/no-jq matrix above already exercises
    both paths. This skips (rather than passing silently) when jq is absent so the
    test report surfaces that the with-jq parametrisations did not run.
    """
    if shutil.which("jq") is None:
        pytest.skip("jq not installed — with-jq parametrisations were skipped")
