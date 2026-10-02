"""Loader for the synthetic Status payload fixtures that carry ``rate_limits``.

Plan 00479 Task 1.2. Values are synthetic. ``NOW`` sits inside both windows of
every fixture except ``five_hour_expired``, whose 5h window ended before it.
"""

import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "status_usage"

#: A fixed "current time" (epoch seconds) for the fixtures' ``resets_at`` values.
NOW = 1_800_000_000.0

#: ``five_hour.resets_at`` of the live-shaped fixtures, 3h from ``NOW``.
FIVE_HOUR_RESETS_AT = 1_800_010_800

#: ``seven_day.resets_at`` of the live-shaped fixtures.
SEVEN_DAY_RESETS_AT = 1_800_600_000


def load_status_payload(name: str) -> dict[str, Any]:
    """Load ``tests/fixtures/status_usage/<name>`` (a file name) as a Status hook_input dict."""
    payload: dict[str, Any] = json.loads((FIXTURE_DIR / name).read_text("utf-8"))
    return payload
