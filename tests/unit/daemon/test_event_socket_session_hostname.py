"""The session's hostname override reaches the daemon over the byte-pump relay.

Plan 00470 Task 6.1 (issues #60, #62). ``persistent_crons`` jobs can carry
``hosts:``, matched against the hostname the SESSION exported
(``HOOKS_DAEMON_HOSTNAME``, then ``CCY_HOST_HOSTNAME``). The daemon is a
long-lived process whose environment is NOT the session's, and the relay is a
byte pump that never parses or rewrites the payload, so nothing in the payload
carries the variable. The daemon therefore reads it from the process on the
other end of the per-event socket (``SO_PEERCRED`` then ``/proc/<pid>/environ``)
and stamps it on the payload as ``hooks_daemon_hostname``.

The client below is a REAL separate process with its own environment, so the
test fails if the daemon's own environment were what got read.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from tests.daemon._start_wait import wait_for_daemon_started

from claude_code_hooks_daemon.config.models import (
    DaemonConfig,
    InputValidationConfig,
    LogLevel,
    TransportConfig,
)
from claude_code_hooks_daemon.constants import HandlerID, Priority, Timeout
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked
from claude_code_hooks_daemon.daemon.server import HooksDaemon

# A client that behaves like the relay: write the payload, half-close, read to EOF.
_CLIENT = """
import json, socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(sys.argv[1])
sock.sendall(sys.stdin.buffer.read())
sock.shutdown(socket.SHUT_WR)
while sock.recv(4096):
    pass
"""


class _EchoHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER, terminal=True
        )
        self.last_hook_input: dict[str, Any] | None = None

    def matches(self, hook_input: dict) -> bool:
        return True

    def handle(self, hook_input: dict) -> HookResult:
        self.last_hook_input = hook_input
        return HookResult(decision=Decision.ALLOW, context=["echoed"])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list:
        return []


@pytest.fixture
def untracked_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _config(untracked_dir: Path) -> DaemonConfig:
    return DaemonConfig(
        socket_path=untracked_dir / "daemon.sock",
        pid_file_path=untracked_dir / "daemon.pid",
        idle_timeout_seconds=600,
        log_level=LogLevel.DEBUG,
        transport=TransportConfig(relay_enabled=True),
        strict_mode=False,
        input_validation=InputValidationConfig(enabled=False),
    )


async def _send_from_a_process(
    socket_path: Path, payload: dict[str, Any], env: dict[str, str]
) -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _CLIENT,
        str(socket_path),
        stdin=asyncio.subprocess.PIPE,
        env=env,
    )
    await proc.communicate(json.dumps(payload).encode())
    assert proc.returncode == 0


def _client_env(**extra: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"HOOKS_DAEMON_HOSTNAME", "CCY_HOST_HOSTNAME"}
    }
    env.update(extra)
    return env


async def _run(
    untracked_dir: Path, payload: dict[str, Any], env: dict[str, str]
) -> dict[str, Any] | None:
    handler = _EchoHandler()
    controller = FrontController(event_name="Stop")
    controller.register(handler)
    daemon = HooksDaemon(config=_config(untracked_dir), controller=controller)
    server_task = asyncio.create_task(daemon.start())
    await wait_for_daemon_started(daemon, server_task, timeout=Timeout.SOCKET_CONNECT)
    try:
        socket_path = get_event_socket_dir_from_untracked(untracked_dir) / "stop.sock"
        await _send_from_a_process(socket_path, payload, env)
    finally:
        await daemon.shutdown()
        await server_task
    return handler.last_hook_input


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc/<pid>/environ")
class TestPeerEnvironmentIsStamped:
    @pytest.mark.anyio
    async def test_the_clients_override_is_stamped_even_though_the_daemon_lacks_it(
        self, untracked_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_HOSTNAME", raising=False)
        seen = await _run(
            untracked_dir,
            {"hook_event_name": "Stop", "session_crons": []},
            _client_env(HOOKS_DAEMON_HOSTNAME="cchd-sdlc-runner"),
        )
        assert seen is not None
        assert seen[HookInputField.SESSION_HOSTNAME] == "cchd-sdlc-runner"

    @pytest.mark.anyio
    async def test_the_clients_value_beats_the_daemons_own_environment(
        self, untracked_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "daemon-own-env")
        seen = await _run(
            untracked_dir,
            {"hook_event_name": "Stop"},
            _client_env(CCY_HOST_HOSTNAME="session-host"),
        )
        assert seen is not None
        assert seen[HookInputField.SESSION_HOSTNAME] == "session-host"

    @pytest.mark.anyio
    async def test_a_client_with_no_override_stamps_nothing(
        self, untracked_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "daemon-own-env")
        seen = await _run(untracked_dir, {"hook_event_name": "Stop"}, _client_env())
        assert seen is not None
        assert HookInputField.SESSION_HOSTNAME not in seen

    @pytest.mark.anyio
    async def test_a_value_already_on_the_payload_is_kept(
        self, untracked_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The python transport stamps it itself; the daemon never overwrites that."""
        monkeypatch.delenv("HOOKS_DAEMON_HOSTNAME", raising=False)
        seen = await _run(
            untracked_dir,
            {"hook_event_name": "Stop", HookInputField.SESSION_HOSTNAME: "from-transport"},
            _client_env(HOOKS_DAEMON_HOSTNAME="peer-env"),
        )
        assert seen is not None
        assert seen[HookInputField.SESSION_HOSTNAME] == "from-transport"
