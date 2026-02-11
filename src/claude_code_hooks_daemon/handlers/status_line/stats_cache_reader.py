"""Stats cache reader utility for usage tracking.

Reads and processes Claude usage statistics from ~/.claude/stats-cache.json
to calculate daily and weekly token usage percentages.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

# Daily token limits per model
DAILY_LIMITS: Final[dict[str, int]] = {
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-opus-4-5-20251101": 100_000,
}


def read_stats_cache(path: Path) -> dict[str, Any] | None:
    """Read and parse stats cache JSON file.

    Args:
        path: Path to stats-cache.json file

    Returns:
        Parsed cache data dictionary, or None if file doesn't exist or is invalid
    """
    try:
        if not path.exists():
            return None

        content = path.read_text()
        data: dict[str, Any] = json.loads(content)
        return data

    except (json.JSONDecodeError, PermissionError, OSError):
        # Silent fail - return None for any read/parse errors
        return None


def calculate_daily_usage(cache_data: dict[str, Any], model_id: str) -> float:
    """Calculate daily token usage percentage for a model.

    Args:
        cache_data: Parsed stats cache data
        model_id: Model identifier (e.g., "claude-sonnet-4-5-20250929")

    Returns:
        Usage percentage (0-100+), or 0.0 if no data or unknown model
    """
    # Check if model has a defined daily limit
    daily_limit = DAILY_LIMITS.get(model_id)
    if daily_limit is None:
        return 0.0

    # Get today's date
    today = datetime.now().strftime("%Y-%m-%d")

    # Extract today's usage for this model (dailyModelTokens is an ARRAY not a dict!)
    daily_tokens_array = cache_data.get("dailyModelTokens", [])

    # Find today's entry in the array
    tokens_used = 0
    for entry in daily_tokens_array:
        if entry.get("date") == today:
            tokens_by_model = entry.get("tokensByModel", {})
            tokens_used = tokens_by_model.get(model_id, 0)
            break

    # Calculate percentage
    if daily_limit == 0:
        return 0.0

    percentage: float = (tokens_used / daily_limit) * 100
    return percentage


def calculate_weekly_usage(cache_data: dict[str, Any], model_id: str) -> float:
    """Calculate weekly token usage percentage for a model.

    Sums usage from the last 7 days (including today).

    Args:
        cache_data: Parsed stats cache data
        model_id: Model identifier (e.g., "claude-sonnet-4-5-20250929")

    Returns:
        Usage percentage (0-100+), or 0.0 if no data or unknown model
    """
    # Check if model has a defined daily limit
    daily_limit = DAILY_LIMITS.get(model_id)
    if daily_limit is None:
        return 0.0

    # Calculate weekly limit (7 days)
    weekly_limit = daily_limit * 7

    # Get dates for the last 7 days
    today = datetime.now()
    last_7_days = {(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}

    # Sum tokens from last 7 days (dailyModelTokens is an ARRAY!)
    daily_tokens_array = cache_data.get("dailyModelTokens", [])
    total_tokens = 0

    for entry in daily_tokens_array:
        date = entry.get("date")
        if date in last_7_days:
            tokens_by_model = entry.get("tokensByModel", {})
            total_tokens += tokens_by_model.get(model_id, 0)

    # Calculate percentage
    if weekly_limit == 0:
        return 0.0

    return (total_tokens / weekly_limit) * 100
