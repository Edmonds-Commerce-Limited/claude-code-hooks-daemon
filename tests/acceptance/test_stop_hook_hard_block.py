r"""Plan 00101 Phase 9 — Stop hook hard-block exit-code-2 acceptance probe.

Confirms the bash wrapper `.claude/hooks/stop` translates a daemon
``decision=block`` JSON response into the exit-code-2 + stderr contract
that Claude Code v2.1.114 honours for hard re-entry.

**Background**: Transcript evidence
(`/root/.claude/projects/-workspace/<session>.jsonl`) shows that 100% of
`stop_hook_summary` records in v2.1.114 are downgraded to
`level: suggestion, preventedContinuation: false` — even when the daemon
correctly emits a `{"decision":"block","reason":"..."}` payload. The
documented alternative per `CLAUDE/Code/HooksSystem.md` is exit code 2
with the reason on stderr; that path forces hard re-entry.

**Contract under test** (both stop and subagent-stop wrappers):

1. Capture the daemon's JSON response (do not mutate it).
2. Print the JSON to stdout (back-compat — existing tests + agent visibility).
3. If `decision == "block"`:
     - Print the `reason` to stderr.
     - Exit 2.
4. Otherwise exit 0.

This file is the end-to-end acceptance gate — invoked by RELEASING.md
Step 12.0 H-1 alongside the other Phase 9 / Phase 10 acceptance probes.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
SOCKET_GLOB = "daemon-*.sock"
STOP_HOOK = REPO_ROOT / ".claude" / "hooks" / "stop"
SUBAGENT_STOP_HOOK = REPO_ROOT / ".claude" / "hooks" / "subagent-stop"

_EXIT_HARD_BLOCK = 2
_EXIT_OK = 0


def _socket_is_alive(sock_path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect(str(sock_path))
        return True
    except OSError:
        return False


def _discover_socket() -> Path | None:
    env_path = os.environ.get("CLAUDE_HOOKS_SOCKET_PATH")
    if env_path and Path(env_path).is_socket() and _socket_is_alive(Path(env_path)):
        return Path(env_path)
    for candidate in sorted((REPO_ROOT / "untracked").glob(SOCKET_GLOB)):
        if candidate.is_socket() and _socket_is_alive(candidate):
            return candidate
    return None


@pytest.fixture
def daemon_running() -> None:
    sock_path = _discover_socket()
    if sock_path is None:
        pytest.skip("Daemon not running — start with: ./bin/hooks-daemon restart")


def _invoke_hook(hook_path: Path, hook_input: dict) -> subprocess.CompletedProcess[str]:
    """Invoke a bash hook wrapper as a subprocess and return the result."""
    return subprocess.run(
        ["bash", str(hook_path)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=Timeout.DAEMON_RESTART_VERIFY_TIMEOUT_SEC,
        check=False,
    )


def test_stop_hook_exits_2_on_block(daemon_running: None, tmp_path: Path) -> None:
    """Daemon returns decision=block → wrapper exits 2 + reason on stderr.

    Reproduces the silent-stop scenario: empty transcript, stop_hook_active
    false. The daemon's default Stop branch emits a block with the
    STOPPING BECAUSE: explainer. The wrapper must translate that to the
    exit-code-2 contract for v2.1.114 hard re-entry.

    The payload ``cwd`` is an isolated directory, never the repo root, so the
    block under test is the one this docstring names. This project's
    ``release_blocker`` sits ahead of the terminal ``auto_continue_stop`` on
    the Stop chain and matches on a modified release file, so a repo-rooted
    ``cwd`` would hand the block to that handler instead whenever the tree is
    dirty — which, during a release, it is by definition. The wrapper contract
    asserted below holds either way, so the substitution would be silent.
    """
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")
    hook_input = {
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "transcript_path": str(transcript),
        "session_id": "phase9-block-probe",
        "cwd": str(tmp_path),
    }

    result = _invoke_hook(STOP_HOOK, hook_input)

    assert result.returncode == _EXIT_HARD_BLOCK, (
        f"Stop wrapper must exit 2 when daemon returns decision=block. "
        f"Got exit={result.returncode}, stdout={result.stdout!r}, "
        f"stderr={result.stderr!r}"
    )

    payload = json.loads(result.stdout.strip())
    assert payload.get("decision") == "block", (
        f"stdout must still carry the daemon JSON (back-compat). " f"Got: {result.stdout!r}"
    )
    expected_reason = payload.get("reason", "")
    assert expected_reason, "Daemon must populate reason on a block response."
    assert expected_reason in result.stderr, (
        f"Daemon reason must be echoed to stderr for Claude Code visibility. "
        f"reason={expected_reason!r}, stderr={result.stderr!r}"
    )


def test_subagent_stop_hook_exits_2_on_block(daemon_running: None, tmp_path: Path) -> None:
    """SubagentStop wrapper mirrors the Stop contract on a block response."""
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")
    hook_input = {
        "hook_event_name": "SubagentStop",
        "stop_hook_active": False,
        "transcript_path": str(transcript),
        "session_id": "phase9-subagent-block-probe",
        "cwd": str(REPO_ROOT),
    }

    result = _invoke_hook(SUBAGENT_STOP_HOOK, hook_input)

    # SubagentStop currently has no auto_continue handler — daemon returns
    # an allow/empty response. The wrapper contract is symmetric: exit 2
    # only when daemon explicitly returns decision=block. If the daemon
    # returns allow/empty, the wrapper exits 0 — but the back-compat stdout
    # invariant still holds.
    payload = json.loads(result.stdout.strip() or "{}")
    if payload.get("decision") == "block":
        assert result.returncode == _EXIT_HARD_BLOCK, (
            f"SubagentStop wrapper must exit 2 on a block response. "
            f"Got exit={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        reason = payload.get("reason", "")
        assert reason and reason in result.stderr, (
            f"Reason must be echoed to stderr. reason={reason!r}, " f"stderr={result.stderr!r}"
        )
    else:
        # No block → no hard re-entry → exit 0, no stderr noise.
        assert result.returncode == _EXIT_OK, (
            f"SubagentStop wrapper must exit 0 when daemon does not block. "
            f"Got exit={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )


def test_stop_hook_exits_0_when_daemon_allows(daemon_running: None, tmp_path: Path) -> None:
    """Re-entry stop (stop_hook_active=true with prior block evidence absent)
    falls through to allow → wrapper must exit 0, no stderr.

    This is the "agent has already explained itself, allow the stop" path.
    The matches() guard in auto_continue_stop requires `stop_hook_active`
    AND evidence of a prior block; absent that evidence the handler treats
    the event as not-our-business and the dispatch chain produces an empty
    allow response.
    """
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")
    hook_input = {
        "hook_event_name": "Stop",
        "stop_hook_active": True,
        "transcript_path": str(transcript),
        "session_id": "phase9-allow-probe",
        "cwd": str(REPO_ROOT),
    }

    result = _invoke_hook(STOP_HOOK, hook_input)

    payload = json.loads(result.stdout.strip() or "{}")
    if payload.get("decision") != "block":
        assert result.returncode == _EXIT_OK, (
            f"Stop wrapper must exit 0 when daemon does not block. "
            f"Got exit={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
