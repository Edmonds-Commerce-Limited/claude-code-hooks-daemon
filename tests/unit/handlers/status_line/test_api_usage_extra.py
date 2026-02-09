"""Tests for ApiUsageExtraHandler."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.status_line.api_usage_extra import (
    ApiUsageExtraHandler,
)


class TestApiUsageExtraHandler:
    """Test extra usage credits status line handler."""

    @pytest.fixture
    def handler(self) -> ApiUsageExtraHandler:
        """Create handler instance."""
        return ApiUsageExtraHandler()

    def test_init_name(self, handler: ApiUsageExtraHandler) -> None:
        assert handler.name == "status-api-usage-extra"

    def test_init_priority(self, handler: ApiUsageExtraHandler) -> None:
        assert handler.priority == 18

    def test_init_terminal_false(self, handler: ApiUsageExtraHandler) -> None:
        assert handler.terminal is False

    def test_matches_always_true(self, handler: ApiUsageExtraHandler) -> None:
        assert handler.matches({}) is True

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_shows_extra_when_enabled(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageExtraHandler,
    ) -> None:
        """Should display extra usage when enabled in account."""
        cached_data: dict[str, Any] = {
            "extra_usage": {
                "is_enabled": True,
                "utilization": 10.0,
                "used_credits": 523,
                "monthly_limit": 5000,
            }
        }
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = cached_data

        result = handler.handle({})
        assert result.context is not None
        assert len(result.context) > 0
        context_str = result.context[0]
        assert "$" in context_str  # Should contain dollar amounts

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_empty_when_disabled(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageExtraHandler,
    ) -> None:
        """Should return empty when extra usage is disabled."""
        cached_data: dict[str, Any] = {
            "extra_usage": {
                "is_enabled": False,
                "utilization": 0,
                "used_credits": 0,
                "monthly_limit": 0,
            }
        }
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = cached_data

        result = handler.handle({})
        assert result.context == []

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_empty_when_no_extra_key(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageExtraHandler,
    ) -> None:
        """Should return empty when extra_usage key missing."""
        cached_data: dict[str, Any] = {
            "five_hour": {"utilization": 30.0},
        }
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = cached_data

        result = handler.handle({})
        assert result.context == []

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_empty_on_no_data(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ApiUsageExtraHandler,
    ) -> None:
        """Should return empty when no data available."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = None
        mock_cache.read.return_value = None
        mock_client = mock_client_cls.return_value
        mock_client.get_usage.return_value = None

        result = handler.handle({})
        assert result.context == []

    def test_get_acceptance_tests(self, handler: ApiUsageExtraHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
