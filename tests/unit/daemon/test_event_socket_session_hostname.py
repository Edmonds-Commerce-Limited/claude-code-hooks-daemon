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
from typing import Any, cast

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
from claude_code_hooks_daemon.daemon import server
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked
from claude_code_hooks_daemon.daemon.server import HooksDaemon
from claude_code_hooks_daemon.utils.cron_hosts import PeerHostname

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


class TestAnUnreadablePeerStampsNothing:
    """A peer whose environment cannot be read is not a peer that set nothing:
    the reader says so, and the stamp step alone decides to stamp nothing."""

    def test_the_payload_is_left_without_a_stamp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            server,
            "_peer_hostname",
            lambda writer, peer=None: PeerHostname(unreadable_because="gone"),
        )
        payload: dict[str, Any] = {"hook_event_name": "Stop"}
        # _peer_hostname is replaced above, so the writer is never touched.
        unused_writer = cast("asyncio.StreamWriter", object())

        server._stamp_session_hostname(payload, unused_writer)

        assert payload == {"hook_event_name": "Stop"}


class TestPeerPidStamp:
    """Plan 00470 Task 6.4: the connected hook's pid is stamped for thread grouping."""

    _writer = cast("asyncio.StreamWriter", object())

    def test_a_known_pid_is_stamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "_peer_pid", lambda writer: (4242, None))
        payload: dict[str, Any] = {"hook_event_name": "Stop"}

        server._stamp_peer_pid(payload, self._writer)

        assert payload[HookInputField.PEER_PID] == 4242

    @pytest.mark.parametrize("pid", [0, -1])
    def test_a_non_positive_pid_stamps_nothing(
        self, monkeypatch: pytest.MonkeyPatch, pid: int
    ) -> None:
        monkeypatch.setattr(server, "_peer_pid", lambda writer: (pid, None))
        payload: dict[str, Any] = {"hook_event_name": "Stop"}

        server._stamp_peer_pid(payload, self._writer)

        assert HookInputField.PEER_PID not in payload

    def test_an_unknown_pid_stamps_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "_peer_pid", lambda writer: (None, "no SO_PEERCRED"))
        payload: dict[str, Any] = {"hook_event_name": "Stop"}

        server._stamp_peer_pid(payload, self._writer)

        assert HookInputField.PEER_PID not in payload

    def test_a_caller_supplied_value_is_replaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "_peer_pid", lambda writer: (4242, None))
        payload: dict[str, Any] = {HookInputField.PEER_PID: 7}

        server._stamp_peer_pid(payload, self._writer)

        assert payload[HookInputField.PEER_PID] == 4242

    @pytest.mark.parametrize("known", [(None, "no SO_PEERCRED"), (0, None)])
    def test_a_caller_supplied_value_is_removed_when_the_pid_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch, known: tuple[int | None, str | None]
    ) -> None:
        monkeypatch.setattr(server, "_peer_pid", lambda writer: known)
        payload: dict[str, Any] = {HookInputField.PEER_PID: 7}

        server._stamp_peer_pid(payload, self._writer)

        assert HookInputField.PEER_PID not in payload

    def test_an_already_queried_peer_is_not_queried_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fail(writer: object) -> tuple[int | None, str | None]:
            raise AssertionError("SO_PEERCRED queried twice")

        monkeypatch.setattr(server, "_peer_pid", _fail)
        payload: dict[str, Any] = {}

        server._stamp_peer_pid(payload, self._writer, (99, None))
        server._stamp_session_hostname(payload, self._writer, (None, "unreadable"))

        assert payload == {HookInputField.PEER_PID: 99}

    def test_a_non_dict_payload_is_left_unchanged(self) -> None:
        payload = ["not", "a", "dict"]

        server._stamp_peer_pid(payload, self._writer, (4242, None))

        assert payload == ["not", "a", "dict"]

    @pytest.mark.anyio
    async def test_the_legacy_socket_replaces_a_forged_pid_with_the_connections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_handle_client`` hands the connection's own peer pid to ``_process_request``."""
        seen: dict[str, Any] = {}
        controller = FrontController(event_name="Stop")
        daemon = HooksDaemon(config=_config(Path(tempfile.mkdtemp())), controller=controller)
        monkeypatch.setattr(
            HooksDaemon,
            "_capture_payload_best_effort",
            lambda self, event, hook_input: seen.update(hook_input),
        )
        request = json.dumps(
            {"event": "Stop", "hook_input": {"hook_event_name": "Stop", HookInputField.PEER_PID: 7}}
        )

        await daemon._process_request(request, peer=(31337, None))

        assert seen[HookInputField.PEER_PID] == 31337

    @pytest.mark.anyio
    async def test_the_event_path_does_not_strip_what_it_already_stamped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}
        controller = FrontController(event_name="Stop")
        daemon = HooksDaemon(config=_config(Path(tempfile.mkdtemp())), controller=controller)
        monkeypatch.setattr(
            HooksDaemon,
            "_capture_payload_best_effort",
            lambda self, event, hook_input: seen.update(hook_input),
        )
        request = json.dumps(
            {"event": "Stop", "hook_input": {"hook_event_name": "Stop", HookInputField.PEER_PID: 8}}
        )

        await daemon._process_request(request)

        assert seen[HookInputField.PEER_PID] == 8

    def test_the_peer_pid_query_reports_a_connection_without_a_socket(self) -> None:
        class _NoSocketWriter:
            def get_extra_info(self, name: str) -> None:
                return None

        pid, reason = server._peer_pid(cast("asyncio.StreamWriter", _NoSocketWriter()))

        assert pid is None
        assert reason is not None

    @pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs SO_PEERCRED")
    @pytest.mark.anyio
    async def test_the_clients_pid_reaches_the_handler(self, untracked_dir: Path) -> None:
        seen = await _run(untracked_dir, {"hook_event_name": "Stop"}, _client_env())

        assert seen is not None
        stamped = seen[HookInputField.PEER_PID]
        assert isinstance(stamped, int)
        assert stamped > 1
        assert stamped != os.getpid()


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
