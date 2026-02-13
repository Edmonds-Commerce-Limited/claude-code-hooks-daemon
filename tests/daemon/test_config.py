"""Tests for daemon configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import LogLevel
from claude_code_hooks_daemon.daemon.config import DaemonConfig


class TestDaemonConfig:
    """Test suite for DaemonConfig (Pydantic version)."""

    def test_creates_with_required_fields(self) -> None:
        """Test DaemonConfig creation with required fields."""
        config = DaemonConfig(socket_path=Path("/tmp/test.sock"))

        # Pydantic stores paths as strings
        assert config.socket_path == "/tmp/test.sock"
        assert config.socket_path_obj == Path("/tmp/test.sock")
        assert config.idle_timeout_seconds == 600  # Default
        assert config.pid_file_path is None  # Default
        assert config.log_level == LogLevel.INFO  # Default

    def test_creates_with_all_fields(self) -> None:
        """Test DaemonConfig creation with all fields specified."""
        config = DaemonConfig(
            socket_path=Path("/tmp/test.sock"),
            idle_timeout_seconds=300,
            pid_file_path=Path("/tmp/test.pid"),
            log_level="DEBUG",
        )

        # Pydantic stores paths as strings
        assert config.socket_path == "/tmp/test.sock"
        assert config.socket_path_obj == Path("/tmp/test.sock")
        assert config.idle_timeout_seconds == 300
        assert config.pid_file_path == "/tmp/test.pid"
        assert config.pid_file_path_obj == Path("/tmp/test.pid")
        assert config.log_level == LogLevel.DEBUG

    def test_converts_string_paths_to_strings(self) -> None:
        """Test that Path objects are converted to strings for storage."""
        config = DaemonConfig(
            socket_path="/tmp/test.sock",
            pid_file_path="/tmp/test.pid",
        )

        # Pydantic stores as strings
        assert isinstance(config.socket_path, str)
        assert isinstance(config.pid_file_path, str)
        assert config.socket_path == "/tmp/test.sock"
        assert config.pid_file_path == "/tmp/test.pid"

        # But properties return Path objects
        assert isinstance(config.socket_path_obj, Path)
        assert isinstance(config.pid_file_path_obj, Path)

    def test_rejects_negative_timeout(self) -> None:
        """Test that negative timeout is rejected."""
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            DaemonConfig(socket_path=Path("/tmp/test.sock"), idle_timeout_seconds=-1)

    def test_rejects_zero_timeout(self) -> None:
        """Test that zero timeout is rejected."""
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            DaemonConfig(socket_path=Path("/tmp/test.sock"), idle_timeout_seconds=0)

    def test_rejects_invalid_log_level(self) -> None:
        """Test that invalid log levels are rejected."""
        with pytest.raises(ValidationError, match="Input should be"):
            DaemonConfig(socket_path=Path("/tmp/test.sock"), log_level="INVALID")

    def test_accepts_valid_log_levels(self) -> None:
        """Test that all valid log levels are accepted."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = DaemonConfig(socket_path=Path("/tmp/test.sock"), log_level=level)
            assert config.log_level == LogLevel(level)

    def test_enforce_single_daemon_process_defaults_to_false(self) -> None:
        """Test that enforce_single_daemon_process defaults to False."""
        config = DaemonConfig(socket_path=Path("/tmp/test.sock"))
        assert config.enforce_single_daemon_process is False

    def test_enforce_single_daemon_process_can_be_enabled(self) -> None:
        """Test that enforce_single_daemon_process can be set to True."""
        config = DaemonConfig(
            socket_path=Path("/tmp/test.sock"), enforce_single_daemon_process=True
        )
        assert config.enforce_single_daemon_process is True

    def test_enforce_single_daemon_process_rejects_non_bool(self) -> None:
        """Test that enforce_single_daemon_process rejects truly invalid values."""
        with pytest.raises(ValidationError, match="Input should be a valid boolean"):
            DaemonConfig(
                socket_path=Path("/tmp/test.sock"),
                enforce_single_daemon_process={"invalid": "dict"},
            )
