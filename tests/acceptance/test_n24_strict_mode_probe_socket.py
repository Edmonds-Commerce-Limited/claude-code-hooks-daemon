r"""Plan 00466 N24 — ``daemon.strict_mode`` plumbing, end to end against the daemon.

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
running daemon process, not just the unit-level DI wiring. It deliberately
avoids depending on any organically-crashing handler (a fragile, separately
tracked bug's lifecycle) by using a dedicated project-only probe handler
(``.claude/project-handlers/pre_tool_use/n24_strict_mode_probe.py``) that
raises ONLY for a payload marked ``synthetic_source: n24-probe`` — a field no
real Claude Code session ever sends (see ``daemon/synthetic_traffic.py``).

Requires ``daemon.strict_mode: true``, which is this repository's own
shipped config (``.claude/hooks-daemon.yaml``) — the same posture used by
``tests/integration/test_relay_event_socket_real_payloads.py``.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]

_DENY = "deny"
_PROBE_MARKER = "n24-probe"

#: `daemon_socket` (socket discovery + Plan 00371 staleness check) lives in
#: tests/acceptance/conftest.py, shared across every acceptance file that
#: dispatches through the live daemon socket.


def _send_pre_tool_use(sock_path: Path, *, synthetic_source: str | None) -> dict:
    """Send a PreToolUse Bash event and return the daemon response."""
    hook_input: dict[str, object] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "true"},
        "cwd": str(REPO_ROOT),
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
    """Extract the PreToolUse permission decision from a daemon response."""
    return str(response.get("hookSpecificOutput", {}).get("permissionDecision", ""))


def _reason(response: dict) -> str:
    """Extract the PreToolUse decision reason from a daemon response."""
    return str(response.get("hookSpecificOutput", {}).get("permissionDecisionReason", ""))


def test_the_marked_probe_payload_is_denied(daemon_socket: Path) -> None:
    """A raising handler denies on the LIVE daemon under strict_mode: true.

    If this ever comes back ALLOW, `daemon.strict_mode` has regressed to
    inert again, and nothing in the unit suite would notice, because the
    unit suite does not exercise the real daemon process this fix threads
    config through.
    """
    response = _send_pre_tool_use(daemon_socket, synthetic_source=_PROBE_MARKER)

    assert _decision(response) == _DENY, (
        f"A handler crashing under this repo's own strict_mode: true config "
        f"must be denied. Got: {response!r}"
    )
    assert "n24-strict-mode-probe" in _reason(
        response
    ), f"Deny reason must name the crashed handler. Got: {_reason(response)!r}"


def test_an_unmarked_payload_is_not_denied_by_the_probe(daemon_socket: Path) -> None:
    """Negative control: the probe never fires on ordinary traffic.

    Without this, a probe handler that matched EVERYTHING would still
    satisfy the test above. Asserts only that the probe itself did not deny
    — another handler may legitimately act on the same event.
    """
    response = _send_pre_tool_use(daemon_socket, synthetic_source=None)

    assert "n24-strict-mode-probe" not in _reason(response), (
        f"An ordinary payload (no synthetic_source marker) must never trip "
        f"the N24 probe handler. Got: {response!r}"
    )


@pytest.mark.parametrize("other_source", ["playbook-probe", "socket-stdin-test"])
def test_a_different_synthetic_source_is_not_denied_by_the_probe(
    daemon_socket: Path, other_source: str
) -> None:
    """Only the EXACT probe marker fires — not every synthetic source."""
    response = _send_pre_tool_use(daemon_socket, synthetic_source=other_source)

    assert "n24-strict-mode-probe" not in _reason(response), (
        f"synthetic_source={other_source!r} must not trip the N24 probe "
        f"handler, only the exact 'n24-probe' marker. Got: {response!r}"
    )
