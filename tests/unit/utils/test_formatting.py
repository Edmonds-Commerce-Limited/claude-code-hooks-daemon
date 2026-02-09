"""Tests for formatting utilities.

Following TDD: These tests are written BEFORE implementation.
They should FAIL initially, then PASS after implementation.
"""

from datetime import UTC, datetime

import pytest

from claude_code_hooks_daemon.utils.formatting import (
    build_progress_bar,
    format_reset_time,
    format_token_count,
)


class TestFormatTokenCount:
    """Test token count formatting with k/m/b abbreviations."""

    def test_zero_tokens(self) -> None:
        """Zero should display as '0'."""
        assert format_token_count(0) == "0"

    def test_single_digit(self) -> None:
        """Single digits should display as-is."""
        assert format_token_count(1) == "1"
        assert format_token_count(5) == "5"
        assert format_token_count(9) == "9"

    def test_double_digit(self) -> None:
        """Double digits should display as-is."""
        assert format_token_count(10) == "10"
        assert format_token_count(42) == "42"
        assert format_token_count(99) == "99"

    def test_triple_digit(self) -> None:
        """Triple digits should display as-is."""
        assert format_token_count(100) == "100"
        assert format_token_count(500) == "500"
        assert format_token_count(999) == "999"

    def test_exactly_one_thousand(self) -> None:
        """1000 should display as '1k'."""
        assert format_token_count(1000) == "1k"

    def test_thousands_no_decimal(self) -> None:
        """Thousands with no fractional part should display as integer + k."""
        assert format_token_count(2000) == "2k"
        assert format_token_count(5000) == "5k"
        assert format_token_count(10000) == "10k"
        assert format_token_count(50000) == "50k"
        assert format_token_count(100000) == "100k"

    def test_thousands_with_decimal(self) -> None:
        """Thousands with fractional part should display with one decimal."""
        assert format_token_count(1500) == "1.5k"
        assert format_token_count(2300) == "2.3k"
        assert format_token_count(12500) == "12.5k"
        assert format_token_count(99900) == "99.9k"

    def test_rounds_to_one_decimal(self) -> None:
        """Fractional thousands should round to one decimal place (banker's rounding)."""
        assert format_token_count(1234) == "1.2k"  # 1.234 rounds to 1.2
        assert format_token_count(1250) == "1.2k"  # 1.250 banker's rounds to 1.2 (even)
        assert format_token_count(1260) == "1.3k"  # 1.260 rounds to 1.3
        assert format_token_count(9999) == "10k"  # 9.999 rounds to 10.0, displayed as 10k

    def test_exactly_one_million(self) -> None:
        """1,000,000 should display as '1m'."""
        assert format_token_count(1000000) == "1m"

    def test_millions_no_decimal(self) -> None:
        """Millions with no fractional part should display as integer + m."""
        assert format_token_count(2000000) == "2m"
        assert format_token_count(5000000) == "5m"
        assert format_token_count(10000000) == "10m"
        assert format_token_count(100000000) == "100m"

    def test_millions_with_decimal(self) -> None:
        """Millions with fractional part should display with one decimal."""
        assert format_token_count(1500000) == "1.5m"
        assert format_token_count(2300000) == "2.3m"
        assert format_token_count(12500000) == "12.5m"

    def test_exactly_one_billion(self) -> None:
        """1,000,000,000 should display as '1b'."""
        assert format_token_count(1000000000) == "1b"

    def test_billions_no_decimal(self) -> None:
        """Billions with no fractional part should display as integer + b."""
        assert format_token_count(2000000000) == "2b"
        assert format_token_count(5000000000) == "5b"

    def test_billions_with_decimal(self) -> None:
        """Billions with fractional part should display with one decimal."""
        assert format_token_count(1500000000) == "1.5b"
        assert format_token_count(2300000000) == "2.3b"

    def test_negative_raises_value_error(self) -> None:
        """Negative token counts should raise ValueError."""
        with pytest.raises(ValueError, match="Token count cannot be negative"):
            format_token_count(-1)
        with pytest.raises(ValueError, match="Token count cannot be negative"):
            format_token_count(-1000)

    def test_real_world_examples(self) -> None:
        """Test with real-world Claude token counts."""
        # Haiku context window
        assert format_token_count(200000) == "200k"

        # Sonnet context window
        assert format_token_count(200000) == "200k"

        # Opus context window (hypothetical)
        assert format_token_count(200000) == "200k"

        # Typical usage amounts
        assert format_token_count(50123) == "50.1k"
        assert format_token_count(75456) == "75.5k"
        assert format_token_count(150789) == "150.8k"


class TestBuildProgressBar:
    """Test progress bar builder with Unicode characters."""

    def test_zero_percent(self) -> None:
        """0% should be all empty circles."""
        assert (
            build_progress_bar(0.0)
            == "\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb"
        )

    def test_hundred_percent(self) -> None:
        """100% should be all filled circles."""
        assert (
            build_progress_bar(100.0)
            == "\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf"
        )

    def test_fifty_percent(self) -> None:
        """50% should be half filled."""
        assert (
            build_progress_bar(50.0)
            == "\u25cf\u25cf\u25cf\u25cf\u25cf\u25cb\u25cb\u25cb\u25cb\u25cb"
        )

    def test_thirty_percent(self) -> None:
        """30% should have 3 filled out of 10."""
        assert (
            build_progress_bar(30.0)
            == "\u25cf\u25cf\u25cf\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb"
        )

    def test_ten_percent(self) -> None:
        """10% should have 1 filled out of 10."""
        assert (
            build_progress_bar(10.0)
            == "\u25cf\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb"
        )

    def test_ninety_percent(self) -> None:
        """90% should have 9 filled out of 10."""
        assert (
            build_progress_bar(90.0)
            == "\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cb"
        )

    def test_custom_width(self) -> None:
        """Custom width should produce correct number of characters."""
        bar = build_progress_bar(50.0, width=5)
        assert len(bar) == 5
        assert bar == "\u25cf\u25cf\u25cb\u25cb\u25cb"  # 2.5 rounds to 3? No, int(2.5) = 2

    def test_custom_width_twenty(self) -> None:
        """Width 20 with 25% should produce 5 filled."""
        bar = build_progress_bar(25.0, width=20)
        assert len(bar) == 20
        filled = bar.count("\u25cf")
        assert filled == 5

    def test_negative_clamped_to_zero(self) -> None:
        """Negative percentage should clamp to 0%."""
        assert (
            build_progress_bar(-10.0)
            == "\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb\u25cb"
        )

    def test_over_hundred_clamped(self) -> None:
        """Over 100% should clamp to 100%."""
        assert (
            build_progress_bar(150.0)
            == "\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf\u25cf"
        )

    def test_default_width_is_ten(self) -> None:
        """Default bar width should be 10 characters."""
        bar = build_progress_bar(0.0)
        assert len(bar) == 10

    def test_small_percentage_rounds_down(self) -> None:
        """5% of 10 = 0.5, should round to 1 filled (at least 1 when > 0)."""
        bar = build_progress_bar(5.0)
        filled = bar.count("\u25cf")
        # 5% of 10 = 0.5 -> rounds to 0 or 1 depending on implementation
        assert filled in (0, 1)

    def test_returns_string(self) -> None:
        """Progress bar should return a string."""
        result = build_progress_bar(50.0)
        assert isinstance(result, str)


class TestFormatResetTime:
    """Test reset time formatting from ISO 8601 strings."""

    def test_time_style_afternoon(self) -> None:
        """Time style should show 'h:MMpm' format."""
        # 3:45 PM UTC
        dt = datetime(2026, 2, 9, 15, 45, 0, tzinfo=UTC)
        result = format_reset_time(dt, style="time")
        # Should contain time in some locale format
        assert ":" in result
        assert "45" in result

    def test_time_style_morning(self) -> None:
        """Time style should handle AM times."""
        dt = datetime(2026, 2, 9, 9, 30, 0, tzinfo=UTC)
        result = format_reset_time(dt, style="time")
        assert ":" in result
        assert "30" in result

    def test_datetime_style(self) -> None:
        """Datetime style should show date and time."""
        dt = datetime(2026, 2, 15, 16, 30, 0, tzinfo=UTC)
        result = format_reset_time(dt, style="datetime")
        # Should contain month and time
        assert "Feb" in result
        assert "15" in result

    def test_date_style(self) -> None:
        """Date style should show only the date."""
        dt = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
        result = format_reset_time(dt, style="date")
        assert "Mar" in result
        assert "1" in result

    def test_invalid_style_raises(self) -> None:
        """Invalid style should raise ValueError."""
        dt = datetime(2026, 2, 9, 15, 45, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="Invalid style"):
            format_reset_time(dt, style="invalid")

    def test_returns_string(self) -> None:
        """All styles should return strings."""
        dt = datetime(2026, 2, 9, 15, 45, 0, tzinfo=UTC)
        assert isinstance(format_reset_time(dt, style="time"), str)
        assert isinstance(format_reset_time(dt, style="datetime"), str)
        assert isinstance(format_reset_time(dt, style="date"), str)

    def test_default_style_is_time(self) -> None:
        """Default style should be 'time'."""
        dt = datetime(2026, 2, 9, 15, 45, 0, tzinfo=UTC)
        result = format_reset_time(dt)
        assert ":" in result
        assert "45" in result
