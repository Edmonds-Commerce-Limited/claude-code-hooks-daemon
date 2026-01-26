"""Tests for daemon server implementation.

Comprehensive test suite following TDD principles.
"""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.front_controller import FrontController
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.daemon.config import DaemonConfig
from claude_code_hooks_daemon.daemon.server import HooksDaemon


class SimpleTestHandler(Handler):
    """Simple test handler for testing daemon dispatch."""

    def __init__(self) -> None:
        """Initialise test handler."""
        super().__init__(name="test_handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        """Match all requests."""
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Return simple allow result."""
        return HookResult(decision="allow", context="Test handler executed")


class SlowTestHandler(Handler):
    """Slow handler for testing concurrent request handling."""

    def __init__(self, delay_ms: int = 100) -> None:
        """Initialise slow handler."""
        super().__init__(name="slow_test_handler", priority=50, terminal=True)
        self.delay_ms = delay_ms

    def matches(self, hook_input: dict) -> bool:
        """Match all requests."""
        return True

    def handle(self, hook_input: dict) -> HookResult:
        """Sleep then return result."""
        time.sleep(self.delay_ms / 1000.0)
        return HookResult(decision="allow", context=f"Delayed {self.delay_ms}ms")


class TestHooksDaemon:
    """Test suite for HooksDaemon server."""

    @pytest.fixture
    def temp_socket_path(self) -> Path:
        """Create temporary socket path."""
        with tempfile.NamedTemporaryFile(suffix=".sock", delete=False) as f:
            socket_path = Path(f.name)
        # Remove the file so daemon can create socket
        socket_path.unlink()
        yield socket_path
        # Cleanup
        if socket_path.exists():
            socket_path.unlink()

    @pytest.fixture
    def temp_pid_path(self) -> Path:
        """Create temporary PID file path."""
        with tempfile.NamedTemporaryFile(suffix=".pid", delete=False) as f:
            pid_path = Path(f.name)
        pid_path.unlink()
        yield pid_path
        # Cleanup
        if pid_path.exists():
            pid_path.unlink()

    @pytest.fixture
    def daemon_config(self, temp_socket_path: Path, temp_pid_path: Path) -> DaemonConfig:
        """Create daemon configuration for testing."""
        return DaemonConfig(
            socket_path=temp_socket_path,
            idle_timeout_seconds=2,  # Short timeout for testing
            pid_file_path=temp_pid_path,
            log_level="DEBUG",
        )

    @pytest.fixture
    def front_controller(self) -> FrontController:
        """Create front controller with test handler."""
        controller = FrontController(event_name="PreToolUse")
        controller.register(SimpleTestHandler())
        return controller

    @pytest.mark.anyio
    async def test_daemon_starts_and_accepts_connections(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon starts and accepts socket connections."""
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)

        # Start daemon in background
        server_task = asyncio.create_task(daemon.start())

        # Wait for server to be ready
        await asyncio.sleep(0.1)

        # Connect and send request
        reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))

        request = {
            "event": "PreToolUse",
            "hook_input": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            "request_id": "test-001",
        }

        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()

        # Read response
        response_data = await reader.readline()
        response = json.loads(response_data.decode())

        # Verify response structure
        assert response["request_id"] == "test-001"
        assert "result" in response
        assert "timing_ms" in response
        assert response["timing_ms"] >= 0

        # Cleanup
        writer.close()
        await writer.wait_closed()
        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_daemon_writes_pid_file_on_start(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon writes PID file on startup."""
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)

        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        # Check PID file exists and contains valid PID
        assert daemon_config.pid_file_path.exists()
        pid_content = daemon_config.pid_file_path.read_text().strip()
        pid = int(pid_content)
        assert pid == os.getpid()

        # Cleanup
        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_daemon_removes_pid_file_on_shutdown(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon removes PID file on graceful shutdown."""
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)

        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        assert daemon_config.pid_file_path.exists()

        # Shutdown
        await daemon.shutdown()
        await server_task

        # PID file should be removed
        assert not daemon_config.pid_file_path.exists()

    @pytest.mark.anyio
    async def test_daemon_handles_stale_pid_file(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon handles stale PID file (process died without cleanup)."""
        # Create stale PID file with non-existent PID
        daemon_config.pid_file_path.write_text("99999")

        daemon = HooksDaemon(config=daemon_config, controller=front_controller)

        # Should start successfully and overwrite stale PID
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        assert daemon_config.pid_file_path.exists()
        pid = int(daemon_config.pid_file_path.read_text().strip())
        assert pid == os.getpid()

        # Cleanup
        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_daemon_idle_timeout_shutdown(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon shuts down after idle timeout."""
        # Use very short timeout and check interval for testing
        daemon_config.idle_timeout_seconds = 1

        # Use short check interval (1 second) for testing
        daemon = HooksDaemon(
            config=daemon_config, controller=front_controller, idle_check_interval=1
        )

        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        # Wait for idle timeout to trigger (1s timeout + 1s check + buffer)
        await asyncio.sleep(2.5)

        # Daemon should have shut down
        assert server_task.done()
        assert not daemon_config.socket_path.exists()

    @pytest.mark.anyio
    async def test_daemon_resets_idle_timer_on_request(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon resets idle timer when handling requests."""
        daemon_config.idle_timeout_seconds = 2

        daemon = HooksDaemon(config=daemon_config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        # Send request after 1 second (before timeout)
        await asyncio.sleep(1)

        reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))
        request = {
            "event": "PreToolUse",
            "hook_input": {"tool_name": "Bash"},
            "request_id": "test-002",
        }
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()
        await reader.readline()  # Read response
        writer.close()
        await writer.wait_closed()

        # Wait another second (total 2s from start, but only 1s since request)
        await asyncio.sleep(1)

        # Daemon should still be running (timer was reset)
        assert not server_task.done()

        # Cleanup
        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_daemon_handles_concurrent_requests(self, daemon_config: DaemonConfig) -> None:
        """Test that daemon handles multiple concurrent requests correctly."""
        # Use slow handler to verify concurrent execution
        controller = FrontController(event_name="PreToolUse")
        controller.register(SlowTestHandler(delay_ms=100))

        daemon = HooksDaemon(config=daemon_config, controller=controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        # Send 3 concurrent requests
        async def send_request(request_id: str) -> dict[str, Any]:
            reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))
            request = {
                "event": "PreToolUse",
                "hook_input": {"tool_name": "Bash"},
                "request_id": request_id,
            }
            writer.write((json.dumps(request) + "\n").encode())
            await writer.drain()

            response_data = await reader.readline()
            response = json.loads(response_data.decode())

            writer.close()
            await writer.wait_closed()
            return response

        start_time = time.time()
        responses = await asyncio.gather(
            send_request("req-1"), send_request("req-2"), send_request("req-3")
        )
        elapsed_time = time.time() - start_time

        # All requests should complete
        assert len(responses) == 3
        assert all(r["request_id"] in ["req-1", "req-2", "req-3"] for r in responses)

        # Should take ~100ms (concurrent) not ~300ms (sequential)
        # Allow some margin for processing overhead
        assert elapsed_time < 0.25

        # Cleanup
        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_daemon_graceful_shutdown_completes_inflight_requests(
        self, daemon_config: DaemonConfig
    ) -> None:
        """Test that graceful shutdown waits for in-flight requests."""
        controller = FrontController(event_name="PreToolUse")
        controller.register(SlowTestHandler(delay_ms=200))

        daemon = HooksDaemon(config=daemon_config, controller=controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        # Start a slow request
        async def send_slow_request() -> dict[str, Any]:
            reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))
            request = {
                "event": "PreToolUse",
                "hook_input": {"tool_name": "Bash"},
                "request_id": "slow-req",
            }
            writer.write((json.dumps(request) + "\n").encode())
            await writer.drain()

            response_data = await reader.readline()
            response = json.loads(response_data.decode())

            writer.close()
            await writer.wait_closed()
            return response

        request_task = asyncio.create_task(send_slow_request())

        # Wait a bit then trigger shutdown
        await asyncio.sleep(0.05)
        shutdown_task = asyncio.create_task(daemon.shutdown())

        # Request should complete successfully
        response = await request_task
        assert response["request_id"] == "slow-req"
        assert "result" in response

        await shutdown_task
        await server_task

    @pytest.mark.anyio
    async def test_daemon_handles_malformed_json_request(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon handles malformed JSON gracefully."""
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))

        # Send malformed JSON
        writer.write(b"{invalid json\n")
        await writer.drain()

        # Should receive error response
        response_data = await reader.readline()
        response = json.loads(response_data.decode())

        assert "error" in response
        assert "request_id" not in response  # Can't extract from malformed request

        writer.close()
        await writer.wait_closed()
        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_daemon_includes_timing_metrics_in_response(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon includes timing metrics in response."""
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))

        request = {
            "event": "PreToolUse",
            "hook_input": {"tool_name": "Bash"},
            "request_id": "timing-test",
        }

        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()

        response_data = await reader.readline()
        response = json.loads(response_data.decode())

        # Verify timing metrics
        assert "timing_ms" in response
        assert isinstance(response["timing_ms"], (int, float))
        assert response["timing_ms"] >= 0
        assert response["timing_ms"] < 1000  # Should be fast

        writer.close()
        await writer.wait_closed()
        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_daemon_cleans_up_socket_on_shutdown(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon removes socket file on shutdown."""
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        assert daemon_config.socket_path.exists()

        await daemon.shutdown()
        await server_task

        # Socket should be removed
        assert not daemon_config.socket_path.exists()

    @pytest.mark.anyio
    async def test_daemon_handles_missing_event_field(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon handles request missing event field."""
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))

        # Request missing 'event' field
        request = {"hook_input": {"tool_name": "Bash"}, "request_id": "missing-event"}

        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()

        response_data = await reader.readline()
        response = json.loads(response_data.decode())

        assert "error" in response
        assert response["request_id"] == "missing-event"

        writer.close()
        await writer.wait_closed()
        await daemon.shutdown()
        await server_task

    @pytest.mark.anyio
    async def test_daemon_handles_missing_hook_input_field(
        self, daemon_config: DaemonConfig, front_controller: FrontController
    ) -> None:
        """Test that daemon handles request missing hook_input field."""
        daemon = HooksDaemon(config=daemon_config, controller=front_controller)
        server_task = asyncio.create_task(daemon.start())
        await asyncio.sleep(0.1)

        reader, writer = await asyncio.open_unix_connection(str(daemon_config.socket_path))

        # Request missing 'hook_input' field
        request = {"event": "PreToolUse", "request_id": "missing-input"}

        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()

        response_data = await reader.readline()
        response = json.loads(response_data.decode())

        assert "error" in response
        assert response["request_id"] == "missing-input"

        writer.close()
        await writer.wait_closed()
        await daemon.shutdown()
        await server_task
