r"""Plan 00196 — ``absolute_path`` deny path, end to end against the daemon.

This file exists because the playbook CANNOT test this handler. Claude Code
resolves ``file_path`` to an absolute path before dispatching PreToolUse, so a
tester driving the real tools can never hand the daemon a relative path — the
two entries in ``absolute_path.get_acceptance_tests()`` are marked
``harness_cannot_produce`` for exactly that reason.

The behaviour is still real and still relied upon: any client that does send a
relative ``file_path`` must be denied. Removing the handler because the harness
happens to pre-normalise would delete a guard for every non-Claude-Code caller.
So the coverage moves here, one layer below the harness, where a relative path
CAN be delivered — this is the end-to-end assertion the playbook entries would
otherwise have made.

Unit-level coverage lives in ``tests/unit/handlers/test_absolute_path.py``.
This file is the live-socket gate.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import Timeout, ToolName

REPO_ROOT = Path(__file__).resolve().parents[2]

_FILE_TOOLS = [ToolName.READ, ToolName.WRITE, ToolName.EDIT]
_DENY = "deny"
_REASON_FRAGMENT = "requires absolute path"
_RELATIVE_PATH = "relative/path/file.txt"
_ABSOLUTE_PATH = "/workspace/relative/path/file.txt"

#: `daemon_socket` (socket discovery + Plan 00371 staleness check) lives in
#: tests/acceptance/conftest.py, shared across every acceptance file that
#: dispatches through the live daemon socket.


def _send_pre_tool_use(sock_path: Path, tool_name: str, file_path: str) -> dict:
    """Send a PreToolUse event for a file tool and return the daemon response."""
    tool_input: dict[str, str] = {"file_path": file_path}
    if tool_name == ToolName.WRITE:
        tool_input["content"] = "probe"
    elif tool_name == ToolName.EDIT:
        tool_input["old_string"] = "old"
        tool_input["new_string"] = "new"

    payload = {
        "event": "PreToolUse",
        "hook_input": {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": str(REPO_ROOT),
        },
    }
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


@pytest.mark.parametrize("tool_name", _FILE_TOOLS)
def test_relative_path_is_denied(daemon_socket: Path, tool_name: str) -> None:
    """A relative file_path must be denied for every file tool.

    This is the assertion the acceptance playbook can no longer make. If it
    ever fails, the handler has regressed and NOTHING in the harness-driven
    suite would notice, because the harness cannot produce this input.
    """
    response = _send_pre_tool_use(daemon_socket, tool_name, _RELATIVE_PATH)

    assert _decision(response) == _DENY, (
        f"{tool_name} with relative file_path {_RELATIVE_PATH!r} must be denied. "
        f"Got: {response!r}"
    )
    assert _REASON_FRAGMENT in _reason(response), (
        f"Deny reason must explain the absolute-path requirement. " f"Got: {_reason(response)!r}"
    )


@pytest.mark.parametrize("tool_name", _FILE_TOOLS)
def test_absolute_path_is_not_denied(daemon_socket: Path, tool_name: str) -> None:
    """Negative control: the handler must not fire on absolute paths.

    Without this, a handler that denied everything would still satisfy the
    test above. Asserts only that ``absolute_path`` did not deny — another
    handler may legitimately act on the same event.
    """
    response = _send_pre_tool_use(daemon_socket, tool_name, _ABSOLUTE_PATH)

    assert _REASON_FRAGMENT not in _reason(response), (
        f"{tool_name} with absolute file_path {_ABSOLUTE_PATH!r} must not trip "
        f"the absolute-path handler. Got: {response!r}"
    )
