"""Formatting utilities for status line display.

This module provides utilities for formatting tokens, progress bars, and time displays
in a compact, human-readable format.
"""

from datetime import datetime

FILLED_CIRCLE = "\u25cf"  # ●
EMPTY_CIRCLE = "\u25cb"  # ○

DEFAULT_BAR_WIDTH = 10


def format_token_count(count: int) -> str:
    """Format token count with k/m/b abbreviations.

    Formats large numbers with single-decimal precision for readability.
    Examples:
        - 999 -> "999"
        - 1000 -> "1k"
        - 1500 -> "1.5k"
        - 50000 -> "50k"
        - 1500000 -> "1.5m"

    Args:
        count: Token count to format (must be non-negative)

    Returns:
        Formatted string with k/m/b suffix if >= 1000

    Raises:
        ValueError: If count is negative
    """
    if count < 0:
        raise ValueError("Token count cannot be negative")

    if count < 1000:
        return str(count)

    if count >= 1_000_000_000:
        value = count / 1_000_000_000
        return _format_with_suffix(value, "b")

    if count >= 1_000_000:
        value = count / 1_000_000
        return _format_with_suffix(value, "m")

    value = count / 1000
    return _format_with_suffix(value, "k")


def _format_with_suffix(value: float, suffix: str) -> str:
    """Format a decimal value with suffix, removing unnecessary decimals.

    Args:
        value: Numeric value to format
        suffix: Suffix to append (k/m/b)

    Returns:
        Formatted string like "1k" or "1.5k"
    """
    rounded = round(value, 1)

    if rounded == int(rounded):
        return f"{int(rounded)}{suffix}"

    return f"{rounded}{suffix}"


def build_progress_bar(percentage: float, width: int = DEFAULT_BAR_WIDTH) -> str:
    """Build a visual progress bar using Unicode circle characters.

    Examples:
        - 30% -> "●●●○○○○○○○"
        - 50% -> "●●●●●○○○○○"
        - 100% -> "●●●●●●●●●●"

    Args:
        percentage: Value from 0-100 (clamped if outside range)
        width: Number of characters in the bar (default: 10)

    Returns:
        String of filled and empty circle characters
    """
    clamped = max(0.0, min(100.0, percentage))
    filled_count = round(clamped / 100.0 * width)
    empty_count = width - filled_count
    return FILLED_CIRCLE * filled_count + EMPTY_CIRCLE * empty_count


def format_reset_time(dt: datetime, style: str = "time") -> str:
    """Format a datetime for reset time display.

    Converts UTC datetime to local time and formats for display.

    Args:
        dt: Datetime object (should be timezone-aware UTC)
        style: One of "time" ("3:45pm"), "datetime" ("Feb 15, 3:45pm"), "date" ("Feb 15")

    Returns:
        Formatted time string

    Raises:
        ValueError: If style is not one of the valid options
    """
    valid_styles = ("time", "datetime", "date")
    if style not in valid_styles:
        raise ValueError(f"Invalid style '{style}'. Must be one of: {', '.join(valid_styles)}")

    # Convert to local time
    local_dt = dt.astimezone()

    hour = local_dt.hour
    minute = local_dt.minute
    am_pm = "am" if hour < 12 else "pm"
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12

    time_str = f"{display_hour}:{minute:02d}{am_pm}"
    month_str = local_dt.strftime("%b")
    day = local_dt.day

    if style == "time":
        return time_str
    if style == "datetime":
        return f"{month_str} {day}, {time_str}"
    # style == "date"
    return f"{month_str} {day}"
