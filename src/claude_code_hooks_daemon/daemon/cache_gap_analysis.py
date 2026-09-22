"""Idle-gap and cache-cost analysis over a session transcript (Plan 00452).

Answers the question the status line cannot: **would warming this project's
cache actually pay?** That turns entirely on the shape of its idle gaps. A
session driven every few minutes never goes cold and has nothing to gain from
warming; a human-paced one may cross its TTL many times a day, paying a full
prefix rebuild each time.

**This repository cannot answer that about itself.** Its crons drive it
continuously, so its own 98.87% hit ratio measures the warming rather than the
need for it — using it to argue anything about projects in general is circular.
That is precisely why this is a CLI-shaped analyser over a transcript path
rather than a number baked into a handler: the measurement has to be taken on
a HUMAN-PACED project, by whoever has one.

Pure and I/O-free: it consumes an iterable of lines. The caller opens the file,
which keeps the whole module testable on a list of strings and keeps the
tolerance rules below honest.

**Tolerance is a requirement, not politeness.** The transcript is external data
that Claude Code appends to LIVE, so the final line is routinely a partial
write mid-flush, and the file interleaves record types freely. A line that does
not parse is not an error — it is a line that is not a usage record.

**Main and sub are split.** `isSidechain` separates them, and they diverge
sharply enough that one blended figure hides the expensive half: measured here,
98.87% on the main thread against 62.17% on a short sub-agent.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import statistics
from collections.abc import Iterable
from typing import Any, Final

#: Gap histogram buckets as (label, exclusive upper bound in seconds). The last
#: bucket is unbounded and its bound is None. Chosen to straddle BOTH TTLs: the
#: 5-minute and 1-hour boundaries each fall on a bucket edge, so the histogram
#: can be read directly against either.
GAP_BUCKETS: Final[tuple[tuple[str, int | None], ...]] = (
    ("<1m", 60),
    ("1-5m", 300),
    ("5-15m", 900),
    ("15-60m", 3600),
    (">60m", None),
)

#: The two TTLs Claude Code actually uses, as (label, seconds).
_TTL_SECONDS: Final[dict[str, int]] = {"5m": 300, "1h": 3600}

_EMPTY_TOKENS: Final[dict[str, int]] = {
    "input": 0,
    "output": 0,
    "cache_read": 0,
    "cache_write": 0,
    "ttl_5m_write": 0,
    "ttl_1h_write": 0,
}


def parse_timestamp(raw: object) -> float | None:
    """A record's ISO-8601 `timestamp` as unix seconds, or None.

    None rather than a fallback: a mis-parsed timestamp does not fail loudly,
    it produces a plausible and WRONG gap histogram, which is worse than no
    histogram at all. Claude Code writes a `Z` suffix, which predates
    `fromisoformat`'s support for it on older Pythons, so it is normalised.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _as_int(raw: object) -> int:
    """A token count as an int, treating anything unexpected as zero."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def _bucket_for(gap: float) -> str:
    """The histogram bucket a gap belongs to. Total by construction."""
    for label, upper in GAP_BUCKETS:
        if upper is None or gap < upper:
            return label
    return GAP_BUCKETS[-1][0]


def _accumulate_usage(usage: dict[str, Any], tokens: dict[str, int]) -> None:
    """Fold one record's usage into the running totals."""
    tokens["input"] += _as_int(usage.get("input_tokens"))
    tokens["output"] += _as_int(usage.get("output_tokens"))
    tokens["cache_read"] += _as_int(usage.get("cache_read_input_tokens"))
    tokens["cache_write"] += _as_int(usage.get("cache_creation_input_tokens"))

    creation = usage.get("cache_creation")
    if isinstance(creation, dict):
        tokens["ttl_5m_write"] += _as_int(creation.get("ephemeral_5m_input_tokens"))
        tokens["ttl_1h_write"] += _as_int(creation.get("ephemeral_1h_input_tokens"))


def _gap_report(timestamps: list[float]) -> dict[str, Any]:
    """Histogram, TTL crossings and summary statistics for the idle gaps.

    Gaps are taken over SORTED timestamps. A transcript is normally already in
    order, but a single out-of-order record would otherwise yield a negative
    gap, which silently drags both the median and the maximum downward — an
    error that makes a project look better-behaved than it is.
    """
    histogram = {label: 0 for label, _ in GAP_BUCKETS}
    report: dict[str, Any] = {
        "count": 0,
        "histogram": histogram,
        "max_seconds": 0.0,
        "median_seconds": 0.0,
    }
    for label, seconds in _TTL_SECONDS.items():
        report[f"exceeding_{label}"] = 0

    ordered = sorted(timestamps)
    gaps = [b - a for a, b in itertools.pairwise(ordered)]
    if not gaps:
        return report

    for gap in gaps:
        histogram[_bucket_for(gap)] += 1
        for label, seconds in _TTL_SECONDS.items():
            if gap > seconds:
                report[f"exceeding_{label}"] += 1

    report["count"] = len(gaps)
    report["max_seconds"] = max(gaps)
    report["median_seconds"] = statistics.median(gaps)
    return report


def analyse_transcript(lines: Iterable[str]) -> dict[str, Any]:
    """Build the cache/gap report for one session transcript.

    Args:
        lines: The transcript's lines, in file order. Lines that are not JSON,
            or that carry no usage object, are skipped rather than raising.

    Returns:
        A JSON-serialisable report: request counts, token totals split by TTL,
        the idle-gap histogram with per-TTL crossing counts, and the hit ratio.
    """
    tokens = dict(_EMPTY_TOKENS)
    timestamps: list[float] = []
    requests = 0
    sidechain_requests = 0
    writing_requests = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        usage = (record.get("message") or {}).get("usage")
        if not isinstance(usage, dict):
            continue

        if record.get("isSidechain"):
            # Counted, but deliberately kept out of the main-thread totals:
            # a blended figure hides whichever half is the expensive one.
            sidechain_requests += 1
            continue

        requests += 1
        if _as_int(usage.get("cache_creation_input_tokens")) > 0:
            writing_requests += 1
        _accumulate_usage(usage, tokens)

        # Tokens are accumulated even when the timestamp is unreadable:
        # dropping them would understate the cost over a malformed line.
        moment = parse_timestamp(record.get("timestamp"))
        if moment is not None:
            timestamps.append(moment)

    cacheable = tokens["cache_read"] + tokens["cache_write"]

    return {
        "requests": requests,
        "sidechain_requests": sidechain_requests,
        "writing_requests": writing_requests,
        "tokens": tokens,
        "gaps": _gap_report(timestamps),
        "hit_ratio": (tokens["cache_read"] / cacheable) if cacheable else None,
        "span_seconds": (max(timestamps) - min(timestamps)) if timestamps else 0.0,
    }
