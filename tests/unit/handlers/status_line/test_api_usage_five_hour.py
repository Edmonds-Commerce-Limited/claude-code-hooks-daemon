"""Tests for ApiUsageFiveHourHandler."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.status_line.api_usage_five_hour import (
    ApiUsageFiveHourHandler,
)


class TestApiUsageFiveHourHandler:
    """Test 5-hour API usage status line handler."""

    @pytest.fixture
    def handler(self) -> ApiUsageFiveHourHandler:
        """Create handler instance."""
        return ApiUsageFiveHourHandler()

    def test_init_name(self, handler: ApiUsageFiveHourHandler) -> None:
        """Handler name should match constant."""
        assert handler.name == "status-api-usage-5h"

    def test_init_priority(self, handler: ApiUsageFiveHourHandler) -> None:
        """Handler priority should be 16."""
        assert handler.priority == 16

    def test_init_terminal_false(self, handler: ApiUsageFiveHourHandler) -> None:
        """Handler should be non-terminal."""
        assert handler.terminal is False

    def test_matches_always_true(self, handler: ApiUsageFiveHourHandler) -> None:
        """Should always match for status events."""
        assert handler.matches({}) is True

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_with_fresh_cache(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageFiveHourHandler,
    ) -> None:
        """Should use cached data when available."""
        cached_data: dict[str, Any] = {
            "five_hour": {
                "utilization": 30.0,
                "resets_at": "2026-02-09T20:00:00Z",
            }
        }
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = cached_data

        result = handler.handle({})
        assert result.context is not None
        assert len(result.context) > 0
        context_str = result.context[0]
        assert "30%" in context_str

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_fetches_when_cache_stale(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageFiveHourHandler,
    ) -> None:
        """Should fetch from API when cache is stale."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = None

        api_data: dict[str, Any] = {
            "five_hour": {
                "utilization": 45.0,
                "resets_at": "2026-02-09T22:00:00Z",
            }
        }
        mock_client = mock_client_cls.return_value
        mock_client.get_usage.return_value = api_data

        result = handler.handle({})
        assert result.context is not None
        assert len(result.context) > 0
        context_str = result.context[0]
        assert "45%" in context_str
        # Should write to cache
        mock_cache.write.assert_called_once()

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_returns_empty_on_no_data(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageFiveHourHandler,
    ) -> None:
        """Should return empty context when no data available."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = None
        mock_cache.read.return_value = None

        mock_client = mock_client_cls.return_value
        mock_client.get_usage.return_value = None

        result = handler.handle({})
        assert result.context == []

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_contains_progress_bar(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageFiveHourHandler,
    ) -> None:
        """Output should contain progress bar characters."""
        cached_data: dict[str, Any] = {
            "five_hour": {
                "utilization": 50.0,
                "resets_at": "2026-02-09T20:00:00Z",
            }
        }
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = cached_data

        result = handler.handle({})
        context_str = result.context[0]
        # Should contain filled and/or empty circles
        assert "\u25cf" in context_str or "\u25cb" in context_str

    def test_get_acceptance_tests(self, handler: ApiUsageFiveHourHandler) -> None:
        """Should return acceptance tests."""
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
