"""Regression: per-event sockets must inject ``hook_event_name`` when the
real Claude Code payload omits it (Plan 00290 dogfood field report, commit
9d353fd3 EMERGENCY suspension, defect 2).

Field report: with relay dogfooded, the Status per-event socket rejected the
real payload with ``Input validation failed for Status (strict mode):
'hook_event_name' is a required property``. The LEGACY bash transport never
hits this because the python3 rung injects ``hook_input['hook_event_name'] =
event_name`` itself before dispatch (``.claude/init.sh``'s
``send_request_stdin``, the Status-line special case) — a byte-pump relay
structurally cannot perform that injection (it never parses JSON), so the
enrichment must happen DAEMON-SIDE, in ``_handle_event_client``, which
already knows the wire event name from which socket the connection arrived
on.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    DaemonConfig,
    InputValidationConfig,
    TransportConfig,
)
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked
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
    # A single controller instance dispatches whatever event name is passed
    # to it at request time (LegacyController resolves handlers per event
    # internally) — reused across the Status/PreToolUse sub-tests below.
    controller = FrontController(event_name="PreToolUse")
    controller.register(echo_handler)
    return controller


def _make_strict_config(untracked_dir: Path) -> DaemonConfig:
    """Mirrors this project's own shipped `.claude/hooks-daemon.yaml`
    (`daemon.strict_mode: true`, `input_validation.enabled/strict_mode:
    true`) — the "shipped default" strict-validation posture the real
    dogfood session ran under when this defect was found live."""
    return DaemonConfig(
        socket_path=untracked_dir / "daemon.sock",
        pid_file_path=untracked_dir / "daemon.pid",
        idle_timeout_seconds=600,
        log_level="DEBUG",
        transport=TransportConfig(relay_enabled=True),
        strict_mode=True,
        input_validation=InputValidationConfig(enabled=True),
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


class TestHookEventNameEnrichment:
    @pytest.mark.anyio
    async def test_status_payload_missing_hook_event_name_is_enriched_not_rejected(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
        echo_handler: _EchoHandler,
    ) -> None:
        """RED reproduction of the live defect: a REALISTIC Status payload —
        exactly what Claude Code sends, with NO hook_event_name (see
        CLAUDE/Architecture/StatusLine.md: the wrapper/daemon must inject it,
        Claude Code never sends it for the status line) — must not be
        rejected by strict-mode input validation on the per-event socket."""
        config = _make_strict_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "status-line.sock"

        realistic_status_payload = {
            "model": {"display_name": "Claude Sonnet 4.5", "id": "claude-sonnet-4-5-20250929"},
            "context_window": {"used_percentage": 25.0},
            "workspace": {"current_dir": "/workspace", "project_dir": "/workspace"},
        }
        response = await _connect_and_send_eof(socket_path, realistic_status_payload)

        assert response.get("error") != "input_validation_failed", response
        assert echo_handler.last_hook_input is not None
        assert echo_handler.last_hook_input.get("hook_event_name") == "Status"

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_payload_already_carrying_hook_event_name_is_left_untouched(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
        echo_handler: _EchoHandler,
    ) -> None:
        """The common case (PreToolUse etc. — Claude Code sends
        hook_event_name itself): enrichment must never override an existing
        value."""
        config = _make_strict_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        response = await _connect_and_send_eof(socket_path, payload)

        assert response.get("error") != "input_validation_failed", response
        assert echo_handler.last_hook_input == payload

        await daemon.shutdown()
        await server_task
