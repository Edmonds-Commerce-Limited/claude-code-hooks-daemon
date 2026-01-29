"""Tests for stats cache reader utility."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.handlers.status_line.stats_cache_reader import (
    DAILY_LIMITS,
    calculate_daily_usage,
    calculate_weekly_usage,
    read_stats_cache,
)


class TestReadStatsCache:
    """Tests for read_stats_cache function."""

    def test_read_valid_stats_cache(self) -> None:
        """Test reading valid stats cache file with REAL format (array not dict)."""
        cache_data = {
            "dailyModelTokens": [
                {
                    "date": "2026-01-29",
                    "tokensByModel": {
                        "claude-sonnet-4-5-20250929": 50000,
                    }
                }
            ]
        }
        json_content = json.dumps(cache_data)

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=json_content):
                result = read_stats_cache(Path("/fake/path"))

        assert result == cache_data
        assert "dailyModelTokens" in result

    def test_read_missing_file(self) -> None:
        """Test reading non-existent stats cache file."""
        with patch("pathlib.Path.exists", return_value=False):
            result = read_stats_cache(Path("/fake/path"))

        assert result is None

    def test_read_invalid_json(self) -> None:
        """Test reading file with invalid JSON."""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value="not json"):
                result = read_stats_cache(Path("/fake/path"))

        assert result is None

    def test_read_permission_error(self) -> None:
        """Test reading file with permission error."""
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", side_effect=PermissionError()):
                result = read_stats_cache(Path("/fake/path"))

        assert result is None


class TestCalculateDailyUsage:
    """Tests for calculate_daily_usage function."""

    def test_calculate_usage_for_today(self) -> None:
        """Test calculating usage for current day with REAL array format."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {
                    "date": today,
                    "tokensByModel": {
                        "claude-sonnet-4-5-20250929": 50000,
                    }
                }
            ]
        }

        # 50000 / 200000 = 25%
        result = calculate_daily_usage(cache_data, "claude-sonnet-4-5-20250929")
        assert result == 25.0

    def test_calculate_usage_no_data_for_today(self) -> None:
        """Test calculating usage when no data exists for today."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [{"date": yesterday, "tokensByModel": {"claude-sonnet-4-5-20250929": 100000}}]
        }

        # No data for today = 0%
        result = calculate_daily_usage(cache_data, "claude-sonnet-4-5-20250929")
        assert result == 0.0

    def test_calculate_usage_empty_cache(self) -> None:
        """Test calculating usage with empty cache."""
        cache_data = {"dailyModelTokens": []}

        result = calculate_daily_usage(cache_data, "claude-sonnet-4-5-20250929")
        assert result == 0.0

    def test_calculate_usage_unknown_model(self) -> None:
        """Test calculating usage for model without limit defined."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [{"date": today, "tokensByModel": {"unknown-model": 50000}}]
        }

        # Unknown model = 0% (no limit defined)
        result = calculate_daily_usage(cache_data, "unknown-model")
        assert result == 0.0

    def test_calculate_usage_opus_model(self) -> None:
        """Test calculating usage for Opus model (100k daily limit)."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [{"date": today, "tokensByModel": {"claude-opus-4-5-20251101": 30000}}]
        }

        # 30000 / 100000 = 30%
        result = calculate_daily_usage(cache_data, "claude-opus-4-5-20251101")
        assert result == 30.0

    def test_calculate_usage_over_limit(self) -> None:
        """Test calculating usage when over daily limit."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {
                    "date": today,
                    "tokensByModel": {
                        "claude-sonnet-4-5-20250929": 250000,  # Over 200k limit
                    }
                }
            ]
        }

        # 250000 / 200000 = 125%
        result = calculate_daily_usage(cache_data, "claude-sonnet-4-5-20250929")
        assert result == 125.0


class TestCalculateWeeklyUsage:
    """Tests for calculate_weekly_usage function."""

    def test_calculate_weekly_usage_multiple_days(self) -> None:
        """Test calculating usage across multiple days."""
        today = datetime.now()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        cache_data = {
            "dailyModelTokens": [
                {"date": dates[0], "tokensByModel": {"claude-sonnet-4-5-20250929": 30000}},  # Today
                {"date": dates[1], "tokensByModel": {"claude-sonnet-4-5-20250929": 40000}},  # Yesterday
                {"date": dates[2], "tokensByModel": {"claude-sonnet-4-5-20250929": 50000}},  # 2 days ago
                {"date": dates[6], "tokensByModel": {"claude-sonnet-4-5-20250929": 20000}},  # 6 days ago
            ]
        }

        # Total: 140000 tokens
        # Weekly limit: 200000 * 7 = 1,400,000
        # Usage: 140000 / 1400000 = 10%
        result = calculate_weekly_usage(cache_data, "claude-sonnet-4-5-20250929")
        assert result == 10.0

    def test_calculate_weekly_usage_partial_week(self) -> None:
        """Test calculating usage with only some days present."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": [
                {"date": today, "tokensByModel": {"claude-sonnet-4-5-20250929": 100000}},
            ]
        }

        # 100000 / 1400000 ≈ 7.14%
        result = calculate_weekly_usage(cache_data, "claude-sonnet-4-5-20250929")
        assert abs(result - 7.14) < 0.01  # Allow small floating point difference

    def test_calculate_weekly_usage_empty_cache(self) -> None:
        """Test calculating weekly usage with empty cache."""
        cache_data = {"dailyModelTokens": []}

        result = calculate_weekly_usage(cache_data, "claude-sonnet-4-5-20250929")
        assert result == 0.0

    def test_calculate_weekly_usage_unknown_model(self) -> None:
        """Test calculating weekly usage for unknown model."""
        today = datetime.now().strftime("%Y-%m-%d")
        cache_data = {
            "dailyModelTokens": {
                today: {"unknown-model": 50000},
            }
        }

        result = calculate_weekly_usage(cache_data, "unknown-model")
        assert result == 0.0

    def test_calculate_weekly_usage_ignores_old_data(self) -> None:
        """Test that data older than 7 days is ignored."""
        today = datetime.now()
        old_date = (today - timedelta(days=8)).strftime("%Y-%m-%d")
        recent_date = today.strftime("%Y-%m-%d")

        cache_data = {
            "dailyModelTokens": [
                {"date": recent_date, "tokensByModel": {"claude-sonnet-4-5-20250929": 70000}},
                {"date": old_date, "tokensByModel": {"claude-sonnet-4-5-20250929": 999999}},  # Should be ignored
            ]
        }

        # Only 70000 should be counted
        # 70000 / 1400000 = 5%
        result = calculate_weekly_usage(cache_data, "claude-sonnet-4-5-20250929")
        assert result == 5.0


class TestDailyLimits:
    """Tests for DAILY_LIMITS constant."""

    def test_daily_limits_defined(self) -> None:
        """Test that daily limits are defined for known models."""
        assert "claude-sonnet-4-5-20250929" in DAILY_LIMITS
        assert "claude-opus-4-5-20251101" in DAILY_LIMITS

    def test_sonnet_limit(self) -> None:
        """Test Sonnet daily limit is 200k."""
        assert DAILY_LIMITS["claude-sonnet-4-5-20250929"] == 200_000

    def test_opus_limit(self) -> None:
        """Test Opus daily limit is 100k."""
        assert DAILY_LIMITS["claude-opus-4-5-20251101"] == 100_000
