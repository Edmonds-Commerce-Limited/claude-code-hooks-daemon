"""Tests for DaemonStatsHandler."""

from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import DaemonStatsHandler


class TestDaemonStatsHandler:
    """Tests for DaemonStatsHandler."""

    @pytest.fixture
    def handler(self) -> DaemonStatsHandler:
        """Create handler instance."""
        return DaemonStatsHandler()

    def test_handler_properties(self, handler: DaemonStatsHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-daemon-stats"
        assert handler.priority == 30
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "daemon" in handler.tags
        assert "health" in handler.tags

    def test_matches_always_returns_true(self, handler: DaemonStatsHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"some": "data"}) is True

    def test_handle_with_full_stats(self, handler: DaemonStatsHandler) -> None:
        """Test formatting with full daemon stats."""
        mock_stats = MagicMock()
        mock_stats.uptime_seconds = 125.5
        mock_stats.errors = 0

        mock_controller = MagicMock()
        mock_controller.get_stats.return_value = mock_stats

        mock_process = MagicMock()
        mock_memory_info = MagicMock()
        mock_memory_info.rss = 45 * 1024 * 1024  # 45 MB
        mock_process.memory_info.return_value = mock_memory_info

        mock_psutil = MagicMock()
        mock_psutil.Process = MagicMock(return_value=mock_process)

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.daemon_stats.get_controller",
                return_value=mock_controller,
            ),
            patch(
                "claude_code_hooks_daemon.handlers.status_line.daemon_stats.psutil",
                mock_psutil,
            ),
            patch("logging.getLogger") as mock_logger,
        ):
            mock_logger.return_value.level = 20  # INFO
            result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) >= 1
        # Check for uptime (should be in minutes)
        assert "2.1m" in result.context[0] or "125" in result.context[0]
        # Check for memory
        assert "45MB" in result.context[0] or "MB" in result.context[0]
        # Check for log level
        assert "INFO" in result.context[0]

    def test_handle_uptime_seconds(self, handler: DaemonStatsHandler) -> None:
        """Test uptime formatting in seconds (< 60s)."""
        mock_stats = MagicMock()
        mock_stats.uptime_seconds = 45.5
        mock_stats.errors = 0

        mock_controller = MagicMock()
        mock_controller.get_stats.return_value = mock_stats

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.daemon_stats.get_controller",
                return_value=mock_controller,
            ),
            patch("logging.getLogger") as mock_logger,
        ):
            mock_logger.return_value.level = 20
            result = handler.handle({})

        assert "45.5s" in result.context[0] or "45" in result.context[0]

    def test_handle_uptime_hours(self, handler: DaemonStatsHandler) -> None:
        """Test uptime formatting in hours (>= 3600s)."""
        mock_stats = MagicMock()
        mock_stats.uptime_seconds = 7200.0  # 2 hours
        mock_stats.errors = 0

        mock_controller = MagicMock()
        mock_controller.get_stats.return_value = mock_stats

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.daemon_stats.get_controller",
                return_value=mock_controller,
            ),
            patch("logging.getLogger") as mock_logger,
        ):
            mock_logger.return_value.level = 20
            result = handler.handle({})

        assert "2.0h" in result.context[0] or "2h" in result.context[0]

    def test_handle_with_errors(self, handler: DaemonStatsHandler) -> None:
        """Test formatting includes error count when errors > 0."""
        mock_stats = MagicMock()
        mock_stats.uptime_seconds = 60.0
        mock_stats.errors = 3

        mock_controller = MagicMock()
        mock_controller.get_stats.return_value = mock_stats

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.daemon_stats.get_controller",
                return_value=mock_controller,
            ),
            patch("logging.getLogger") as mock_logger,
        ):
            mock_logger.return_value.level = 20
            result = handler.handle({})

        assert len(result.context) == 2
        assert "❌ 3 err" in result.context[1]

    def test_handle_psutil_not_available(self, handler: DaemonStatsHandler) -> None:
        """Test graceful handling when psutil is not available."""
        mock_stats = MagicMock()
        mock_stats.uptime_seconds = 60.0
        mock_stats.errors = 0

        mock_controller = MagicMock()
        mock_controller.get_stats.return_value = mock_stats

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.daemon_stats.get_controller",
                return_value=mock_controller,
            ),
            patch("claude_code_hooks_daemon.handlers.status_line.daemon_stats.psutil", None),
            patch("logging.getLogger") as mock_logger,
        ):
            mock_logger.return_value.level = 20
            result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) >= 1
        # Should still have uptime and log level, just no memory
        assert "1.0m" in result.context[0] or "60" in result.context[0]

    def test_handle_controller_error_silent_fail(self, handler: DaemonStatsHandler) -> None:
        """Test silent failure when controller errors."""
        with patch(
            "claude_code_hooks_daemon.handlers.status_line.daemon_stats.get_controller",
            side_effect=Exception("Controller error"),
        ):
            result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_psutil_error_silent_fail(self, handler: DaemonStatsHandler) -> None:
        """Test continues when psutil.Process() fails."""
        mock_stats = MagicMock()
        mock_stats.uptime_seconds = 60.0
        mock_stats.errors = 0

        mock_controller = MagicMock()
        mock_controller.get_stats.return_value = mock_stats

        mock_psutil = MagicMock()
        mock_psutil.Process = MagicMock(side_effect=Exception("psutil error"))

        with (
            patch(
                "claude_code_hooks_daemon.handlers.status_line.daemon_stats.get_controller",
                return_value=mock_controller,
            ),
            patch(
                "claude_code_hooks_daemon.handlers.status_line.daemon_stats.psutil",
                mock_psutil,
            ),
            patch("logging.getLogger") as mock_logger,
        ):
            mock_logger.return_value.level = 20
            result = handler.handle({})

        # Should still return stats, just without memory
        assert result.decision == "allow"
        assert len(result.context) >= 1
