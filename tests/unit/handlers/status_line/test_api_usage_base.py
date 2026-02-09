"""Tests for ApiUsageBaseHandler."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.status_line.api_usage_base import (
    ApiUsageBaseHandler,
)


class ConcreteUsageHandler(ApiUsageBaseHandler):
    """Concrete test implementation of the base handler."""

    def __init__(self) -> None:
        from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority

        super().__init__(
            handler_id=HandlerID.API_USAGE_FIVE_HOUR,
            priority=Priority.API_USAGE_FIVE_HOUR,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def _format_usage(self, usage_data: dict[str, Any]) -> str | None:
        pct = usage_data.get("five_hour", {}).get("utilization")
        if pct is not None:
            return f"test: {pct}%"
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestApiUsageBaseHandler:
    """Test base API usage handler shared logic."""

    @pytest.fixture
    def handler(self) -> ConcreteUsageHandler:
        return ConcreteUsageHandler()

    def test_matches_always_true(self, handler: ConcreteUsageHandler) -> None:
        assert handler.matches({}) is True

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_uses_fresh_cache(
        self, mock_cache_cls: MagicMock, handler: ConcreteUsageHandler
    ) -> None:
        """Should use cached data when fresh."""
        cached: dict[str, Any] = {"five_hour": {"utilization": 30.0}}
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = cached

        result = handler.handle({})
        assert result.context is not None
        assert "30.0%" in result.context[0]

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_fetches_api_when_cache_stale(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ConcreteUsageHandler,
    ) -> None:
        """Should fetch from API and write cache when cache is stale."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = None

        api_data: dict[str, Any] = {"five_hour": {"utilization": 45.0}}
        mock_client = mock_client_cls.return_value
        mock_client.get_usage.return_value = api_data

        result = handler.handle({})
        assert "45.0%" in result.context[0]
        mock_cache.write.assert_called_once()

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_falls_back_to_stale_cache(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ConcreteUsageHandler,
    ) -> None:
        """Should use stale cache when API fails."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = None
        stale: dict[str, Any] = {"five_hour": {"utilization": 20.0}}
        mock_cache.read.return_value = stale

        mock_client = mock_client_cls.return_value
        mock_client.get_usage.return_value = None

        result = handler.handle({})
        assert "20.0%" in result.context[0]

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.ApiUsageClient")
    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_returns_empty_when_all_fail(
        self,
        mock_cache_cls: MagicMock,
        mock_client_cls: MagicMock,
        handler: ConcreteUsageHandler,
    ) -> None:
        """Should return empty context when no data available."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = None
        mock_cache.read.return_value = None

        mock_client = mock_client_cls.return_value
        mock_client.get_usage.return_value = None

        result = handler.handle({})
        assert result.context == []

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_returns_empty_when_format_returns_none(
        self, mock_cache_cls: MagicMock, handler: ConcreteUsageHandler
    ) -> None:
        """Should return empty when _format_usage returns None."""
        cached: dict[str, Any] = {"seven_day": {"utilization": 50.0}}
        mock_cache = mock_cache_cls.return_value
        mock_cache.read_if_fresh.return_value = cached

        result = handler.handle({})
        assert result.context == []

    @patch("claude_code_hooks_daemon.handlers.status_line.api_usage_base.UsageCache")
    def test_handle_catches_exceptions(
        self, mock_cache_cls: MagicMock, handler: ConcreteUsageHandler
    ) -> None:
        """Should catch exceptions and return empty context."""
        mock_cache_cls.side_effect = RuntimeError("boom")

        result = handler.handle({})
        assert result.context == []
