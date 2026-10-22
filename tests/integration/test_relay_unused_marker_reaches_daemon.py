"""A relay the guard could not run is announced to the daemon (Plan 00529 Task 2c).

The generated relay guard falls through to the bash path when the relay binary
is missing or cannot run, and records that in ``HOOKS_DAEMON_RELAY_UNUSED``.
``init.sh`` must carry it to the daemon as the request envelope's
``relay_unused`` field, so the daemon can add its warning line. The verdict
must be exactly the bash path's, and the forwarder must exit 0.

The per-event nc rung is skipped while the marker is set: it sends the raw
hook input with no envelope, so it has nowhere to carry the field.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants.protocol import RequestEnvelopeField
from tests.integration.test_relay_guard_fail_open import (
    _MAIN_PROBE,
    _TIMEOUT_SECONDS,
    _base_env,
    _live_pid_file,
    _RecordingSocketServer,
    _write_generated_forwarder,
)

_CANNED = (
    b'{"hookSpecificOutput":{"hookEventName":"PreToolUse",'
    b'"permissionDecision":"deny","permissionDecisionReason":"bash path verdict"}}\n'
)
_NC_CANNED = b'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"via-nc"}}\n'

#: What each broken binary holds. The text one prints a forged allow if run.
_BROKEN_BINARIES: dict[str, bytes | None] = {
    "missing": None,
    "corrupt-elf": b"\x7fELF" + bytes(range(256)) * 4,
    "text-garbage": b"echo '{}'\nexit 0\n",
}


@pytest.fixture
def events_dir() -> Iterator[Path]:
    """A short events directory: a Unix socket path must stay under 108 bytes."""
    path = Path(tempfile.mkdtemp(prefix="rlu-"))
    yield path
    shutil.rmtree(path)


@pytest.fixture
def live_pid_file(tmp_path: Path) -> Iterator[Path]:
    with _live_pid_file(tmp_path, tmp_path) as pid_path:
        yield pid_path


def _run(
    tmp_path: Path, events_dir: Path, live_pid_file: Path, binary: bytes | None
) -> tuple[subprocess.CompletedProcess[bytes], _RecordingSocketServer, Path]:
    relay_bin = tmp_path / "bin" / "hooks-relay"
    if binary is not None:
        relay_bin.parent.mkdir(parents=True)
        relay_bin.write_bytes(binary)
        relay_bin.chmod(0o755)
    # nc is enabled too, so the forwarder hands init.sh the per-event socket
    # and the nc rung WOULD run but for the marker.
    transport = TransportConfig(relay_enabled=True, nc_enabled=True, relay_binary=str(relay_bin))
    forwarder = _write_generated_forwarder(
        tmp_path, "pre-tool-use", "PreToolUse", transport, tmp_path / "untracked"
    )
    sock_path = tmp_path / "daemon.sock"
    server = _RecordingSocketServer(sock_path, _CANNED)
    server.start()
    env = _base_env(sock_path, live_pid_file)
    env.pop("HOOKS_DAEMON_RELAY_BINARY", None)
    env["HOOKS_DAEMON_EVENTS_DIR"] = str(events_dir)
    env["HOOKS_DAEMON_NC_UNIX_CAPABLE"] = "1"
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "pwd"}, **_MAIN_PROBE}
    ).encode()
    result = subprocess.run(
        ["bash", str(forwarder)],
        input=payload,
        capture_output=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
    )
    server.join()
    server.close()
    return result, server, relay_bin


@pytest.mark.parametrize("shape", sorted(_BROKEN_BINARIES))
def test_a_broken_relay_is_named_in_the_envelope_and_the_verdict_is_the_bash_paths(
    shape: str, tmp_path: Path, events_dir: Path, live_pid_file: Path
) -> None:
    nc_server = _RecordingSocketServer(events_dir / "pre-tool-use.sock", _NC_CANNED)
    nc_server.start()
    try:
        result, server, relay_bin = _run(
            tmp_path, events_dir, live_pid_file, _BROKEN_BINARIES[shape]
        )
    finally:
        nc_server.close()

    assert result.returncode == 0, result.stderr.decode()
    assert json.loads(result.stdout) == json.loads(_CANNED)
    assert server.received is not None, "the bash path never reached the daemon"
    request = json.loads(server.received)
    assert request[RequestEnvelopeField.RELAY_UNUSED] == str(relay_bin)
    assert request["hook_input"]["tool_input"]["command"] == "pwd"
    assert nc_server.received is None, "the nc rung ran, and it cannot carry the marker"


def test_no_event_socket_sends_no_marker(
    tmp_path: Path, events_dir: Path, live_pid_file: Path
) -> None:
    """No relay socket is the start-up path, which reports for itself."""
    result, server, _ = _run(tmp_path, events_dir, live_pid_file, None)

    assert result.returncode == 0, result.stderr.decode()
    assert server.received is not None
    assert RequestEnvelopeField.RELAY_UNUSED not in json.loads(server.received)


def test_the_init_sh_literal_matches_the_daemon_constant() -> None:
    """init.sh cannot import the constant, so it carries a pinned copy."""
    init_sh = Path(__file__).resolve().parents[2] / "init.sh"
    assert f"_envelope['{RequestEnvelopeField.RELAY_UNUSED}'] = relay_unused" in (
        init_sh.read_text()
    )


def test_the_marker_never_reaches_a_child_process() -> None:
    """init.sh unsets the variable once captured, so a daemon it starts never sees it."""
    init_sh = Path(__file__).resolve().parents[2] / "init.sh"
    env = {**os.environ, "HOOKS_DAEMON_RELAY_UNUSED": "/x/hooks-relay"}
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1" && printf "%s|%s" "$_HOOKS_DAEMON_RELAY_UNUSED" '
            '"$(printenv HOOKS_DAEMON_RELAY_UNUSED || echo unset)"',
            "_",
            str(init_sh),
        ],
        capture_output=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
    )
    assert result.stdout.decode() == "/x/hooks-relay|unset", result.stderr.decode()
