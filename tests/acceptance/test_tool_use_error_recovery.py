r"""Plan 00101 Phase 7 — tool_use_error recovery acceptance probe.

Exercises the Plan 00101 Phase 6 ``auto_continue_stop`` Branch 2.5 against
the live daemon socket. Reproduces the field-bug shape:

  - Agent calls ``Edit`` on a file it has not yet ``Read``.
  - Claude Code returns a ``tool_use_error`` (``File has not been read yet``).
  - Agent then stops silently instead of recovering.

Phase 6's Branch 2.5 contract: the Stop hook MUST return ``decision=block``
with a recovery-specific reason (``TOOL ERROR RECOVERY:`` prefix) so the
agent re-enters with a clear next step — Read the file, then retry the Edit.

Negative-control case: the same scenario but with a *successful* tool_result
(``is_error=false``) must fall through to the generic explain-or-continue
branch (Branch 4), proving Branch 2.5 gates strictly on ``is_error=true``.

Unit-level coverage in ``tests/unit/handlers/stop/test_auto_continue_stop.py``
``TestAutoContinueStopAfterToolUseError`` (Cases A/B/C) verifies the
in-process behaviour. This file is the end-to-end acceptance gate against
the production daemon socket — invoked by RELEASING.md Step 12.0 H-1.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOCKET_GLOB = "daemon-*.sock"

_RECOVERY_REASON_FRAGMENT = "TOOL ERROR RECOVERY:"
_DEFAULT_REASON_FRAGMENT = "STOPPING BECAUSE:"


def _socket_is_alive(sock_path: Path) -> bool:
    """Return True if a Unix socket file accepts a connection.

    Multiple stale ``daemon-{hostname}.sock`` files can accumulate when a
    container restarts under a new hostname — the old socket inode survives
    on disk but ``connect()`` raises ``ECONNREFUSED`` because no daemon
    process is listening. Probing with a short timeout filters those out.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(str(sock_path))
        return True
    except OSError:
        return False


def _discover_socket() -> Path | None:
    """Locate the running daemon's Unix socket via env or glob.

    Mirrors ``scripts/qa/run_smoke_test.sh`` discovery but additionally
    probes each candidate to skip stale sockets whose daemon process is
    gone. Env override (``CLAUDE_HOOKS_SOCKET_PATH``) takes precedence.
    """
    env_path = os.environ.get("CLAUDE_HOOKS_SOCKET_PATH")
    if env_path and Path(env_path).is_socket() and _socket_is_alive(Path(env_path)):
        return Path(env_path)
    for candidate in sorted((REPO_ROOT / "untracked").glob(SOCKET_GLOB)):
        if candidate.is_socket() and _socket_is_alive(candidate):
            return candidate
    return None


def _send_stop_event(sock_path: Path, transcript_path: Path, session_id: str) -> dict:
    """Send a Stop event to the daemon via Unix socket and return the response."""
    payload = {
        "event": "Stop",
        "hook_input": {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "transcript_path": str(transcript_path),
            "session_id": session_id,
            "cwd": str(REPO_ROOT),
        },
    }
    request = json.dumps(payload).encode("utf-8") + b"\n"

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10.0)
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


def _write_transcript(path: Path, *, is_error: bool, tool_use_id: str = "toolu_phase7") -> None:
    """Write a transcript with an Edit tool_use followed by a tool_result.

    ``is_error=True`` reproduces the "File has not been read yet" failure
    shape. ``is_error=False`` is the negative-control success case.
    """
    error_content = (
        "File has not been read yet. Read it first before writing to it."
        if is_error
        else "Edit succeeded."
    )
    lines = [
        json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": "Edit",
                            "input": {
                                "file_path": "/tmp/phase7-target.py",
                                "old_string": "old",
                                "new_string": "new",
                            },
                        }
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": error_content,
                            "is_error": is_error,
                        }
                    ],
                },
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def daemon_socket() -> Path:
    sock_path = _discover_socket()
    if sock_path is None:
        pytest.skip(
            "Daemon not running — no live socket found under untracked/. "
            "Start the daemon with: "
            "$PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
        )
    assert sock_path is not None
    return sock_path


def test_tool_use_error_recovery_branch_fires(daemon_socket: Path, tmp_path: Path) -> None:
    """Positive case: Edit + tool_use_error + silent stop → recovery reason.

    Field-regression shape from Plan 00101 Phase 0 incident: agent calls
    ``Edit`` on an unread file, Claude Code returns a ``tool_use_error``,
    and the agent stops without recovery. Phase 6 Branch 2.5 must trigger
    a ``decision=block`` response with the TOOL ERROR RECOVERY-specific
    reason so the agent receives a clear directive (Read, then retry)
    instead of the generic explain-or-continue prompt.
    """
    transcript_path = tmp_path / "transcript.jsonl"
    _write_transcript(transcript_path, is_error=True)

    response = _send_stop_event(daemon_socket, transcript_path, session_id="phase7-positive")

    assert response.get("decision") == "block", (
        f"Stop hook must block when the last tool_result is an error and "
        f"the agent stopped silently. Got: {response!r}"
    )
    reason = response.get("reason", "")
    assert _RECOVERY_REASON_FRAGMENT in reason, (
        f"Block reason must be the TOOL ERROR RECOVERY-specific branch "
        f"(Phase 6 Branch 2.5), not the generic explain-or-continue branch. "
        f"Got reason: {reason!r}"
    )
    lower = reason.lower()
    assert (
        "retry" in lower or "read" in lower
    ), f"Recovery reason must direct the agent to Read+retry. Got: {reason!r}"


def test_tool_use_error_recovery_branch_skipped_on_success(
    daemon_socket: Path, tmp_path: Path
) -> None:
    """Negative control: success tool_result must NOT fire Branch 2.5.

    With ``is_error=false`` on the last tool_result, Branch 2.5 must remain
    dormant and the dispatcher must fall through to the default
    explain-or-continue branch (Branch 4). Proves Branch 2.5 gates strictly
    on ``is_error=true`` and never matches on a clean turn.
    """
    transcript_path = tmp_path / "transcript.jsonl"
    _write_transcript(transcript_path, is_error=False)

    response = _send_stop_event(daemon_socket, transcript_path, session_id="phase7-negative")

    assert response.get("decision") == "block", (
        f"Silent stop is still blocked by the default branch — what differs "
        f"is the REASON. Got: {response!r}"
    )
    reason = response.get("reason", "")
    assert _RECOVERY_REASON_FRAGMENT not in reason, (
        f"Branch 2.5 must NOT fire on a successful tool_result. Got TOOL "
        f"ERROR RECOVERY reason instead of default. Reason: {reason!r}"
    )
    assert _DEFAULT_REASON_FRAGMENT in reason, (
        f"Default branch reason must direct the agent to use the "
        f"STOPPING BECAUSE: prefix. Got: {reason!r}"
    )
