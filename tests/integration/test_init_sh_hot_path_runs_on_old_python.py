"""init.sh's stdlib-only python3 snippets run on the oldest interpreter a host may have.

init.sh runs bare ``python3`` on purpose in the forwarder hot path (recovery
carve-out, provision carve-out, the jq-less encoders, the socket transport):
no venv is resolved there by design, and these snippets run precisely when the
daemon or its venv is absent. The bare-python detector therefore allowlists
them, and that allowance holds only while every snippet stays valid on the
oldest Python a host can put first on PATH. This test runs each one under
real 3.8 and 3.9 interpreters (skipping when a host has neither) with jq absent,
so a 3.10+ construct in any of them fails here, not in a client's session.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.old_python import OLD_VERSIONS, old_python_or_skip

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / "init.sh"
_RUN_TIMEOUT_SECONDS = 60

# No jq: the encoders that fall back to python3 are the ones under test.
_TOOLS = (
    "sh",
    "bash",
    "env",
    "cat",
    "dirname",
    "basename",
    "tr",
    "hostname",
    "stat",
    "date",
    "mkdir",
    "mktemp",
    "touch",
    "chmod",
    "rm",
    "ls",
    "grep",
    "sed",
    "awk",
    "uname",
    "head",
    "cut",
    "sort",
    "wc",
    "id",
    "readlink",
    "realpath",
    "ps",
    "sleep",
)


@pytest.fixture(params=OLD_VERSIONS)
def old_env(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Path, Path]:
    """(checkout, bindir): init.sh deployed in a checkout, python3 -> an old interpreter."""
    interpreter = old_python_or_skip(request.param)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in _TOOLS:
        real = shutil.which(tool)
        if real is not None:
            (bindir / tool).symlink_to(real)
    (bindir / "python3").symlink_to(interpreter)
    checkout = tmp_path / "client"
    (checkout / ".claude").mkdir(parents=True)
    (checkout / ".claude" / "init.sh").write_text(_INIT_SH.read_text())
    return checkout, bindir


def _run(
    old_env: tuple[Path, Path], body: str, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    checkout, bindir = old_env
    script = (
        f'source "{checkout}/.claude/init.sh" >/dev/null 2>&1\n'
        f'PROJECT_PATH="{checkout}"\n'
        f"{body}\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        input=stdin,
        capture_output=True,
        text=True,
        env={"PATH": str(bindir), "HOME": str(checkout), "TMPDIR": str(checkout)},
        timeout=_RUN_TIMEOUT_SECONDS,
        check=False,
    )


def _assert_clean(result: subprocess.CompletedProcess[str]) -> None:
    assert "Traceback" not in result.stderr, result.stderr
    assert "SyntaxError" not in result.stderr, result.stderr


def test_python3_on_path_is_the_old_interpreter(old_env: tuple[Path, Path]) -> None:
    """Guard the harness: the shim really is below the daemon's minimum."""
    result = _run(old_env, "python3 -c 'import sys; print(sys.version_info[1])'")
    assert int(result.stdout) < 11


def test_recovery_advice_runs(old_env: tuple[Path, Path]) -> None:
    result = _run(old_env, "_hooks_daemon_recovery_advice")
    _assert_clean(result)
    assert result.returncode == 0, result.stderr
    assert "TO FIX" in result.stdout


def test_recovery_command_runs(old_env: tuple[Path, Path]) -> None:
    result = _run(old_env, "_hooks_daemon_recovery_command restart")
    _assert_clean(result)
    assert result.returncode in (0, 3), result.stderr


def test_stdin_is_recovery_command_denies_by_default(old_env: tuple[Path, Path]) -> None:
    result = _run(
        old_env,
        "_hooks_daemon_stdin_is_recovery_command",
        '{"tool_name": "Bash", "tool_input": {"command": "ls"}}',
    )
    _assert_clean(result)
    assert result.returncode == 1, result.stderr


def test_root_is_this_install_runs(old_env: tuple[Path, Path]) -> None:
    result = _run(
        old_env, 'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"; _hooks_daemon_root_is_this_install'
    )
    _assert_clean(result)
    assert result.returncode in (0, 1), result.stderr


def test_provision_command_is_recognised(old_env: tuple[Path, Path]) -> None:
    checkout, _ = old_env
    (checkout / ".claude" / "provision.sh").write_text("#!/bin/sh\n")
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "bash .claude/provision.sh"},
            "cwd": str(checkout),
        }
    )
    accepted = _run(old_env, "_hooks_daemon_stdin_is_provision_command", payload)
    _assert_clean(accepted)
    assert accepted.returncode == 0, accepted.stderr
    other = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    refused = _run(old_env, "_hooks_daemon_stdin_is_provision_command", other)
    _assert_clean(refused)
    assert refused.returncode == 1, refused.stderr


def test_needs_provision_answer_without_jq(old_env: tuple[Path, Path]) -> None:
    result = _run(
        old_env,
        '_HOOKS_DAEMON_UNPROVISIONED_MODE=block _HOOKS_DAEMON_UNPROVISIONED_MODE_NOTE="" '
        "_hooks_daemon_emit_needs_provision PreToolUse",
    )
    _assert_clean(result)
    answer = json.loads(result.stdout)
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "provision" in answer["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("event", ["SessionStart", "Stop", "SessionEnd"])
def test_hook_error_encoder_without_jq(old_env: tuple[Path, Path], event: str) -> None:
    result = _run(
        old_env,
        "_HOOKS_DAEMON_NOT_INSTALLED=true\n"
        f'emit_hook_error "{event}" "daemon_not_installed" "no daemon here"',
    )
    _assert_clean(result)
    assert result.returncode == 0, result.stderr
    assert isinstance(json.loads(result.stdout), dict)


def test_transport_reports_a_missing_socket_as_a_deny(old_env: tuple[Path, Path]) -> None:
    """The whole socket-transport snippet parses and runs its failure path on old Python."""
    checkout, _ = old_env
    result = _run(
        old_env,
        f'export HOOKS_DAEMON_EVENTS_DIR="{checkout}/no-events"\n'
        f'send_request_stdin PreToolUse "" "" "" 2>"$PROJECT_PATH/stderr.txt"; '
        'cat "$PROJECT_PATH/stderr.txt" >&2',
        '{"tool_name": "Bash", "tool_input": {"command": "ls"}}',
    )
    _assert_clean(result)
    answer = json.loads(result.stdout)
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_forward_stop_event_blocks_when_daemon_is_down(old_env: tuple[Path, Path]) -> None:
    """forward_stop_event's response reader runs on old Python and turns a block into exit 2."""
    checkout, _ = old_env
    result = _run(
        old_env,
        f'export HOOKS_DAEMON_EVENTS_DIR="{checkout}/no-events"\nforward_stop_event Stop',
        '{"session_id": "s"}',
    )
    _assert_clean(result)
    assert result.returncode == 2, result.stderr
