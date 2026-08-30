"""Tests for the daemon's per-event Unix socket listeners (Plan 00290, Task 2.1/2.2).

Covers ``CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md``
§1-§2: one additional listener per wired hook event, bound alongside (never
instead of) the legacy socket; EOF-delimited framing; gated on
``daemon.transport.relay_enabled or nc_enabled``; socket hygiene (wholesale
removal on start, unlink on shutdown).
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import DaemonConfig, TransportConfig
from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.constants.events import wired_event_metas
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked
from claude_code_hooks_daemon.daemon.server import HooksDaemon


class _EchoHandler(Handler):
    """Records the last dispatched hook_input and always allows."""

    def __init__(self) -> None:
        super().__init__(name="echo_handler", priority=Priority.TEST_HANDLER, terminal=True)
        self.last_hook_input: dict[str, Any] | None = None

    def matches(self, hook_input: dict) -> bool:
        return True

    def handle(self, hook_input: dict) -> HookResult:
        self.last_hook_input = hook_input
        return HookResult(decision=Decision.ALLOW, context="echoed")

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list:
        return []


@pytest.fixture
def isolated_untracked_dir() -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def echo_handler() -> _EchoHandler:
    return _EchoHandler()


@pytest.fixture
def front_controller(echo_handler: _EchoHandler) -> FrontController:
    controller = FrontController(event_name="PreToolUse")
    controller.register(echo_handler)
    return controller


def _make_config(untracked_dir: Path, *, relay_enabled: bool = False) -> DaemonConfig:
    return DaemonConfig(
        socket_path=untracked_dir / "daemon.sock",
        pid_file_path=untracked_dir / "daemon.pid",
        idle_timeout_seconds=600,
        log_level="DEBUG",
        transport=TransportConfig(relay_enabled=relay_enabled),
    )


async def _connect_and_send_eof(socket_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """EOF-delimited round trip: write payload, half-close, read to EOF."""
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(json.dumps(payload).encode())
    writer.write_eof()
    await writer.drain()
    raw_response = await reader.read(-1)
    writer.close()
    await writer.wait_closed()
    return dict(json.loads(raw_response.decode()))


class TestGating:
    @pytest.mark.anyio
    async def test_disabled_transport_binds_no_event_sockets(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        config = _make_config(isolated_untracked_dir, relay_enabled=False)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        assert not events_dir.exists()

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_enabled_transport_binds_one_socket_per_wired_event(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        config = _make_config(isolated_untracked_dir, relay_enabled=True)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        assert events_dir.is_dir()
        expected_names = {f"{meta.bash_key}.sock" for meta in wired_event_metas()}
        actual_names = {p.name for p in events_dir.glob("*.sock")}
        assert actual_names == expected_names

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_legacy_socket_protocol_untouched_when_transport_enabled(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        config = _make_config(isolated_untracked_dir, relay_enabled=True)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        reader, writer = await asyncio.open_unix_connection(str(config.socket_path_obj))
        request = {
            "event": "PreToolUse",
            "hook_input": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            "request_id": "legacy-001",
        }
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()
        response = json.loads((await reader.readline()).decode())
        assert response["request_id"] == "legacy-001"
        writer.close()
        await writer.wait_closed()

        await daemon.shutdown()
        await server_task


class TestEofFraming:
    @pytest.mark.anyio
    async def test_event_socket_dispatches_through_same_controller(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
        echo_handler: _EchoHandler,
    ) -> None:
        config = _make_config(isolated_untracked_dir, relay_enabled=True)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        # EOF framing: no {"event", "hook_input"} envelope — the raw hook
        # payload only, exactly what Claude Code writes to the forwarder's
        # stdin (DESIGN §2). The event comes from WHICH socket, not the body.
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        response = await _connect_and_send_eof(socket_path, hook_input)

        assert echo_handler.last_hook_input == hook_input
        assert "hookSpecificOutput" in response

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_malformed_json_fails_open_with_empty_object(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        config = _make_config(isolated_untracked_dir, relay_enabled=True)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        writer.write(b"{not valid json")
        writer.write_eof()
        await writer.drain()
        raw_response = await reader.read(-1)
        writer.close()
        await writer.wait_closed()

        assert json.loads(raw_response.decode()) == {}

        await daemon.shutdown()
        await server_task


class TestSocketHygiene:
    @pytest.mark.anyio
    async def test_preexisting_events_dir_removed_wholesale_on_start(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        events_dir.mkdir(parents=True)
        stale_file = events_dir / "leftover-from-a-dead-daemon.sock"
        stale_file.write_text("")
        assert stale_file.exists()

        config = _make_config(isolated_untracked_dir, relay_enabled=True)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        assert not stale_file.exists()
        assert events_dir.is_dir()

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_shutdown_unlinks_event_sockets_and_removes_dir(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        config = _make_config(isolated_untracked_dir, relay_enabled=True)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        assert events_dir.is_dir()

        await daemon.shutdown()
        await server_task

        assert not events_dir.exists()
