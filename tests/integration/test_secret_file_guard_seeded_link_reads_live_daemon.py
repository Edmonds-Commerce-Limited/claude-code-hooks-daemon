"""Reads through a seeded link are denied by a RUNNING daemon (Plan 00613, live-socket check).

``tests/unit/handlers/pre_tool_use/test_secret_file_guard_seeded_link_reads.py``
pins the guard's judgement by calling the handler directly. This file closes
the success criterion that asks for the same verdicts from an actual daemon
process, over its real socket, with the link placed by the real route:

1. A git repository on ``main`` commits a config whose ``worktree_create`` seed
   list holds ``conf`` in symlink mode and whose ``secret_file_guard`` protects
   ``conf/vault.txt`` (a project glob no shipped default matches, so a read can
   only be denied by RESOLVING the link, never by its spelling).
2. A worktree is made by hand (``git worktree add``), which fires no creation
   hook, and ``hooks-daemon seed-worktree`` places the link.
3. The project's own daemon is started, and PreToolUse events are sent to its
   socket with ``cwd`` inside the worktree, where an agent working there stands.

Each payload carries ``synthetic_source: test-probe`` so the verdict log does
not count it as an agent's tool call.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout
from tests.isolated_daemon import DAEMON_CLI_SUBPROCESS_BOUND, isolated_daemon_paths

_PROTECTED = "conf/vault.txt"
_WORKTREE = ".claude/worktrees/live-seeded"
_PROBE_SOURCE = "test-probe"
_CLI = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.cli"]

_CONFIG = f"""
version: '1.0'
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  self_install_mode: true
handlers:
  pre_tool_use:
    secret_file_guard:
      enabled: true
      priority: 14
      options:
        protected_paths:
          - "{_PROTECTED}"
  post_tool_use: {{}}
  session_start: {{}}
  worktree_create:
    worktree_create:
      enabled: true
      priority: 50
      options:
        seed:
          default_mode: symlink
          entries:
            - conf
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_CLI, *args],
        cwd=cwd,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=DAEMON_CLI_SUBPROCESS_BOUND,
    )


@pytest.fixture
def live_seeded_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Path]]:
    """A hand-made worktree seeded by ``seed-worktree``, and the project's running daemon."""
    root = tmp_path / "project"
    root.mkdir()
    socket_path, pid_path, log_path = isolated_daemon_paths(tmp_path, "seeded-link")
    monkeypatch.setenv("CLAUDE_HOOKS_SOCKET_PATH", str(socket_path))
    monkeypatch.setenv("CLAUDE_HOOKS_PID_PATH", str(pid_path))
    monkeypatch.setenv("CLAUDE_HOOKS_LOG_PATH", str(log_path))

    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@test.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "remote", "add", "origin", "https://github.com/test/repo.git")
    (root / ".gitignore").write_text("conf/\n.claude/worktrees/\nuntracked/\n")
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG)
    _git(root, "add", ".gitignore", ".claude/hooks-daemon.yaml")
    _git(root, "commit", "-m", "Seed list commits conf as a link")

    (root / "conf").mkdir()
    (root / _PROTECTED).write_bytes(b"not-a-real-secret\n")
    (root / "conf" / "plain.txt").write_text("ordinary\n")

    tree = root / _WORKTREE
    _git(root, "worktree", "add", "-b", "live-seeded", str(tree))

    seeded = _cli(root, "seed-worktree", str(tree))
    assert seeded.returncode == 0, seeded.stderr
    assert (tree / "conf").is_symlink()
    (tree / "plain.txt").write_text("ordinary\n")

    started = _cli(root, "start")
    if started.returncode != 0:
        pytest.fail(f"Failed to start daemon (exit {started.returncode}): {started.stderr}")
    time.sleep(1)
    status = _cli(root, "status")
    if "RUNNING" not in status.stdout:
        pytest.fail(f"Daemon not running after start:\n{status.stdout}")

    yield {"root": root, "tree": tree, "socket": socket_path}

    _cli(root, "stop")


def _send(sock_path: Path, cwd: Path, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    hook_input = {
        "hook_event_name": "PreToolUse",
        "session_id": "seeded-link-live-probe",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(cwd),
        "synthetic_source": _PROBE_SOURCE,
    }
    request = json.dumps({"event": "PreToolUse", "hook_input": hook_input}).encode() + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(Timeout.SOCKET_DISPATCH_ROUNDTRIP)
        sock.connect(str(sock_path))
        sock.sendall(request)
        sock.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    response = json.loads(b"".join(chunks).decode().strip())
    assert isinstance(response, dict), response
    return response


def _verdict(response: dict[str, Any]) -> tuple[str, str]:
    output = response.get("hookSpecificOutput", {})
    return (
        str(output.get("permissionDecision", "")),
        str(output.get("permissionDecisionReason", "")),
    )


_DENIED_BASH_READS = [
    f"cat {_PROTECTED}",
    "cat conf/*",
    "grep -r secret conf",
    "grep -R secret .",
    "rg -L secret",
    "find -L . -type f -exec cat {} +",
    "tar -chf out.tar .",
    f"cp -L {_PROTECTED} copy.txt",
]


@pytest.mark.parametrize("command", _DENIED_BASH_READS)
def test_a_bash_read_through_the_seeded_link_is_denied(
    live_seeded_worktree: dict[str, Path], command: str
) -> None:
    decision, reason = _verdict(
        _send(
            live_seeded_worktree["socket"],
            live_seeded_worktree["tree"],
            "Bash",
            {"command": command},
        )
    )
    assert decision == "deny", reason
    assert "R-SECRET" in reason


def test_the_read_tool_through_the_seeded_link_is_denied(
    live_seeded_worktree: dict[str, Path],
) -> None:
    tree = live_seeded_worktree["tree"]
    decision, reason = _verdict(
        _send(live_seeded_worktree["socket"], tree, "Read", {"file_path": str(tree / _PROTECTED)})
    )
    assert decision == "deny", reason


def test_the_grep_tool_rooted_at_the_linked_directory_is_denied(
    live_seeded_worktree: dict[str, Path],
) -> None:
    tree = live_seeded_worktree["tree"]
    tool_input = {"path": str(tree / "conf"), "pattern": "secret"}
    decision, reason = _verdict(_send(live_seeded_worktree["socket"], tree, "Grep", tool_input))
    assert decision == "deny", reason


@pytest.mark.parametrize(
    "command",
    [
        f"ln -s ../../../{_PROTECTED} vault-link.txt",
        f"ln -s {_PROTECTED} vault-link.txt",
        f"cp -s ../../../{_PROTECTED} vault-link.txt",
    ],
)
def test_a_hand_typed_link_to_the_protected_file_is_denied(
    live_seeded_worktree: dict[str, Path], command: str
) -> None:
    """Only the configured seed route places a protected link; a typed one stays denied."""
    decision, reason = _verdict(
        _send(
            live_seeded_worktree["socket"],
            live_seeded_worktree["tree"],
            "Bash",
            {"command": command},
        )
    )
    assert decision == "deny", reason
    assert "R-SECRET" in reason


# `grep -r` follows no link below its root, so its ALLOW against the DENY of
# `grep -R secret .` above shows the live daemon judged the link, not the spelling.
@pytest.mark.parametrize("command", ["cat plain.txt", "cat conf/plain.txt", "grep -r secret ."])
def test_an_unprotected_read_in_the_worktree_is_not_denied(
    live_seeded_worktree: dict[str, Path], command: str
) -> None:
    """Control: the denials come from the protected file behind the link, not the worktree."""
    decision, reason = _verdict(
        _send(
            live_seeded_worktree["socket"],
            live_seeded_worktree["tree"],
            "Bash",
            {"command": command},
        )
    )
    assert decision != "deny", reason
