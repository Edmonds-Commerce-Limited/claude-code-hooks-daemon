"""``_handle_event_client`` must deny PreToolUse, not fail open with ``{}``.

Plan 00466 N40 review 2 MA3: an oversized/malformed/undecodable payload on
the per-event socket, and the generic ``except`` in ``_handle_event_client``,
both answered a bare ``{}`` -- indistinguishable from a real judged "allow,
nothing to add" verdict to whatever reads it next (the relay, or a direct
per-event-socket client). Every OTHER fail-closed guarantee this project
claims (M1, N25, m5) holds on the legacy socket; this is the per-event-socket
twin, and the one the shipped relay actually talks to.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    DaemonConfig,
    InputValidationConfig,
    LogLevel,
    TransportConfig,
)
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.protocol import SocketLimit
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked
from claude_code_hooks_daemon.daemon.server import HooksDaemon


class _AllowHandler(Handler):
    """A trivial handler that always allows -- never reached by these tests,
    since every payload here fails before dispatch, but a controller needs
    at least one handler to construct."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER, terminal=True
        )

    def matches(self, hook_input: dict) -> bool:
        return True

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list:
        return []


@pytest.fixture
def isolated_untracked_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def front_controller() -> FrontController:
    controller = FrontController(event_name="PreToolUse")
    controller.register(_AllowHandler())
    return controller


def _make_config(untracked_dir: Path) -> DaemonConfig:
    return DaemonConfig(
        socket_path=untracked_dir / "daemon.sock",
        pid_file_path=untracked_dir / "daemon.pid",
        idle_timeout_seconds=600,
        log_level=LogLevel.DEBUG,
        transport=TransportConfig(relay_enabled=True),
        strict_mode=True,
        input_validation=InputValidationConfig(enabled=True),
    )


async def _send_raw_and_read(socket_path: Path, raw: bytes) -> dict[str, Any]:
    """Write raw bytes (not necessarily valid JSON), half-close, read to EOF."""
    import json

    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(raw)
    writer.write_eof()
    await writer.drain()
    raw_response = await reader.read(-1)
    writer.close()
    await writer.wait_closed()
    return dict(json.loads(raw_response.decode()))


def _is_pre_tool_use_deny(response: dict[str, Any]) -> bool:
    hso = response.get("hookSpecificOutput")
    return (
        isinstance(hso, dict)
        and hso.get("hookEventName") == "PreToolUse"
        and hso.get("permissionDecision") == "deny"
    )


class TestMalformedPayloadFailsClosedOnPreToolUseSocket:
    @pytest.mark.anyio
    async def test_undecodable_bytes_deny_on_pre_tool_use_socket(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        response = await _send_raw_and_read(socket_path, b"\xff\xfe not valid utf-8 or json")

        assert response != {}, response
        assert _is_pre_tool_use_deny(response), response

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_oversized_payload_denies_on_pre_tool_use_socket(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        oversized = b"{" + b"x" * (SocketLimit.REQUEST_BUFFER_BYTES + 1024)
        response = await _send_raw_and_read(socket_path, oversized)

        assert response != {}, response
        assert _is_pre_tool_use_deny(response), response

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_malformed_payload_on_non_pre_tool_use_socket_stays_fail_open(
        self, isolated_untracked_dir: Path, front_controller: FrontController
    ) -> None:
        """Only PreToolUse changes; every other event keeps the original
        fail-open `{}` contract -- it never gates a real tool call."""
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "status-line.sock"

        response = await _send_raw_and_read(socket_path, b"\xff\xfe not valid utf-8 or json")

        assert response == {}, response

        await daemon.shutdown()
        await server_task


class TestNonVerdictResponseFailsClosedOnPreToolUseSocket:
    """Plan 00466 N24 review 3 MA2: ``_process_request`` can answer WITHOUT
    raising -- an ``invalid_request``/``input_validation_failed`` error
    envelope, or any other shape that is not one of PreToolUse's two
    legitimate verdict shapes. The relay only pumps bytes and cannot tell
    such a response apart from a real judged allow, so the daemon itself
    must refuse to put it on the PreToolUse wire."""

    @pytest.mark.anyio
    async def test_error_envelope_denies_on_pre_tool_use_socket(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)

        async def _non_verdict(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"error": "input_validation_failed"}

        monkeypatch.setattr(HooksDaemon, "_process_request", _non_verdict)

        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        payload = (
            b'{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"true"}}'
        )
        response = await _send_raw_and_read(socket_path, payload)

        assert response != {"error": "input_validation_failed"}, response
        assert _is_pre_tool_use_deny(response), response

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_malformed_result_envelope_denies_on_pre_tool_use_socket(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)

        async def _non_verdict(*args: Any, **kwargs: Any) -> dict[str, Any]:
            # controller.py's invalid_request path shape -- Claude Code never
            # reads this key, so it is an ambiguous ALLOW on the old wire.
            return {"result": {"decision": "deny", "reason": "invalid_request"}}

        monkeypatch.setattr(HooksDaemon, "_process_request", _non_verdict)

        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        payload = (
            b'{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"true"}}'
        )
        response = await _send_raw_and_read(socket_path, payload)

        assert "result" not in response, response
        assert _is_pre_tool_use_deny(response), response

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_non_verdict_response_on_non_pre_tool_use_socket_passes_through(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only the PreToolUse wire gets this new server-side validation --
        every other event's response shape is untouched."""
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)

        async def _non_verdict(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"error": "input_validation_failed"}

        monkeypatch.setattr(HooksDaemon, "_process_request", _non_verdict)

        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "status-line.sock"

        response = await _send_raw_and_read(socket_path, b'{"hook_event_name":"Status"}')

        assert response == {"error": "input_validation_failed"}, response

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_real_judged_deny_passes_through_unchanged(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
    ) -> None:
        """The new validation must never reject a REAL verdict."""
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        payload = (
            b'{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"true"}}'
        )
        response = await _send_raw_and_read(socket_path, payload)

        # _AllowHandler always allows, so this is a genuine judged verdict --
        # HookResult.to_json's documented empty-response shape for "allow,
        # nothing to add".
        assert response == {}, response

        await daemon.shutdown()
        await server_task


class TestGenericExceptionFailsClosedOnPreToolUseSocket:
    @pytest.mark.anyio
    async def test_process_request_exception_denies_on_pre_tool_use_socket(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)

        async def _boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("simulated daemon-side crash")

        monkeypatch.setattr(HooksDaemon, "_process_request", _boom)

        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "pre-tool-use.sock"

        payload = (
            b'{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"true"}}'
        )
        response = await _send_raw_and_read(socket_path, payload)

        assert response != {}, response
        assert _is_pre_tool_use_deny(response), response

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_process_request_exception_on_non_pre_tool_use_socket_stays_fail_open(
        self,
        isolated_untracked_dir: Path,
        front_controller: FrontController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config = _make_config(isolated_untracked_dir)
        daemon = HooksDaemon(config=config, controller=front_controller)

        async def _boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("simulated daemon-side crash")

        monkeypatch.setattr(HooksDaemon, "_process_request", _boom)

        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        events_dir = get_event_socket_dir_from_untracked(isolated_untracked_dir)
        socket_path = events_dir / "status-line.sock"

        payload = b'{"hook_event_name":"Status"}'
        response = await _send_raw_and_read(socket_path, payload)

        assert response == {}, response

        await daemon.shutdown()
        await server_task
