r"""Plan 00466 N24 — ``daemon.strict_mode`` plumbing, end to end against an isolated daemon.

``daemon.strict_mode`` used to read ``self._config.strict_mode`` in
``DaemonController.process_event``, and ``self._config`` is never populated
by the real daemon startup path — so ``strict_mode: true`` in
``hooks-daemon.yaml`` never reached a live daemon: every handler that raised
was treated as "no match" (fail-open) regardless of the setting. That is
fixed at the source (``daemon/controller.py`` narrow-slice DI, mirrored into
``daemon/cli.py``'s ``_build_initialised_controller``), and is covered
directly by ``tests/unit/daemon/test_controller.py`` and
``tests/unit/daemon/test_cli_strict_mode_wiring.py``.

This file is the live-socket gate: it proves the fix reaches an ACTUAL
running daemon process, not just the unit-level DI wiring. It starts its OWN
isolated daemon (the same pattern ``tests/integration/test_daemon_smoke.py``
uses) rather than depending on this repository's own shared, already-running
daemon — a probe handler this narrow has no business being permanently
installed in this project's real ``.claude/project-handlers/`` (a
maintainer-visible directory meant for genuinely useful project handlers),
so the probe's source lives only in ``_PROBE_HANDLER_SOURCE`` below and is
written into the isolated daemon's own tmp project before it starts.

It deliberately avoids depending on any organically-crashing handler (a
fragile, separately tracked bug's lifecycle): the probe raises ONLY for a
payload marked ``synthetic_source: n24-probe`` — a field no real Claude Code
session ever sends (see ``daemon/synthetic_traffic.py``).
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
_PROBE_MARKER = "n24-probe"

#: The probe handler's full source, written into the isolated daemon's own
#: `.claude/project-handlers/pre_tool_use/` before it starts. Kept here
#: rather than as a permanent file in this repository's own project-handlers
#: tree: the probe exists only to prove strict_mode wiring end to end, and
#: has no ongoing use once this test has run.
_PROBE_HANDLER_SOURCE = '''\
"""N24 strict_mode acceptance probe (Plan 00466 N24) — test-fixture only."""

from typing import Any

from claude_code_hooks_daemon.core import GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.daemon.synthetic_traffic import event_synthetic_source

_PROBE_MARKER = "n24-probe"


class N24StrictModeProbeHandler(PreToolUseHandlerBase):
    """Deliberately raise for a payload only this test's own client sends."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="n24-strict-mode-probe",
            priority=5,
            terminal=False,
            tags=["project", "test"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return event_synthetic_source(hook_input) == _PROBE_MARKER

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        raise RuntimeError(
            "n24 probe: deliberate crash to verify daemon.strict_mode plumbing "
            "(Plan 00466 N24)"
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []
'''


@pytest.fixture
def strict_probe_daemon_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """An isolated project: git repo, strict_mode:true config, the N24 probe handler.

    Mirrors ``tests/integration/test_daemon_smoke.py``'s ``daemon_env``, plus
    ``daemon.strict_mode: true`` and the probe handler file the tests below
    depend on.
    """
    test_id = tmp_path.name[-20:]
    socket_path = Path(f"/tmp/test-n24-probe-{test_id}.sock")
    pid_path = Path(f"/tmp/test-n24-probe-{test_id}.pid")
    log_path = Path(f"/tmp/test-n24-probe-{test_id}.log")

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
    (config_dir / "hooks-daemon.yaml").write_text("""
version: '1.0'
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  self_install_mode: true
  strict_mode: true
project_handlers:
  enabled: true
  path: .claude/project-handlers
handlers:
  pre_tool_use: {}
  post_tool_use: {}
  session_start: {}
""")

    probe_dir = config_dir / "project-handlers" / "pre_tool_use"
    probe_dir.mkdir(parents=True)
    (probe_dir / "n24_strict_mode_probe.py").write_text(_PROBE_HANDLER_SOURCE)

    return {
        "project_root": tmp_path,
        "socket_path": socket_path,
    }


@pytest.fixture
def strict_probe_daemon_process(strict_probe_daemon_env: dict[str, Any]):
    """Start the isolated daemon and ensure it is stopped after the test."""
    project_root = strict_probe_daemon_env["project_root"]
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

    yield strict_probe_daemon_env

    stop_cmd = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli", "stop"]
    subprocess.run(
        stop_cmd,
        cwd=project_root,
        env=test_env,
        capture_output=True,
        timeout=Timeout.SOCKET_CONNECT,
    )
    time.sleep(0.5)


def _send_pre_tool_use(sock_path: Path, cwd: Path, *, synthetic_source: str | None) -> dict:
    """Send a PreToolUse Bash event and return the daemon response."""
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


def test_the_marked_probe_payload_is_denied(
    strict_probe_daemon_process: dict[str, Any],
) -> None:
    """A raising handler denies on the LIVE daemon under strict_mode: true.

    If this ever comes back ALLOW, `daemon.strict_mode` has regressed to
    inert again, and nothing in the unit suite would notice, because the
    unit suite does not exercise the real daemon process this fix threads
    config through.
    """
    project_root = strict_probe_daemon_process["project_root"]
    socket_path = strict_probe_daemon_process["socket_path"]
    response = _send_pre_tool_use(socket_path, project_root, synthetic_source=_PROBE_MARKER)

    assert (
        _decision(response) == _DENY
    ), f"A handler crashing under strict_mode: true must be denied. Got: {response!r}"
    assert "n24-strict-mode-probe" in _reason(
        response
    ), f"Deny reason must name the crashed handler. Got: {_reason(response)!r}"


def test_an_unmarked_payload_is_not_denied_by_the_probe(
    strict_probe_daemon_process: dict[str, Any],
) -> None:
    """Negative control: the probe never fires on ordinary traffic."""
    project_root = strict_probe_daemon_process["project_root"]
    socket_path = strict_probe_daemon_process["socket_path"]
    response = _send_pre_tool_use(socket_path, project_root, synthetic_source=None)

    assert "n24-strict-mode-probe" not in _reason(response), (
        f"An ordinary payload (no synthetic_source marker) must never trip "
        f"the N24 probe handler. Got: {response!r}"
    )


@pytest.mark.parametrize("other_source", ["playbook-probe", "socket-stdin-test"])
def test_a_different_synthetic_source_is_not_denied_by_the_probe(
    strict_probe_daemon_process: dict[str, Any], other_source: str
) -> None:
    """Only the EXACT probe marker fires — not every synthetic source."""
    project_root = strict_probe_daemon_process["project_root"]
    socket_path = strict_probe_daemon_process["socket_path"]
    response = _send_pre_tool_use(socket_path, project_root, synthetic_source=other_source)

    assert "n24-strict-mode-probe" not in _reason(response), (
        f"synthetic_source={other_source!r} must not trip the N24 probe "
        f"handler, only the exact 'n24-probe' marker. Got: {response!r}"
    )
