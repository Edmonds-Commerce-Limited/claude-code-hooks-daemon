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
a socket — the invocation context itself is the thing under test. Per
``CLAUDE/development/LESSONS.md`` "Test in the host's invocation context",
every payload below is what Claude Code actually sends — nothing hand-added
that any layer under test (the wrapper, the transport, the daemon) is
itself responsible for injecting, and every assertion checks the RESPONSE
shape the host actually consumes for that event's class (JSON decision
object / raw text / exit-code-2), not merely that a response arrived.
"""

import json
import socket
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = Path("/workspace/.claude/hooks")
_EXIT_OK = 0
_EXIT_HARD_BLOCK = 2
# Generous ceiling for one forwarder round-trip (daemon answer is sub-second;
# the margin covers a cold daemon restart under concurrent-agent load).
_FORWARDER_TIMEOUT_SECONDS = 60

_PRE_TOOL_USE_PAYLOAD = (
    b'{"tool_name":"Bash","tool_input":{"command":"true"},'
    b'"hook_event_name":"PreToolUse","session_id":"socket-stdin-test"}'
)
# Real PostToolUse shape (core/input_schemas.py: requires tool_name,
# tool_response, hook_event_name const "PostToolUse" — a Bash tool_response
# has no "exit_code" field per that schema's own captured-event note).
_POST_TOOL_USE_PAYLOAD = (
    b'{"tool_name":"Bash","tool_input":{"command":"true"},'
    b'"tool_response":{"stdout":"","stderr":""},'
    b'"hook_event_name":"PostToolUse","session_id":"socket-stdin-test"}'
)
_STATUS_PAYLOAD = (
    b'{"session_id":"socket-stdin-test","model":{"display_name":"Test"},'
    b'"workspace":{"current_dir":"/workspace"}}'
)


def _run_forwarder_with_socket_stdin(
    forwarder: Path, payload: bytes, cwd: Path | None = None
) -> tuple[int, bytes, bytes]:
    parent, child = socket.socketpair()
    try:
        parent.sendall(payload)
        parent.shutdown(socket.SHUT_WR)
        proc = subprocess.Popen(
            ["bash", str(forwarder)],
            stdin=child.fileno(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
        )
        child.close()
        out, err = proc.communicate(timeout=_FORWARDER_TIMEOUT_SECONDS)
        return proc.returncode, out, err
    finally:
        parent.close()


@pytest.mark.parametrize(
    ("forwarder_name", "payload", "expect_json_object"),
    [
        ("pre-tool-use", _PRE_TOOL_USE_PAYLOAD, True),
        ("post-tool-use", _POST_TOOL_USE_PAYLOAD, True),
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
        # Response-direction contract (LESSONS.md #3): a normal event's
        # answer is a JSON decision object Claude Code parses STRUCTURALLY —
        # it must be a real JSON object, not merely "some text that happens
        # to start with a brace". An empty `{}` is itself a valid decision
        # object (the documented "no opinion" / implicit-allow response for
        # PreToolUse/PostToolUse), so no further key is required — only that
        # decoding as JSON succeeds and yields a dict.
        parsed = json.loads(out.decode())
        assert isinstance(parsed, dict), out.decode()[:200]


# ---------------------------------------------------------------------------
# Stop-family: the wrapper translates a daemon decision=block JSON response
# into exit-code-2 + reason-on-stderr (Plan 00101 Phase 9 hard-reentry
# contract) — a response shape no other event class uses. This closes two
# gaps at once: the pre-existing acceptance coverage
# (tests/acceptance/test_stop_hook_hard_block.py) invokes the wrapper with a
# PIPE, not a socket, so it never proved the fd-type contract for this event
# class; and nothing anywhere asserted the exit-code contract with stdin
# genuinely being a socket.
# ---------------------------------------------------------------------------


def test_stop_forwarder_exits_2_on_block_with_socket_stdin(tmp_path: Path) -> None:
    """Real payload, real socket stdin, real daemon: a genuinely-blockable
    Stop event (empty transcript, stop_hook_active=False — the
    auto_continue_stop default block) must exit 2 with the reason on
    stderr, exactly as Claude Code v2.1.114 requires for hard re-entry."""
    forwarder = HOOKS_DIR / "stop"
    assert forwarder.is_file(), f"deployed forwarder missing: {forwarder}"

    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")
    # Real payload shape (see tests/acceptance/test_stop_hook_hard_block.py,
    # itself keyed off a real captured Stop event) — cwd is isolated so this
    # project's own release_blocker (which matches a dirty repo-rooted cwd)
    # cannot substitute a different block for the one under test.
    payload = json.dumps(
        {
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "transcript_path": str(transcript),
            "session_id": "socket-stdin-stop-block-probe",
            "cwd": str(tmp_path),
        }
    ).encode()

    returncode, out, err = _run_forwarder_with_socket_stdin(forwarder, payload, cwd=tmp_path)

    assert b"No such device or address" not in err, err.decode()
    assert returncode == _EXIT_HARD_BLOCK, (
        f"Stop wrapper must exit 2 on a block response with socket stdin. "
        f"Got exit={returncode}, stdout={out.decode()!r}, stderr={err.decode()!r}"
    )
    stdout_payload = json.loads(out.decode().strip())
    assert stdout_payload.get("decision") == "block", out.decode()
    reason = stdout_payload.get("reason", "")
    assert (
        reason and reason.encode() in err
    ), f"Block reason must be echoed to stderr. reason={reason!r} stderr={err.decode()!r}"


def test_stop_forwarder_exits_0_when_not_blocked_with_socket_stdin(tmp_path: Path) -> None:
    """Re-entry Stop (stop_hook_active=True, no prior-block evidence) falls
    through to allow — exit 0, no hard-reentry stderr noise — with genuine
    socket stdin."""
    forwarder = HOOKS_DIR / "stop"
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")
    payload = json.dumps(
        {
            "hook_event_name": "Stop",
            "stop_hook_active": True,
            "transcript_path": str(transcript),
            "session_id": "socket-stdin-stop-allow-probe",
            "cwd": str(tmp_path),
        }
    ).encode()

    returncode, out, err = _run_forwarder_with_socket_stdin(forwarder, payload, cwd=tmp_path)

    assert b"No such device or address" not in err, err.decode()
    stdout_payload = json.loads(out.decode().strip() or "{}")
    if stdout_payload.get("decision") != "block":
        assert returncode == _EXIT_OK, (
            f"Stop wrapper must exit 0 when not blocked. Got exit={returncode}, "
            f"stdout={out.decode()!r}, stderr={err.decode()!r}"
        )


# ---------------------------------------------------------------------------
# WorktreeCreate: the wrapper unwraps the daemon's JSON into a RAW PATH on
# stdout (never JSON — Claude Code takes the literal stdout bytes as the
# worktree path, Plan 00188), or fails cleanly (non-zero exit, no stdout)
# when the daemon produced none. Exercised against an isolated non-repo
# ``cwd`` so ``git worktree add`` fails loudly and nothing is created
# anywhere in this repository's own tree — the failure path IS the raw_stdout
# contract under test (no JSON on stdout either way).
# ---------------------------------------------------------------------------


def test_worktree_create_forwarder_fails_cleanly_with_no_json_on_stdout(tmp_path: Path) -> None:
    forwarder = HOOKS_DIR / "worktree-create"
    assert forwarder.is_file(), f"deployed forwarder missing: {forwarder}"

    # Real payload shape (see WorktreeCreateHandler's _KEY_* constants,
    # captured from a real WorktreeCreate event). cwd is an isolated tmp dir
    # that is NOT a git repository, so worktree creation fails loudly and
    # nothing is created inside this project's own tree.
    payload = json.dumps(
        {
            "hook_event_name": "WorktreeCreate",
            "cwd": str(tmp_path),
            "name": "socket-stdin-worktree-probe",
            "prompt_id": "socket-stdin-prompt",
            "session_id": "socket-stdin-worktree-session",
        }
    ).encode()

    returncode, out, err = _run_forwarder_with_socket_stdin(forwarder, payload, cwd=tmp_path)

    assert b"No such device or address" not in err, err.decode()
    # Response-direction contract: never JSON on stdout for a raw_stdout
    # event, success or failure.
    assert not out.lstrip().startswith(b"{"), out.decode()[:200]
    if returncode == _EXIT_OK:
        # Handler somehow succeeded (unexpected but not this test's job to
        # forbid) — stdout must be a real absolute path, not empty and not JSON.
        assert out.strip(), "success must still print the worktree path"
    else:
        # The expected shape: creation failed against a non-repo cwd, so no
        # path exists to print — stdout is empty, the reason is on stderr.
        assert not out.strip(), f"a failed creation must print no path: {out.decode()!r}"
        assert err.strip(), "a failed creation must explain itself on stderr"
