"""Tests for server.py coverage gaps.

Targets uncovered lines: 236, 257-259, 358-360, 464-468, 531-539, 547, 559,
584-593, 596-600, 624.
"""

import asyncio
import json
import os
import signal
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from claude_code_hooks_daemon.config.models import DaemonConfig
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.daemon.server import (
    HooksDaemon,
)


def _make_config(
    socket_path: Path | None = None,
    pid_file_path: Path | None = None,
) -> DaemonConfig:
    """Create a minimal DaemonConfig for testing."""
    if socket_path is None:
        socket_path = Path(tempfile.mktemp(suffix=".sock"))
    return DaemonConfig(
        socket_path=socket_path,
        pid_file_path=pid_file_path,
        idle_timeout_seconds=600,
        log_level="DEBUG",
    )


class FakeController:
    """Controller implementing the new Controller protocol."""

    def process_request(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Process request and return response."""
        return {"result": {"decision": "allow"}}

    def get_health(self) -> dict[str, Any]:
        """Return health status."""
        return {"status": "healthy", "handlers": {}}

    def get_handlers(self) -> dict[str, list[dict[str, Any]]]:
        """Return registered handlers."""
        return {"PreToolUse": [{"name": "test", "priority": 50}]}


class FakeLegacyController:
    """Controller implementing the legacy protocol."""

    def dispatch(self, hook_input: dict[str, Any]) -> HookResult:
        """Dispatch to handlers."""
        return HookResult(decision="allow", context="legacy")


class NotAController:
    """Object that matches neither protocol."""

    pass


class TestStrictValidationEnvVar:
    """Tests for _is_strict_validation with env var returning False."""

    def test_strict_validation_false_env_var(self) -> None:
        """Line 236: env var 'false' returns False."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeController())

        for val in ("false", "0", "no"):
            with patch.dict(os.environ, {"HOOKS_DAEMON_VALIDATION_STRICT": val}):
                assert daemon._is_strict_validation() is False


class TestGetInputValidatorImportError:
    """Tests for _get_input_validator when jsonschema is missing."""

    def test_import_error_returns_none(self) -> None:
        """Lines 257-259: ImportError when jsonschema not installed."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeController())
        daemon._input_validators.clear()

        with (
            patch(
                "claude_code_hooks_daemon.daemon.server.get_input_schema",
                return_value={"type": "object"},
            ),
            patch.dict("sys.modules", {"jsonschema": None}),
        ):
            result = daemon._get_input_validator("PreToolUse")

        assert result is None


class TestSignalHandler:
    """Tests for _signal_handler creating shutdown task."""

    @pytest.mark.anyio
    async def test_signal_handler_creates_shutdown_task(self) -> None:
        """Lines 358-360: signal handler creates asyncio task for shutdown."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeController())
        daemon._shutdown_requested = False

        # Patch shutdown on the class to avoid __slots__ issue
        original_shutdown = HooksDaemon.shutdown

        async def mock_shutdown(self_arg: Any) -> None:
            self_arg._shutdown_requested = True

        HooksDaemon.shutdown = mock_shutdown  # type: ignore[assignment]
        try:
            daemon._signal_handler(signal.SIGTERM)
            assert daemon._shutdown_task is not None
            await daemon._shutdown_task
            assert daemon._shutdown_requested is True
        finally:
            HooksDaemon.shutdown = original_shutdown  # type: ignore[assignment]


class TestHandleClientException:
    """Tests for _handle_client exception path."""

    @pytest.mark.anyio
    async def test_handle_client_exception_sends_error(self) -> None:
        """Lines 464-468: exception during processing sends error response."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeController())

        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = AsyncMock(spec=asyncio.StreamWriter)

        # readline returns valid data, but _process_request raises
        reader.readline.return_value = b'{"event":"PreToolUse","hook_input":{}}\n'

        with patch.object(HooksDaemon, "_process_request", side_effect=RuntimeError("boom")):
            await daemon._handle_client(reader, writer)

        # Verify error response was written
        written = writer.write.call_args[0][0]
        resp = json.loads(written.decode().strip())
        assert "error" in resp
        assert "boom" in resp["error"]
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()


class TestProcessRequestNewController:
    """Tests for _process_request with new Controller protocol."""

    @pytest.mark.anyio
    async def test_new_controller_process_request(self) -> None:
        """Lines 531-539, 547: new Controller dispatches via process_request."""
        config = _make_config()
        controller = FakeController()
        daemon = HooksDaemon(config=config, controller=controller)

        request = json.dumps(
            {
                "event": "PreToolUse",
                "hook_input": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                "request_id": "req-123",
            }
        )

        result = await daemon._process_request(request)

        assert result.get("request_id") == "req-123"
        assert "result" in result

    @pytest.mark.anyio
    async def test_new_controller_without_request_id(self) -> None:
        """Line 547 branch: no request_id means it is not added."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeController())

        request = json.dumps(
            {
                "event": "PreToolUse",
                "hook_input": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            }
        )

        result = await daemon._process_request(request)
        assert "request_id" not in result


class TestProcessRequestUnknownController:
    """Tests for _process_request with unknown controller type."""

    @pytest.mark.anyio
    async def test_unknown_controller_returns_error(self) -> None:
        """Line 559: neither Controller nor LegacyController."""
        config = _make_config()
        not_controller = NotAController()
        daemon = HooksDaemon(config=config, controller=not_controller)  # type: ignore[arg-type]
        # Force flags so neither branch matches
        daemon._is_new_controller = False

        request = json.dumps(
            {
                "event": "PreToolUse",
                "hook_input": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            }
        )

        result = await daemon._process_request(request)
        assert result == {"error": "Unknown controller type"}


class TestHandleSystemRequestLegacy:
    """Tests for _handle_system_request with legacy controller paths."""

    def test_health_with_legacy_controller(self) -> None:
        """Lines 584-593: health action with legacy controller returns default."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeLegacyController())

        result = daemon._handle_system_request({"action": "health"}, None)

        assert result["result"]["status"] == "healthy"
        assert result["result"]["initialised"] is True

    def test_handlers_with_legacy_controller(self) -> None:
        """Lines 596-600: handlers action with legacy controller returns empty."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeLegacyController())

        result = daemon._handle_system_request({"action": "handlers"}, None)

        assert result["result"]["handlers"] == {}

    def test_health_with_new_controller(self) -> None:
        """Lines 584-585: health action with new controller calls get_health."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeController())

        result = daemon._handle_system_request({"action": "health"}, "req-1")

        assert result["result"]["status"] == "healthy"
        assert result["request_id"] == "req-1"

    def test_handlers_with_new_controller(self) -> None:
        """Lines 596-597: handlers action with new controller calls get_handlers."""
        config = _make_config()
        daemon = HooksDaemon(config=config, controller=FakeController())

        result = daemon._handle_system_request({"action": "handlers"}, None)

        assert "PreToolUse" in result["result"]["handlers"]


class TestWritePidFileNoPidPath:
    """Tests for _write_pid_file when pid_file_path is None."""

    def test_write_pid_file_no_path_returns_early(self) -> None:
        """Line 624: early return when no pid_file_path configured."""
        config = _make_config(pid_file_path=None)
        daemon = HooksDaemon(config=config, controller=FakeController())

        # Should not raise - just returns early
        daemon._write_pid_file()
