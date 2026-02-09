"""Tests for ApiUsageSevenDayHandler."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.status_line.api_usage_seven_day import (
    ApiUsageSevenDayHandler,
)


class TestApiUsageSevenDayHandler:
    """Test 7-day API usage status line handler."""

    @pytest.fixture
    def handler(self) -> ApiUsageSevenDayHandler:
        """Create handler instance."""
        return ApiUsageSevenDayHandler()

    def test_init_name(self, handler: ApiUsageSevenDayHandler) -> None:
        assert handler.name == "status-api-usage-7d"

    def test_init_priority(self, handler: ApiUsageSevenDayHandler) -> None:
        assert handler.priority == 17

    def test_init_terminal_false(self, handler: ApiUsageSevenDayHandler) -> None:
        assert handler.terminal is False

    def test_matches_always_true(self, handler: ApiUsageSevenDayHandler) -> None:
        assert handler.matches({}) is True

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_with_cached_data(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageSevenDayHandler,
    ) -> None:
        """Should display 7-day usage from cached data."""
        cached_data: dict[str, Any] = {
            "seven_day": {
                "utilization": 50.0,
                "resets_at": "2026-02-15T00:00:00Z",
            }
        }
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = cached_data

        result = handler.handle({})
        assert result.context is not None
        assert len(result.context) > 0
        context_str = result.context[0]
        assert "50%" in context_str

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_returns_empty_on_no_data(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageSevenDayHandler,
    ) -> None:
        """Should return empty context when no data available."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = None
        mock_cache.read.return_value = None
        mock_client = mock_client_cls.return_value
        mock_client.get_usage.return_value = None

        result = handler.handle({})
        assert result.context == []

    def test_get_acceptance_tests(self, handler: ApiUsageSevenDayHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
