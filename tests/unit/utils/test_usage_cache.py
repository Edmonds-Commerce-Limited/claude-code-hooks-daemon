"""Tests for usage cache.

Following TDD: Tests written BEFORE implementation.
"""

import json
import time
from pathlib import Path

from claude_code_hooks_daemon.utils.usage_cache import UsageCache


class TestUsageCache:
    """Test usage cache with TTL support."""

    # --- write() and read() tests ---

    def test_write_creates_cache_file(self, tmp_path: Path) -> None:
        """write() should create the cache file."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        data = {"five_hour": {"utilization": 30.0}}

        cache.write(cache_path, data)
        assert cache_path.exists()

    def test_read_returns_cached_data(self, tmp_path: Path) -> None:
        """read() should return data written by write()."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        data = {"five_hour": {"utilization": 30.0}}

        cache.write(cache_path, data)
        result = cache.read(cache_path)
        assert result is not None
        assert result["five_hour"]["utilization"] == 30.0

    def test_read_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        """read() should return None when cache file doesn't exist."""
        cache = UsageCache()
        cache_path = tmp_path / "nonexistent.json"

        result = cache.read(cache_path)
        assert result is None

    def test_read_returns_none_when_malformed_json(self, tmp_path: Path) -> None:
        """read() should return None when cache file has invalid JSON."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("not valid json{{{")

        result = cache.read(cache_path)
        assert result is None

    # --- is_stale() tests ---

    def test_is_stale_returns_true_when_file_missing(self, tmp_path: Path) -> None:
        """is_stale() should return True when cache file doesn't exist."""
        cache = UsageCache()
        cache_path = tmp_path / "nonexistent.json"

        assert cache.is_stale(cache_path) is True

    def test_is_stale_returns_false_for_fresh_cache(self, tmp_path: Path) -> None:
        """is_stale() should return False for recently written cache."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("{}")

        assert cache.is_stale(cache_path, max_age_seconds=60) is False

    def test_is_stale_returns_true_for_old_cache(self, tmp_path: Path) -> None:
        """is_stale() should return True for cache older than max_age."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("{}")

        # Set modification time to 120 seconds ago
        old_time = time.time() - 120
        import os

        os.utime(cache_path, (old_time, old_time))

        assert cache.is_stale(cache_path, max_age_seconds=60) is True

    def test_default_max_age_is_sixty_seconds(self, tmp_path: Path) -> None:
        """Default max_age should be 60 seconds."""
        cache = UsageCache()
        assert cache.default_max_age_seconds == 60

    # --- read_if_fresh() tests ---

    def test_read_if_fresh_returns_data_when_fresh(self, tmp_path: Path) -> None:
        """read_if_fresh() should return data when cache is fresh."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        data = {"five_hour": {"utilization": 45.0}}

        cache.write(cache_path, data)
        result = cache.read_if_fresh(cache_path)
        assert result is not None
        assert result["five_hour"]["utilization"] == 45.0

    def test_read_if_fresh_returns_none_when_stale(self, tmp_path: Path) -> None:
        """read_if_fresh() should return None when cache is stale."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text(json.dumps({"data": True}))

        # Make it old
        old_time = time.time() - 120
        import os

        os.utime(cache_path, (old_time, old_time))

        result = cache.read_if_fresh(cache_path, max_age_seconds=60)
        assert result is None

    def test_read_if_fresh_returns_none_when_missing(self, tmp_path: Path) -> None:
        """read_if_fresh() should return None when file doesn't exist."""
        cache = UsageCache()
        cache_path = tmp_path / "nonexistent.json"

        result = cache.read_if_fresh(cache_path)
        assert result is None

    # --- write creates valid JSON ---

    def test_write_creates_valid_json(self, tmp_path: Path) -> None:
        """write() should create valid JSON that can be parsed."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        data = {
            "five_hour": {"utilization": 30.0, "resets_at": "2026-02-09T20:00:00Z"},
            "seven_day": {"utilization": 50.0, "resets_at": "2026-02-15T00:00:00Z"},
        }

        cache.write(cache_path, data)

        # Verify it's valid JSON
        raw = cache_path.read_text()
        parsed = json.loads(raw)
        assert parsed == data

    # --- custom TTL ---

    def test_custom_max_age(self, tmp_path: Path) -> None:
        """Should support custom max_age_seconds."""
        cache = UsageCache()
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("{}")

        # 5 seconds ago
        import os

        old_time = time.time() - 5
        os.utime(cache_path, (old_time, old_time))

        # With 3-second TTL, should be stale
        assert cache.is_stale(cache_path, max_age_seconds=3) is True

        # With 10-second TTL, should be fresh
        assert cache.is_stale(cache_path, max_age_seconds=10) is False
