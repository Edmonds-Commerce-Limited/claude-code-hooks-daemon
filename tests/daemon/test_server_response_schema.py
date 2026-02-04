"""Test that server responses comply with Claude Code schema.

CRITICAL: This tests the ACTUAL server output, not just handler output.
The server may add fields after handler processing, so we must validate
the complete response that gets sent to Claude Code.
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.daemon.config import DaemonConfig
from claude_code_hooks_daemon.daemon.server import HooksDaemon


class TestServerHandler(Handler):
    """Simple handler for testing server responses."""

    def __init__(self) -> None:
        # Test-only handler, use literal values (not in production constants)
        super().__init__(name="test-server-handler", priority=5, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        return True

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult.allow(context=["Test context"])

    def get_acceptance_tests(self) -> list:
        """Stub implementation for test handler."""
        return []


@pytest.mark.anyio
class TestServerResponseSchema:
    """Test that server responses comply with Claude Code schemas."""

    @pytest.fixture
    def temp_socket_path(self) -> Path:
        """Create temporary socket path."""
        with tempfile.NamedTemporaryFile(suffix=".sock", delete=False) as f:
            socket_path = Path(f.name)
        socket_path.unlink()
        yield socket_path
        if socket_path.exists():
            socket_path.unlink()

    @pytest.fixture
    def temp_pid_path(self) -> Path:
        """Create temporary PID file path."""
        with tempfile.NamedTemporaryFile(suffix=".pid", delete=False) as f:
            pid_path = Path(f.name)
        pid_path.unlink()
        yield pid_path
        if pid_path.exists():
            pid_path.unlink()

    @pytest.fixture
    def daemon_config(self, temp_socket_path: Path, temp_pid_path: Path) -> DaemonConfig:
        """Create daemon configuration for testing."""
        return DaemonConfig(
            socket_path=temp_socket_path,
            idle_timeout_seconds=2,
            pid_file_path=temp_pid_path,
            log_level="DEBUG",
        )

    @pytest.fixture
    def front_controller(self) -> FrontController:
        """Create front controller with test handler."""
        controller = FrontController("PreToolUse")
        controller.register(TestServerHandler())
        return controller

    async def test_server_response_complies_with_claude_code_schema(
        self, daemon_config: DaemonConfig, front_controller: FrontController, response_validator
    ) -> None:
        """Test that server responses pass Claude Code schema validation.

        CRITICAL: This is a regression test for the timing_ms bug.
        Claude Code schema does NOT accept timing_ms as a top-level field.
        """
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))

        request = {
            "event": "PreToolUse",
            "hook_input": {"tool_name": "Bash", "tool_input": {"command": "echo test"}},
            "request_id": "schema-test",
        }

        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()

        response_data = await reader.readline()
        response = json.loads(response_data.decode())

        # Remove request_id for schema validation (it's not part of hook schema)
        response_without_request_id = {k: v for k, v in response.items() if k != "request_id"}

        # CRITICAL: Validate ACTUAL server response against Claude Code schema
        # This should catch any fields the server adds that Claude Code doesn't accept
        response_validator.assert_valid("PreToolUse", response_without_request_id)

        writer.close()
        await writer.wait_closed()
        await daemon.shutdown()
        await server_task

    async def test_precompact_server_response_schema(
        self, daemon_config: DaemonConfig, response_validator
    ) -> None:
        """Test PreCompact responses comply with Claude Code schema.

        This was the original failing case that triggered this bug discovery.
        """
        # Create PreCompact front controller
        controller = FrontController("PreCompact")
        controller.register(TestServerHandler())

        daemon = HooksDaemon(config=daemon_config, controller=controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))

        request = {
            "event": "PreCompact",
            "hook_input": {"hook_event_name": "PreCompact", "trigger": "manual"},
            "request_id": "precompact-test",
        }

        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()

        response_data = await reader.readline()
        response = json.loads(response_data.decode())

        # Remove request_id for schema validation
        response_without_request_id = {k: v for k, v in response.items() if k != "request_id"}

        # Validate against Claude Code PreCompact schema
        response_validator.assert_valid("PreCompact", response_without_request_id)

        writer.close()
        await writer.wait_closed()
        await daemon.shutdown()
        await server_task
