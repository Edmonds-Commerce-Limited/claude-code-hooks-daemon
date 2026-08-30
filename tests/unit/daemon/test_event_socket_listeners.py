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
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import DaemonConfig, TransportConfig
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.events import wired_event_metas
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.daemon.paths import (
    _UNIX_SOCKET_PATH_LIMIT,
    get_event_socket_dir_from_untracked,
)
from claude_code_hooks_daemon.daemon.server import HooksDaemon


class _EchoHandler(Handler):
    """Records the last dispatched hook_input and always allows."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER, terminal=True
        )
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

        # hook_event_name enrichment (Plan 00290 defect 2 fix): the daemon
        # injects it from the socket identity when the payload omits it —
        # see test_event_socket_hook_event_name_enrichment.py for the
        # dedicated coverage of that behaviour.
        assert echo_handler.last_hook_input == {**hook_input, "hook_event_name": "PreToolUse"}
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


class TestRealisticClientDepth:
    """Plan 00290 F3 fix (canary run 2): the canary daemon bound only 7/31
    per-event sockets at a standard, deeply-nested client checkout layout.
    Binds ALL wired events at a realistic client-depth ``untracked_dir`` and
    asserts every one succeeds — the fallback-dir fix under test."""

    @pytest.mark.anyio
    async def test_all_wired_events_bind_at_realistic_client_depth(
        self, front_controller: FrontController
    ) -> None:
        # Mirrors a standard, deeply-nested client checkout layout: the
        # LEGACY socket (`untracked/daemon.sock`) still comfortably fits the
        # AF_UNIX limit, but the natural `events{suffix}/<event>.sock` path
        # does not — the exact shape the canary found only 7/31 bound at.
        # Built from a fresh `tempfile.mkdtemp()` root (short and
        # pytest-prefix-independent, unlike `tmp_path`) plus a filler
        # component sized to land `untracked_dir` reliably in that window
        # regardless of the base path's own length.
        base = Path(tempfile.mkdtemp())
        target_untracked_len = 75  # comfortably: legacy fits, events overflows
        filler_len = max(1, target_untracked_len - len(str(base)) - len("/untracked") - 1)
        deep_untracked_dir = base / ("x" * filler_len) / "untracked"
        deep_untracked_dir.mkdir(parents=True)
        legacy_socket_len = len(str(deep_untracked_dir / "daemon.sock"))
        assert legacy_socket_len <= _UNIX_SOCKET_PATH_LIMIT, (
            f"test fixture invariant broken: legacy socket path itself too long "
            f"({legacy_socket_len} chars) — adjust target_untracked_len"
        )

        config = _make_config(deep_untracked_dir, relay_enabled=True)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        expected_names = {f"{meta.bash_key}.sock" for meta in wired_event_metas()}
        assert len(daemon._event_servers) == len(expected_names), (
            f"expected all {len(expected_names)} wired events bound, "
            f"got {len(daemon._event_servers)}: {sorted(daemon._event_servers)}"
        )

        await daemon.shutdown()
        await server_task


class TestBindShortfallIsSurfaced:
    """Plan 00290 F3 fix (canary run 2): a shortfall must be surfaced as one
    summary WARNING line, not just individual per-socket skips easy to miss
    in a long log."""

    @pytest.mark.anyio
    async def test_shortfall_logs_a_summary_warning(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
    ) -> None:
        # Reads the daemon's own in-memory log buffer (what `bin/hooks-daemon
        # logs` surfaces) rather than pytest's caplog — HooksDaemon's own
        # `_setup_logging` clears the root logger's handlers at construction
        # time, which would otherwise discard caplog's handler too.
        from claude_code_hooks_daemon.daemon import paths as paths_module
        from claude_code_hooks_daemon.daemon.server import get_memory_logs

        real_resolver = paths_module.get_event_socket_path_in_dir

        def _flaky_resolver(events_dir: Path, event_file_name: str) -> Path | None:
            # Simulate 2 of the wired events being unbindable at path-length.
            if event_file_name in {"pre-tool-use", "post-tool-use"}:
                return None
            return real_resolver(events_dir, event_file_name)

        config = _make_config(isolated_untracked_dir, relay_enabled=True)
        daemon = HooksDaemon(config=config, controller=front_controller)

        with patch.object(
            paths_module, "get_event_socket_path_in_dir", side_effect=_flaky_resolver
        ):
            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)
            await daemon.shutdown()
            await server_task

        expected_total = len(wired_event_metas())
        bound_count = expected_total - 2
        logs = "\n".join(get_memory_logs())
        assert f"Only {bound_count}/{expected_total} per-event socket(s) bound" in logs


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
