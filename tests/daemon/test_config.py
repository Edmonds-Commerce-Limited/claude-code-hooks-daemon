"""Tests for daemon configuration."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.config import DaemonConfig


class TestDaemonConfig:
    """Test suite for DaemonConfig."""

    def test_creates_with_required_fields(self) -> None:
        """Test DaemonConfig creation with required fields."""
        config = DaemonConfig(socket_path=Path("/tmp/test.sock"))

        assert config.socket_path == Path("/tmp/test.sock")
        assert config.idle_timeout_seconds == 600  # Default
        assert config.pid_file_path is None  # Default
        assert config.log_level == "INFO"  # Default

    def test_creates_with_all_fields(self) -> None:
        """Test DaemonConfig creation with all fields specified."""
        config = DaemonConfig(
            socket_path=Path("/tmp/test.sock"),
            idle_timeout_seconds=300,
            pid_file_path=Path("/tmp/test.pid"),
            log_level="DEBUG",
        )

        assert config.socket_path == Path("/tmp/test.sock")
        assert config.idle_timeout_seconds == 300
        assert config.pid_file_path == Path("/tmp/test.pid")
        assert config.log_level == "DEBUG"

    def test_converts_string_paths_to_path_objects(self) -> None:
        """Test that string paths are converted to Path objects."""
        config = DaemonConfig(
            socket_path="/tmp/test.sock",  # type: ignore
            pid_file_path="/tmp/test.pid",  # type: ignore
        )

        assert isinstance(config.socket_path, Path)
        assert isinstance(config.pid_file_path, Path)
        assert config.socket_path == Path("/tmp/test.sock")
        assert config.pid_file_path == Path("/tmp/test.pid")

    def test_rejects_negative_timeout(self) -> None:
        """Test that negative timeout is rejected."""
        with pytest.raises(ValueError, match="idle_timeout_seconds must be positive"):
            DaemonConfig(socket_path=Path("/tmp/test.sock"), idle_timeout_seconds=-1)

    def test_rejects_zero_timeout(self) -> None:
        """Test that zero timeout is rejected."""
        with pytest.raises(ValueError, match="idle_timeout_seconds must be positive"):
            DaemonConfig(socket_path=Path("/tmp/test.sock"), idle_timeout_seconds=0)

    def test_rejects_invalid_log_level(self) -> None:
        """Test that invalid log levels are rejected."""
        with pytest.raises(ValueError, match="Invalid log_level"):
            DaemonConfig(socket_path=Path("/tmp/test.sock"), log_level="INVALID")

    def test_accepts_valid_log_levels(self) -> None:
        """Test that all valid log levels are accepted."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = DaemonConfig(socket_path=Path("/tmp/test.sock"), log_level=level)
            assert config.log_level == level
