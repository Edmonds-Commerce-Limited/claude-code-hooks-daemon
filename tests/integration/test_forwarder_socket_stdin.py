"""Deployed forwarders must work when stdin is a SOCKET, as Claude Code spawns them.

Field report (live session): every real hook event failed with
``init.sh: line 944: /dev/stdin: No such device or address`` while every
test passed — because Claude Code hands hook commands a socketpair end as
stdin, and bash's ``< /dev/stdin`` re-open is an ``open()`` on a socket,
which fails with ENXIO. Pipe-fed invocations (every pytest/pipe harness)
re-open fine, so no test saw it. The transport now duplicates the stdin fd
(``exec 3<&0`` — dup semantics, valid for any fd type) instead of
re-opening a path.

These tests invoke the REAL deployed forwarders with stdin genuinely being
a socket — the invocation context itself is the thing under test.
"""

import socket
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = Path("/workspace/.claude/hooks")

_PRE_TOOL_USE_PAYLOAD = (
    b'{"tool_name":"Bash","tool_input":{"command":"true"},'
    b'"hook_event_name":"PreToolUse","session_id":"socket-stdin-test"}'
)
_STATUS_PAYLOAD = (
    b'{"session_id":"socket-stdin-test","model":{"display_name":"Test"},'
    b'"workspace":{"current_dir":"/workspace"}}'
)


def _run_forwarder_with_socket_stdin(forwarder: Path, payload: bytes) -> tuple[int, bytes, bytes]:
    parent, child = socket.socketpair()
    try:
        parent.sendall(payload)
        parent.shutdown(socket.SHUT_WR)
        proc = subprocess.Popen(
            ["bash", str(forwarder)],
            stdin=child.fileno(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        child.close()
        out, err = proc.communicate(timeout=60)
        return proc.returncode, out, err
    finally:
        parent.close()


@pytest.mark.parametrize(
    ("forwarder_name", "payload", "expect_json_object"),
    [
        ("pre-tool-use", _PRE_TOOL_USE_PAYLOAD, True),
        ("post-tool-use", _PRE_TOOL_USE_PAYLOAD, True),
        # status-line returns RAW text (raw_stdout event), not a JSON object.
        ("status-line", _STATUS_PAYLOAD, False),
    ],
)
def test_forwarder_answers_when_stdin_is_a_socket(
    forwarder_name: str, payload: bytes, expect_json_object: bool
) -> None:
    forwarder = HOOKS_DIR / forwarder_name
    assert forwarder.is_file(), f"deployed forwarder missing: {forwarder}"

    returncode, out, err = _run_forwarder_with_socket_stdin(forwarder, payload)

    assert b"No such device or address" not in err, err.decode()
    assert b"HOOKS DAEMON ERROR" not in out, out.decode()
    assert returncode == 0, f"exit={returncode} stderr={err.decode()[:400]}"
    assert out.strip(), "forwarder produced no response"
    if expect_json_object:
        assert out.lstrip().startswith(b"{"), out.decode()[:200]
