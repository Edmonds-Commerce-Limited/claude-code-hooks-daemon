"""Status per-event socket raw-text mode (issue #131, Plan 00542 Phase 1).

A Status request carrying ``hooks_daemon_raw_text: true`` is answered with the
exact bytes the init.sh python rung would print (``text`` plus a newline), or an
EMPTY body when the response is an error or carries no text, so a shell client
with no JSON parser can tell success from fall-through. A request without the
flag is answered with the JSON response exactly as before.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from tests.daemon._start_wait import wait_for_daemon_started

from claude_code_hooks_daemon.config.models import DaemonConfig, LogLevel, TransportConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.constants.protocol import HookInputField, RawTextReply
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked
from claude_code_hooks_daemon.daemon.server import HooksDaemon, _raw_text_reply
from claude_code_hooks_daemon.utils.cron_hosts import PeerHostname

SENTINEL = RawTextReply.SENTINEL.encode()


class TestRawTextReply:
    """The pure response-to-bytes mapping."""

    def test_text_starts_with_the_sentinel_and_ends_with_a_newline(self) -> None:
        reply = _raw_text_reply({"text": "model | 25%"})
        assert reply == SENTINEL + b"model | 25%\n"
        assert reply.startswith(b"\x1e")

    def test_non_ascii_text_is_utf8(self) -> None:
        assert _raw_text_reply({"text": "⚠ ok"}) == SENTINEL + "⚠ ok\n".encode()

    @pytest.mark.parametrize("response", [{"error": "boom"}, {"error": "boom", "text": "stale"}])
    def test_an_error_is_the_python_rungs_error_line(self, response: dict[str, Any]) -> None:
        assert _raw_text_reply(response) == SENTINEL + "⚠️ ERROR: boom\n".encode()

    @pytest.mark.parametrize("response", [{}, {"text": ""}, {"text": None}, {"text": 5}])
    def test_no_text_is_the_python_rungs_no_data_line(self, response: dict[str, Any]) -> None:
        assert _raw_text_reply(response) == SENTINEL + "⚠️ NO STATUS DATA\n".encode()


@pytest.fixture(autouse=True)
def _no_session_hostname_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "claude_code_hooks_daemon.daemon.server.hostname_override_of_process",
        lambda pid: PeerHostname(),
    )


@pytest.fixture
def isolated_untracked_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


async def _round_trip(socket_path: Path, payload: dict[str, Any]) -> bytes:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
    writer.write(json.dumps(payload).encode())
    writer.write_eof()
    await writer.drain()
    raw = await reader.read(-1)
    writer.close()
    await writer.wait_closed()
    return raw


class TestRawTextOverTheSocket:
    @pytest.mark.anyio
    async def test_raw_request_matches_json_text_and_non_raw_is_unchanged(
        self, isolated_untracked_dir: Path
    ) -> None:
        config = DaemonConfig(
            socket_path=isolated_untracked_dir / "daemon.sock",
            pid_file_path=isolated_untracked_dir / "daemon.pid",
            idle_timeout_seconds=600,
            log_level=LogLevel.DEBUG,
            transport=TransportConfig(relay_enabled=True),
        )
        daemon = HooksDaemon(config=config, controller=FrontController(event_name="Status"))
        server_task = asyncio.create_task(daemon.start())
        await wait_for_daemon_started(daemon, server_task, timeout=Timeout.SOCKET_CONNECT)
        sock = get_event_socket_dir_from_untracked(isolated_untracked_dir) / "status-line.sock"
        payload: dict[str, Any] = {"model": {"display_name": "M"}}

        plain = json.loads((await _round_trip(sock, dict(payload))).decode())
        assert isinstance(plain, dict)
        assert HookInputField.RAW_TEXT not in plain

        raw = await _round_trip(sock, {**payload, HookInputField.RAW_TEXT: True})
        text = plain.get("text")
        if plain.get("error") or not isinstance(text, str) or not text:
            assert raw.startswith(SENTINEL + "⚠️ ".encode())
        else:
            assert raw == SENTINEL + text.encode() + b"\n"

        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_raw_flag_is_ignored_on_other_events(self, isolated_untracked_dir: Path) -> None:
        config = DaemonConfig(
            socket_path=isolated_untracked_dir / "daemon.sock",
            pid_file_path=isolated_untracked_dir / "daemon.pid",
            idle_timeout_seconds=600,
            log_level=LogLevel.DEBUG,
            transport=TransportConfig(relay_enabled=True),
        )
        daemon = HooksDaemon(config=config, controller=FrontController(event_name="Stop"))
        server_task = asyncio.create_task(daemon.start())
        await wait_for_daemon_started(daemon, server_task, timeout=Timeout.SOCKET_CONNECT)
        sock = get_event_socket_dir_from_untracked(isolated_untracked_dir) / "stop.sock"

        raw = await _round_trip(sock, {"hook_event_name": "Stop", HookInputField.RAW_TEXT: True})
        assert isinstance(json.loads(raw.decode()), dict)

        await daemon.shutdown()
        await server_task
