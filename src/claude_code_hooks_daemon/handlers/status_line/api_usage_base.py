"""Base class for API usage status line handlers.

Shared logic for fetching and caching usage data from the Anthropic OAuth API.
Each concrete handler extracts its specific window (5-hour, 7-day, extra).
"""

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.utils.api_usage_client import ApiUsageClient
from claude_code_hooks_daemon.utils.usage_cache import UsageCache

logger = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".claude" / "status-line-cache.json"


class ApiUsageBaseHandler(Handler):
    """Base handler for API usage display.

    Handles cache read/write and API fallback. Subclasses implement
    _format_usage() to extract their specific data window.
    """

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Fetch usage data (cached or fresh) and format for display."""
        try:
            usage_data = self._get_usage_data()
            if not usage_data:
                return HookResult(context=[])

            # Check for no credentials marker
            if usage_data.get("_no_credentials"):
                return HookResult(context=["API: Set ANTHROPIC_API_KEY (Console key, not OAuth)"])

            formatted = self._format_usage(usage_data)
            if not formatted:
                return HookResult(context=[])

            return HookResult(context=[formatted])
        except Exception:
            logger.info("Error in %s handler", self.name)
            return HookResult(context=[])

    def _get_usage_data(self) -> dict[str, Any] | None:
        """Get usage data from cache or API.

        Returns:
            Usage data dict, or None if unavailable
        """
        cache = UsageCache()

        # Try fresh cache first
        cached = cache.read_if_fresh(CACHE_PATH)
        if cached:
            return cached

        # Cache stale - fetch from API
        client = ApiUsageClient()

        # Check if credentials are available
        token = client.get_credentials()
        if not token:
            # No credentials - return special marker for helpful error message
            return {"_no_credentials": True}

        fresh_data = client.get_usage()
        if fresh_data:
            cache.write(CACHE_PATH, fresh_data)
            return fresh_data

        # API failed - try stale cache as fallback
        stale = cache.read(CACHE_PATH)
        if stale:
            return stale

        return None

    def _format_usage(self, usage_data: dict[str, Any]) -> str | None:
        """Format usage data for display. Override in subclasses.

        Args:
            usage_data: Full API response data

        Returns:
            Formatted status string, or None to skip display
        """
        raise NotImplementedError
