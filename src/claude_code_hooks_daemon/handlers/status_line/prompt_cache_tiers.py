"""Shared prompt-cache classification — single source of truth (Plan 00452).

Answers one question: **is this session's prompt cache in trouble, and how
seriously?** The status line renders the answer and any later supervisor logic
acts on it, and both read THIS module — so "the bar is showing a warning" and
"the supervisor should warm the cache" can never disagree.

That is Plan 00135 Decision J applied again. Context tiers had the identical
problem: a threshold duplicated between the renderer and the actuator drifts
the moment one side is tuned, and the drift is silent because each side looks
correct on its own. `context_tiers.py` is the conforming reference this module
mirrors.

**Nothing here is derived from a transcript.** Claude Code ships a
`prompt_cache` object on the Status payload carrying `warm`, `ttl`,
`expires_at`, `hit_ratio`, `misses`, `last_miss_at`, `last_miss_cause` and
`recache_tokens_if_cold`. An earlier design read the session transcript for
the same figures; that was abandoned once the payload was captured, because
every wanted number was already present and pre-computed.

**Four tiers, and UNKNOWN is load-bearing.** A session before any caching has
been observed is not cold — it has no state at all. Collapsing the two would
make every fresh session report a problem it does not have, and a warning that
fires on healthy sessions is quickly ignored on unhealthy ones.

**EXPIRING is arithmetic, not estimation.** `expires_at` is a deadline, so
there is no need to guess the idle gap or infer the TTL. The window scales
with the TTL rather than being fixed: a fixed six-minute window would mark the
entire five-minute band as expiring for its whole life, which is the same as
having no signal.

**A recent miss is reported even while WARM**, because the cache being warm
NOW says nothing about the rebuild having just been paid for. That rebuild is
the expensive event the operator wants to see — measured here, the same
invalidation cost 130k tokens early in a session and 509k at its peak.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Any, Final

#: Fraction of the TTL remaining below which the cache counts as EXPIRING.
#: 10% mirrors the "warm at TTL-10%" interval the warming arithmetic assumes.
_EXPIRING_FRACTION: Final[float] = 0.1

#: How recently a miss must have happened to still be worth showing. Every
#: long session accumulates old misses; surfacing those would be constant noise.
_RECENT_MISS_SECONDS: Final[int] = 300

#: `ttl` arrives as a short duration string ("1h", "5m", "30s").
_TTL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(\d+)([hms])$")

_SECONDS_PER_UNIT: Final[dict[str, int]] = {"s": 1, "m": 60, "h": 3600}

#: Joins multiple attributed causes into one renderable string.
_CAUSE_SEPARATOR: Final[str] = "+"


class PromptCacheTier(enum.Enum):
    """How much trouble the prompt cache is in."""

    #: No caching has been observed yet, or no payload was supplied. An
    #: ABSENCE of information — never to be treated as a cold verdict.
    UNKNOWN = "unknown"
    WARM = "warm"
    #: Alive, but inside the tail of its TTL.
    EXPIRING = "expiring"
    #: The prefix is gone and the next request rebuilds it.
    COLD = "cold"


@dataclass(frozen=True)
class PromptCacheThresholds:
    """The two tunables, kept together so a caller overrides them coherently."""

    expiring_fraction: float = _EXPIRING_FRACTION
    recent_miss_seconds: int = _RECENT_MISS_SECONDS


@dataclass(frozen=True)
class PromptCacheState:
    """Everything a renderer or a supervisor needs, already decided."""

    tier: PromptCacheTier
    ttl_seconds: int | None
    seconds_remaining: int | None
    rebuild_tokens: int | None
    hit_ratio: float | None
    recent_miss: bool
    recent_miss_cause: str | None


def _as_number(raw: object) -> float | None:
    """A numeric field as a float, or None when it is absent or not a number.

    `bool` is excluded deliberately: it is an `int` in Python, so `True` would
    otherwise pass straight through and render as a token count of zero.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def parse_ttl_seconds(raw: object) -> int | None:
    """`"1h"` as 3600 seconds, or None when the value is not a known shape.

    None rather than a default: a wrong TTL silently mis-times every expiry
    decision downstream, and a session whose TTL cannot be read is better
    served by no expiry verdict than by a confident wrong one.
    """
    if not isinstance(raw, str):
        return None
    match = _TTL_PATTERN.match(raw)
    if not match:
        return None
    return int(match.group(1)) * _SECONDS_PER_UNIT[match.group(2)]


def _recent_miss_cause(cache: dict[str, Any]) -> str | None:
    """The attributed cause(s) of the last miss, joined, or None if unstated."""
    stated = cache.get("last_miss_cause")
    if not isinstance(stated, dict):
        return None
    causes = stated.get("causes")
    if not isinstance(causes, list):
        return None
    named = [str(c) for c in causes if c]
    if not named:
        return None
    return _CAUSE_SEPARATOR.join(named)


def classify_prompt_cache(
    cache: object,
    now: float,
    cfg: PromptCacheThresholds | None = None,
) -> PromptCacheState:
    """Classify a `prompt_cache` payload into a single decided state.

    Pure: `now` is passed in rather than read, so every boundary in here is
    testable at the boundary.

    Args:
        cache: The `prompt_cache` object from the Status payload. Anything that
            is not a dict is treated as an absent payload.
        now: Current unix time in seconds.
        cfg: Threshold overrides; the canonical defaults are used when omitted.

    Returns:
        The decided `PromptCacheState`.
    """
    cfg = cfg or PromptCacheThresholds()

    if not isinstance(cache, dict) or not cache.get("caching_observed"):
        return PromptCacheState(
            tier=PromptCacheTier.UNKNOWN,
            ttl_seconds=None,
            seconds_remaining=None,
            rebuild_tokens=None,
            hit_ratio=None,
            recent_miss=False,
            recent_miss_cause=None,
        )

    ttl_seconds = parse_ttl_seconds(cache.get("ttl"))

    expires_at = _as_number(cache.get("expires_at"))
    seconds_remaining = int(expires_at - now) if expires_at is not None else None

    rebuild = _as_number(cache.get("recache_tokens_if_cold"))
    hit_ratio = _as_number(cache.get("hit_ratio"))

    last_miss_at = _as_number(cache.get("last_miss_at"))
    recent_miss = last_miss_at is not None and (now - last_miss_at) < cfg.recent_miss_seconds

    tier = _resolve_tier(
        warm=bool(cache.get("warm")),
        ttl_seconds=ttl_seconds,
        seconds_remaining=seconds_remaining,
        cfg=cfg,
    )

    return PromptCacheState(
        tier=tier,
        ttl_seconds=ttl_seconds,
        seconds_remaining=seconds_remaining,
        rebuild_tokens=int(rebuild) if rebuild is not None else None,
        hit_ratio=hit_ratio,
        recent_miss=recent_miss,
        recent_miss_cause=_recent_miss_cause(cache) if recent_miss else None,
    )


def _resolve_tier(
    warm: bool,
    ttl_seconds: int | None,
    seconds_remaining: int | None,
    cfg: PromptCacheThresholds,
) -> PromptCacheTier:
    """WARM, EXPIRING or COLD, given the payload's own deadline.

    An EXPIRING verdict requires BOTH a parseable TTL and a stated expiry:
    without the TTL there is no window to measure against, and inventing one
    would produce a confident wrong answer on exactly the sessions whose
    payload is least trustworthy.
    """
    if not warm:
        return PromptCacheTier.COLD
    if ttl_seconds is None or seconds_remaining is None:
        return PromptCacheTier.WARM
    if seconds_remaining < int(ttl_seconds * cfg.expiring_fraction):
        return PromptCacheTier.EXPIRING
    return PromptCacheTier.WARM


def is_cold(state: PromptCacheState) -> bool:
    """True only for a genuinely cold cache.

    UNKNOWN is excluded on purpose: it means nothing has been observed, which
    is not evidence of a cold cache and must never trigger action.
    """
    return state.tier is PromptCacheTier.COLD


def is_expiring(state: PromptCacheState) -> bool:
    """True when the cache is alive but inside the tail of its TTL."""
    return state.tier is PromptCacheTier.EXPIRING


def needs_attention(state: PromptCacheState) -> bool:
    """The one boolean a supervisor or a renderer should branch on.

    Deliberately a superset of `is_cold`: an EXPIRING cache is the case where
    acting is still CHEAP, and a cache that was rebuilt moments ago is worth
    showing even though it is warm right now — that rebuild is the expensive
    event, and it has already been paid for.
    """
    return is_cold(state) or is_expiring(state) or state.recent_miss
