"""Usage cache with TTL support.

Caches API usage data to reduce API call frequency. Uses file-based caching
with configurable staleness detection.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_SECONDS = 60


class UsageCache:
    """File-based cache for usage data with TTL support."""

    def __init__(self) -> None:
        self.default_max_age_seconds = DEFAULT_MAX_AGE_SECONDS

    def write(self, cache_path: Path, data: dict[str, Any]) -> None:
        """Write usage data to cache file.

        Args:
            cache_path: Path to cache file
            data: Usage data to cache
        """
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data))
        except OSError:
            logger.info("Failed to write usage cache")

    def read(self, cache_path: Path) -> dict[str, Any] | None:
        """Read usage data from cache file.

        Args:
            cache_path: Path to cache file

        Returns:
            Parsed cache data, or None if unavailable/invalid
        """
        if not cache_path.exists():
            return None

        try:
            raw = cache_path.read_text()
            result: dict[str, Any] = json.loads(raw)
            return result
        except (json.JSONDecodeError, OSError):
            logger.info("Failed to read usage cache")
            return None

    def is_stale(self, cache_path: Path, max_age_seconds: int | None = None) -> bool:
        """Check if cache file is older than max_age.

        Args:
            cache_path: Path to cache file
            max_age_seconds: Maximum age in seconds (default: 60)

        Returns:
            True if cache is stale or missing, False if fresh
        """
        if not cache_path.exists():
            return True

        max_age = max_age_seconds if max_age_seconds is not None else self.default_max_age_seconds
        file_age = time.time() - cache_path.stat().st_mtime
        return file_age >= max_age

    def read_if_fresh(
        self, cache_path: Path, max_age_seconds: int | None = None
    ) -> dict[str, Any] | None:
        """Read cache only if it's fresh (not stale).

        Args:
            cache_path: Path to cache file
            max_age_seconds: Maximum age in seconds (default: 60)

        Returns:
            Cached data if fresh, None if stale or unavailable
        """
        if self.is_stale(cache_path, max_age_seconds):
            return None

        return self.read(cache_path)
