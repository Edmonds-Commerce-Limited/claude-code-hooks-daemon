"""A client that hangs up is not a daemon error.

Found by dogfooding: `bin/hooks-daemon logs | grep -i error` — the check this
project's own docs tell agents to run after every change — was reporting an
ERROR with two chained tracebacks (`ConnectionResetError` then
`BrokenPipeError`) on an ordinary daemon restart. Nothing was wrong. A client
had simply gone away before its response was delivered, the generic
`except Exception` caught it, and the attempt to report the failure back down
the same dead socket produced the second traceback.

That matters because the noise is in a diagnostic channel: an agent told to
grep for errors after a change finds one that has nothing to do with the
change, and either chases it or learns to ignore the channel.

The disconnect is still not silent. It is CLASSIFIED, and the classification
carries information the generic handler threw away: if the undelivered
response was a BLOCKING one, the hook's decision never reached Claude Code and
the tool call was not gated. That is worth a warning. An undelivered ALLOW is
not.

These tests read the server module's own logger rather than ``caplog``. The
daemon installs its own handlers and records do not reach the root logger, so
``caplog.records`` is empty here whatever the code does — an assertion written
against it passes for the wrong reason, which is how the first draft of this
file "passed" before the fix existed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from claude_code_hooks_daemon.config.models import DaemonConfig
from claude_code_hooks_daemon.daemon import server as server_module
from claude_code_hooks_daemon.daemon.server import HooksDaemon

_ALLOW_RESPONSE: dict[str, Any] = {
    "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
}
_DENY_RESPONSE: dict[str, Any] = {
    "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"}
}

_REQUEST_LINE = b'{"event":"PreToolUse","hook_input":{}}\n'


class _StubController:
    """Never consulted — ``_process_request`` is patched in every test here."""

    def process_request(self, request_data: dict[str, Any]) -> dict[str, Any]:
        return _ALLOW_RESPONSE

    def get_health(self) -> dict[str, Any]:
        return {"status": "healthy", "handlers": {}}

    def get_handlers(self) -> dict[str, list[dict[str, Any]]]:
        return {}

    def get_mode(self) -> dict[str, Any]:
        return {"mode": "default", "custom_message": None}

    def set_mode(self, mode: Any, custom_message: str | None = None) -> bool:
        return True


class _Collector(logging.Handler):
    """Captures records straight off the module logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def logged() -> Iterator[_Collector]:
    collector = _Collector()
    logger = server_module.logger
    previous_level = logger.level
    logger.addHandler(collector)
    logger.setLevel(logging.DEBUG)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous_level)


def _make_daemon(tmp_path: Path) -> HooksDaemon:
    config = DaemonConfig(
        socket_path=tmp_path / "daemon.sock",
        pid_file_path=None,
        idle_timeout_seconds=600,
        log_level="DEBUG",
    )
    return HooksDaemon(config=config, controller=_StubController())


def _streams(*, drain_error: BaseException | None = None) -> tuple[AsyncMock, AsyncMock]:
    reader = AsyncMock(spec=asyncio.StreamReader)
    writer = AsyncMock(spec=asyncio.StreamWriter)
    reader.readline.return_value = _REQUEST_LINE
    if drain_error is not None:
        writer.drain.side_effect = drain_error
    return reader, writer


def _at_least(collector: _Collector, level: int) -> list[logging.LogRecord]:
    return [record for record in collector.records if record.levelno >= level]


def _exactly(collector: _Collector, level: int) -> list[logging.LogRecord]:
    return [record for record in collector.records if record.levelno == level]


def _returning(response: dict[str, Any]) -> Any:
    return patch.object(HooksDaemon, "_process_request", new=AsyncMock(return_value=response))


class TestDeadPeerIsNotAnError:
    @pytest.mark.anyio
    async def test_reset_while_delivering_an_allow_logs_no_error(
        self, tmp_path: Path, logged: _Collector
    ) -> None:
        """THE regression: an ordinary disconnect produced an ERROR + traceback."""
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams(drain_error=ConnectionResetError("peer went away"))

        with _returning(_ALLOW_RESPONSE):
            await daemon._handle_client(reader, writer)

        assert _at_least(logged, logging.ERROR) == []

    @pytest.mark.anyio
    async def test_reset_while_delivering_an_allow_is_still_reported(
        self, tmp_path: Path, logged: _Collector
    ) -> None:
        """Not silent — classified. Silent suppression is its own defect."""
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams(drain_error=ConnectionResetError("peer went away"))

        with _returning(_ALLOW_RESPONSE):
            await daemon._handle_client(reader, writer)

        assert any("disconnect" in record.getMessage().lower() for record in logged.records)

    @pytest.mark.anyio
    async def test_broken_pipe_is_treated_the_same_as_a_reset(
        self, tmp_path: Path, logged: _Collector
    ) -> None:
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams(drain_error=BrokenPipeError("peer is gone"))

        with _returning(_ALLOW_RESPONSE):
            await daemon._handle_client(reader, writer)

        assert _at_least(logged, logging.ERROR) == []

    @pytest.mark.anyio
    async def test_disconnect_before_a_request_arrives_is_not_an_error(
        self, tmp_path: Path, logged: _Collector
    ) -> None:
        """The peer can also vanish before it says anything."""
        daemon = _make_daemon(tmp_path)
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = AsyncMock(spec=asyncio.StreamWriter)
        reader.readline.side_effect = ConnectionResetError("peer went away")

        await daemon._handle_client(reader, writer)

        assert _at_least(logged, logging.ERROR) == []

    @pytest.mark.anyio
    async def test_the_connection_is_still_closed_cleanly(self, tmp_path: Path) -> None:
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams(drain_error=ConnectionResetError("peer went away"))

        with _returning(_ALLOW_RESPONSE):
            await daemon._handle_client(reader, writer)

        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    @pytest.mark.anyio
    async def test_no_error_response_is_written_to_a_socket_known_to_be_dead(
        self, tmp_path: Path
    ) -> None:
        """The second traceback came from reporting the failure down the same
        dead socket. There is nobody to tell."""
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams(drain_error=ConnectionResetError("peer went away"))

        with _returning(_ALLOW_RESPONSE):
            await daemon._handle_client(reader, writer)

        written = b"".join(call.args[0] for call in writer.write.call_args_list)
        assert b'"error"' not in written


class TestAnUndeliveredBlockDecisionIsWorthAWarning:
    @pytest.mark.anyio
    async def test_lost_blocking_response_warns(self, tmp_path: Path, logged: _Collector) -> None:
        """The information the generic handler threw away: nobody received the
        deny, so the tool call ran ungated."""
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams(drain_error=ConnectionResetError("peer went away"))

        with _returning(_DENY_RESPONSE):
            await daemon._handle_client(reader, writer)

        assert _exactly(
            logged, logging.WARNING
        ), "an undelivered blocking decision must not be logged at DEBUG"
        assert _at_least(logged, logging.ERROR) == []

    @pytest.mark.anyio
    async def test_lost_allow_response_does_not_warn(
        self, tmp_path: Path, logged: _Collector
    ) -> None:
        """An undelivered ALLOW gated nothing, so it is not worth a warning."""
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams(drain_error=ConnectionResetError("peer went away"))

        with _returning(_ALLOW_RESPONSE):
            await daemon._handle_client(reader, writer)

        assert _exactly(logged, logging.WARNING) == []


class TestGenuineFailuresStillFailLoudly:
    @pytest.mark.anyio
    async def test_a_real_exception_is_still_logged_at_error(
        self, tmp_path: Path, logged: _Collector
    ) -> None:
        """The narrow catch must not have widened into a general muffler."""
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams()

        with patch.object(HooksDaemon, "_process_request", side_effect=RuntimeError("boom")):
            await daemon._handle_client(reader, writer)

        assert any("boom" in record.getMessage() for record in _at_least(logged, logging.ERROR))

    @pytest.mark.anyio
    async def test_an_unrelated_oserror_is_still_an_error(
        self, tmp_path: Path, logged: _Collector
    ) -> None:
        """``OSError`` is the parent of both disconnect types. Catching the
        parent would swallow a genuinely broken socket, a full disk, or a
        permissions failure — so only the two subclasses are classified."""
        daemon = _make_daemon(tmp_path)
        reader, writer = _streams(drain_error=OSError("disk is on fire"))

        with _returning(_ALLOW_RESPONSE):
            await daemon._handle_client(reader, writer)

        assert _at_least(logged, logging.ERROR), "a non-disconnect OSError must not be demoted"
