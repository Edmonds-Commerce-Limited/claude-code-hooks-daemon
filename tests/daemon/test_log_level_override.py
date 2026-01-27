"""Tests for HOOKS_DAEMON_LOG_LEVEL environment variable override.

Comprehensive test suite following TDD principles.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

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

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match all requests."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return simple allow result."""
        return HookResult(decision="allow", context="Test handler executed")


class TestLogLevelEnvironmentOverride:
    """Test suite for HOOKS_DAEMON_LOG_LEVEL environment variable override."""

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
            idle_timeout_seconds=2,
            pid_file_path=temp_pid_path,
            log_level="INFO",  # Default config value
        )

    @pytest.fixture
    def front_controller(self) -> FrontController:
        """Create front controller with test handler."""
        controller = FrontController(event_name="PreToolUse")
        controller.register(SimpleTestHandler())
        return controller

    @pytest.mark.anyio
    async def test_env_var_overrides_config_log_level(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test that HOOKS_DAEMON_LOG_LEVEL env var overrides config log_level."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "DEBUG"}):
            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            # Start daemon to trigger logging setup
            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            # Check that root logger level is DEBUG (not INFO from config)
            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

            # Cleanup
            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_config_log_level_used_when_env_var_not_set(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test that config log_level is used when env var not set."""
        # Ensure env var is not set
        with patch.dict(os.environ, {}, clear=False):
            if "HOOKS_DAEMON_LOG_LEVEL" in os.environ:
                del os.environ["HOOKS_DAEMON_LOG_LEVEL"]

            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            # Start daemon to trigger logging setup
            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            # Check that root logger level is INFO (from config)
            root_logger = logging.getLogger()
            assert root_logger.level == logging.INFO

            # Cleanup
            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_env_var_debug_overrides_warning_config(
        self,
        temp_socket_path: Path,
        temp_pid_path: Path,
        front_controller: FrontController,
    ) -> None:
        """Test env var DEBUG overrides WARNING config."""
        config = DaemonConfig(
            socket_path=temp_socket_path,
            idle_timeout_seconds=2,
            pid_file_path=temp_pid_path,
            log_level="WARNING",  # Higher level in config
        )

        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "DEBUG"}):
            daemon = HooksDaemon(config=config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            # Env var should override config
            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_env_var_error_overrides_debug_config(
        self,
        temp_socket_path: Path,
        temp_pid_path: Path,
        front_controller: FrontController,
    ) -> None:
        """Test env var ERROR overrides DEBUG config."""
        config = DaemonConfig(
            socket_path=temp_socket_path,
            idle_timeout_seconds=2,
            pid_file_path=temp_pid_path,
            log_level="DEBUG",  # Lower level in config
        )

        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "ERROR"}):
            daemon = HooksDaemon(config=config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            # Env var should override config
            root_logger = logging.getLogger()
            assert root_logger.level == logging.ERROR

            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_env_var_critical_level(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test env var supports CRITICAL log level."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "CRITICAL"}):
            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            root_logger = logging.getLogger()
            assert root_logger.level == logging.CRITICAL

            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_env_var_case_insensitive(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test that env var is case-insensitive (lowercase works)."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "debug"}):
            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            root_logger = logging.getLogger()
            # Should be converted to uppercase DEBUG
            assert root_logger.level == logging.DEBUG

            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_env_var_mixed_case(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test that env var handles mixed case (WaRnInG)."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "WaRnInG"}):
            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            root_logger = logging.getLogger()
            # Should be normalized to WARNING
            assert root_logger.level == logging.WARNING

            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_invalid_env_var_falls_back_to_config(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test that invalid env var value falls back to config."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "INVALID_LEVEL"}):
            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            # Should fall back to config value (INFO)
            root_logger = logging.getLogger()
            assert root_logger.level == logging.INFO

            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_empty_env_var_uses_config(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test that empty env var uses config value."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": ""}):
            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            # Should use config value (INFO)
            root_logger = logging.getLogger()
            assert root_logger.level == logging.INFO

            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_whitespace_env_var_uses_config(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test that whitespace-only env var uses config value."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "   "}):
            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            # Should use config value (INFO)
            root_logger = logging.getLogger()
            assert root_logger.level == logging.INFO

            await daemon.shutdown()
            await server_task

    @pytest.mark.anyio
    async def test_env_var_with_surrounding_whitespace(
        self,
        daemon_config: DaemonConfig,
        front_controller: FrontController,
    ) -> None:
        """Test that env var with surrounding whitespace is trimmed."""
        with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": "  DEBUG  "}):
            daemon = HooksDaemon(config=daemon_config, controller=front_controller)

            server_task = asyncio.create_task(daemon.start())
            await asyncio.sleep(0.1)

            # Should trim and use DEBUG
            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

            await daemon.shutdown()
            await server_task

    def test_all_valid_log_levels_accepted(
        self,
        temp_socket_path: Path,
        temp_pid_path: Path,
        front_controller: FrontController,
    ) -> None:
        """Test that all valid log levels are accepted by env var."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        for level_str in valid_levels:
            config = DaemonConfig(
                socket_path=temp_socket_path,
                idle_timeout_seconds=2,
                pid_file_path=temp_pid_path,
                log_level="INFO",
            )

            with patch.dict(os.environ, {"HOOKS_DAEMON_LOG_LEVEL": level_str}):
                daemon = HooksDaemon(config=config, controller=front_controller)

                # Just verify initialization doesn't raise
                expected_level = getattr(logging, level_str)
                root_logger = logging.getLogger()
                assert root_logger.level == expected_level
