r"""Plan 00466 N34 — the per-handler chain deadline, end to end against an isolated daemon.

``HandlerChain.execute``'s own deadline check (Plan 00466 N25) only ran
BETWEEN handlers, so a handler slow within its own ``matches()``/``handle()``
call reproduced exactly the bypass N25 exists to close (``secret_file_guard``
measured at 48.958s on 4 MB, past both the 20s chain deadline and the
client's own 30s socket timeout). N34 bounds each handler's own call too, via
``core.bounded_dispatch.BoundedDispatcher``.

This file is the live-socket gate: it proves the fix reaches an ACTUAL
running daemon process, not just the unit-level chain/dispatcher wiring
(``tests/unit/core/test_chain.py``, ``tests/unit/core/test_bounded_dispatch.py``).
It starts its OWN isolated daemon (the same pattern
``tests/integration/test_daemon_smoke.py`` and
``tests/integration/test_n24_strict_mode_probe_isolated_daemon.py`` use)
configured with a SHORT chain deadline, and a probe handler that sleeps far
longer than it -- then measures the ROUND-TRIP time on the real socket to
show the client gets its deny back near the configured deadline, not after
the probe's own sleep and not anywhere near the client's own 30s timeout.

The probe raises... no -- SLEEPS, only for a payload marked
``synthetic_source: n34-probe``, a field no real Claude Code session ever
sends (see ``daemon/synthetic_traffic.py``), so this never fires on ordinary
traffic.
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

_DENY = "deny"
_PROBE_MARKER = "n34-probe"

# Comfortably above the configured chain deadline (below) so the probe's
# sleep would be trivially observable if the deadline failed to bound it,
# and comfortably under the client's own 30s socket timeout either way.
_PROBE_SLEEP_SECONDS = 8.0
_CONFIGURED_DEADLINE_SECONDS = 1.0

#: The probe handler's full source, written into the isolated daemon's own
#: `.claude/project-handlers/pre_tool_use/` before it starts. Test-fixture
#: only, same rationale as the N24 strict_mode probe this file is modelled on.
_PROBE_HANDLER_SOURCE = f'''\
"""N34 chain-deadline acceptance probe (Plan 00466 N34) — test-fixture only."""

import time
from typing import Any

from claude_code_hooks_daemon.core import GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.daemon.synthetic_traffic import event_synthetic_source

_PROBE_MARKER = "{_PROBE_MARKER}"


class N34DeadlineProbeHandler(PreToolUseHandlerBase):
    """Sleep far past the configured chain deadline, tagged SAFETY+BLOCKING."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="n34-deadline-probe",
            priority=5,
            terminal=True,
            tags=["safety", "blocking", "project", "test"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return event_synthetic_source(hook_input) == _PROBE_MARKER

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        time.sleep({_PROBE_SLEEP_SECONDS})
        return GatingResult(decision="allow")

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []
'''


@pytest.fixture
def deadline_probe_daemon_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """An isolated project: git repo, a short chain deadline, the N34 probe handler."""
    test_id = tmp_path.name[-20:]
    socket_path = Path(f"/tmp/test-n34-probe-{test_id}.sock")
    pid_path = Path(f"/tmp/test-n34-probe-{test_id}.pid")
    log_path = Path(f"/tmp/test-n34-probe-{test_id}.log")

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
    (config_dir / "hooks-daemon.yaml").write_text(f"""
version: '1.0'
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  self_install_mode: true
  chain:
    deadline_seconds: {_CONFIGURED_DEADLINE_SECONDS}
project_handlers:
  enabled: true
  path: .claude/project-handlers
handlers:
  pre_tool_use: {{}}
  post_tool_use: {{}}
  session_start: {{}}
""")

    probe_dir = config_dir / "project-handlers" / "pre_tool_use"
    probe_dir.mkdir(parents=True)
    (probe_dir / "n34_deadline_probe.py").write_text(_PROBE_HANDLER_SOURCE)

    return {
        "project_root": tmp_path,
        "socket_path": socket_path,
    }


@pytest.fixture
def deadline_probe_daemon_process(deadline_probe_daemon_env: dict[str, Any]):
    """Start the isolated daemon and ensure it is stopped after the test."""
    project_root = deadline_probe_daemon_env["project_root"]
    test_env = os.environ.copy()

    start_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "start"]
    with open("/dev/null", "w") as devnull:
        result = subprocess.run(
            start_cmd,
            cwd=project_root,
            env=test_env,
            stdout=devnull,
            stderr=devnull,
            timeout=Timeout.DISPATCH_TEST_OUTER_BOUND,
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

    yield deadline_probe_daemon_env

    stop_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "stop"]
    subprocess.run(
        stop_cmd,
        cwd=project_root,
        env=test_env,
        capture_output=True,
        timeout=Timeout.SOCKET_CONNECT,
    )
    # The probe's own straggler thread is still sleeping inside the daemon
    # process at this point (N34 abandons it, by design) -- give the
    # subprocess a moment to actually exit before the next test reuses the
    # socket/pid paths.
    time.sleep(_PROBE_SLEEP_SECONDS)


def _send_pre_tool_use(sock_path: Path, cwd: Path, *, synthetic_source: str | None) -> dict:
    """Send a PreToolUse Bash event and return the daemon response.

    ``settimeout`` deliberately mirrors the REAL client's own socket timeout
    (``Timeout.SOCKET_DISPATCH_ROUNDTRIP``, 30s) rather than some shorter
    test-only budget: the whole point of this test is showing the response
    comes back well within that real budget, not a relaxed one.
    """
    hook_input: dict[str, object] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "true"},
        "cwd": str(cwd),
    }
    if synthetic_source is not None:
        hook_input["synthetic_source"] = synthetic_source

    payload = {"event": "PreToolUse", "hook_input": hook_input}
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


def _decision(response: dict) -> str:
    return str(response.get("hookSpecificOutput", {}).get("permissionDecision", ""))


def _reason(response: dict) -> str:
    return str(response.get("hookSpecificOutput", {}).get("permissionDecisionReason", ""))


def test_client_receives_the_deny_near_the_deadline_not_after_the_probes_sleep(
    deadline_probe_daemon_process: dict[str, Any],
) -> None:
    """The core N34 claim: bounded by the DEADLINE, not the handler's sleep.

    If N34 ever regresses to N25-only enforcement (checked only BETWEEN
    handlers), this call is the FIRST and ONLY matching handler, so nothing
    would bound its own execution -- the round trip would take roughly
    ``_PROBE_SLEEP_SECONDS`` (8s) instead of roughly
    ``_CONFIGURED_DEADLINE_SECONDS`` (1s), and this assertion would fail.

    Plan 00466 N40 m1: the WHOLE chain (here, just this one probe handler)
    is dispatched as ONE call, not one per handler -- the deny names
    "chain", not ``n34-deadline-probe`` specifically, since nothing is left
    on the calling thread that could still say which handler overran. See
    ``tests/unit/core/test_chain.py``'s module-level note on the redesign.
    """
    project_root = deadline_probe_daemon_process["project_root"]
    socket_path = deadline_probe_daemon_process["socket_path"]

    start = time.perf_counter()
    response = _send_pre_tool_use(socket_path, project_root, synthetic_source=_PROBE_MARKER)
    elapsed = time.perf_counter() - start

    assert _decision(response) == _DENY, (
        f"A handler that oversleeps its own dispatch budget must be denied "
        f"(not judged in time). Got: {response!r}"
    )
    assert "chain" in _reason(
        response
    ), f"Deny reason must say the CHAIN was not judged in time. Got: {_reason(response)!r}"
    assert "not judged in time" in _reason(response).lower()
    # Generous margin above the 1s configured deadline for process/socket
    # overhead, but nowhere near the probe's own 8s sleep or the client's
    # real 30s timeout -- the whole point of this test.
    assert elapsed < 5.0, (
        f"Round trip took {elapsed:.2f}s -- expected close to the "
        f"{_CONFIGURED_DEADLINE_SECONDS}s configured deadline, not the probe's "
        f"own {_PROBE_SLEEP_SECONDS}s sleep."
    )


def test_an_unmarked_payload_is_not_denied_by_the_probe(
    deadline_probe_daemon_process: dict[str, Any],
) -> None:
    """Negative control: the probe never fires on ordinary traffic."""
    project_root = deadline_probe_daemon_process["project_root"]
    socket_path = deadline_probe_daemon_process["socket_path"]

    start = time.perf_counter()
    response = _send_pre_tool_use(socket_path, project_root, synthetic_source=None)
    elapsed = time.perf_counter() - start

    assert "n34-deadline-probe" not in _reason(response), (
        f"An ordinary payload (no synthetic_source marker) must never trip "
        f"the N34 probe handler. Got: {response!r}"
    )
    # Not DENY -- an ordinary "true" Bash command with no probe marker. An
    # explicit "allow" string is not asserted: a genuine allow with nothing
    # to say may carry no permissionDecision field at all, only its absence.
    assert _decision(response) != _DENY, response
    assert elapsed < 5.0
