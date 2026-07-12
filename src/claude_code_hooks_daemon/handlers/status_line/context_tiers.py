"""Shared context-tier classification — single source of truth.

Determines "what colour/tier is this context usage percentage in?" for a
given context window size. This logic is shared between the status line
(`ModelContextHandler`, which renders it as an icon/colour) and future
compact-trigger logic (which needs a plain "is this red?" boolean) — hence
its extraction into a standalone, dependency-free module.

Thresholds are keyed by context window size (in thousands of tokens). Larger
windows get tighter percentage thresholds because even moderate percentages
represent enormous absolute token counts.

200k thresholds (standard — Sonnet, Haiku, Opus-200k):
- Green (0-24%)
- Yellow (25-50%)
- Orange (51-75%)
- Red (76-89%)
- Critical (90-100%)

1000k thresholds (Opus-1M — tighter because 400k+ tokens is already huge):
- Green (0-14%)
- Yellow (15-29%)
- Orange (30-39%)
- Red (40-59%)
- Critical (60-100%)

Yellow is always derived as half of the orange threshold (integer division).

CRITICAL (Plan 00151) is a distinct top band ABOVE red. It exists so the
status line can shout a "compact NOW" signal and the compact supervisor can act
more aggressively (bypassing its cooldown) once context is dangerously high.
Crucially, CRITICAL is still "red or worse": ``is_red`` returns True across BOTH
the red and critical bands, because the sidecar's ``red`` flag drives the
supervisor's compact trigger and must not go False just because the percentage
climbed past the critical threshold.
"""

import enum
from dataclasses import dataclass

# Context threshold tier sizes, in tokens. The tier whose size threshold is
# <= the actual context_window_size wins (checked largest-first), falling
# back to the smallest (200k) tier for unknown/zero window sizes.
_CONTEXT_TIER_200K_SIZE = 200_000
_CONTEXT_TIER_200K_ORANGE_PCT = 51
_CONTEXT_TIER_200K_RED_PCT = 76
_CONTEXT_TIER_200K_CRITICAL_PCT = 90

_CONTEXT_TIER_1000K_SIZE = 1_000_000
_CONTEXT_TIER_1000K_ORANGE_PCT = 30
_CONTEXT_TIER_1000K_RED_PCT = 40
_CONTEXT_TIER_1000K_CRITICAL_PCT = 60

# Yellow band starts at half of orange (e.g. orange=51 -> yellow=25).
_YELLOW_DIVISOR = 2

# The compact-urgency midpoint is the integer mean of red and critical
# (e.g. red=76, critical=90 -> 83). Below it the ccy supervisor stays PATIENT
# in the red band (waits for the turn to settle before compacting); at/above it
# the supervisor compacts PROMPTLY even mid-turn (Plan 00152).
_COMPACT_URGENCY_DIVISOR = 2

# Fallback CRITICAL threshold for a TierThresholds constructed WITHOUT an
# explicit critical_pct (back-compat for callers predating Plan 00151). The
# canonical per-size defaults come from TierConfig.default(); this only guards
# bare TierThresholds(orange_pct=..., red_pct=...) construction.
_DEFAULT_CRITICAL_PCT = _CONTEXT_TIER_200K_CRITICAL_PCT


class ContextTier(enum.Enum):
    """Classification of context usage percentage into a colour tier."""

    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"
    CRITICAL = "critical"


@dataclass(frozen=True)
class TierThresholds:
    """Orange, red and critical percentage thresholds for one context-size tier.

    ``critical_pct`` (Plan 00151) is the start of the CRITICAL band above red.
    It defaults so pre-existing ``TierThresholds(orange_pct=..., red_pct=...)``
    construction keeps working; callers that care pass it explicitly.
    """

    orange_pct: int
    red_pct: int
    critical_pct: int = _DEFAULT_CRITICAL_PCT


@dataclass(frozen=True)
class TierConfig:
    """Configurable per-window-size threshold pairs.

    Holds the (orange, red) percentage thresholds for the 200k and 1000k
    context-window-size tiers. Callers build this from their own config
    overrides (e.g. handler options), keeping this module free of any
    knowledge of how configuration is sourced.
    """

    t200k: TierThresholds
    t1000k: TierThresholds

    @classmethod
    def default(cls) -> "TierConfig":
        """Build a TierConfig using the canonical default thresholds."""
        return cls(
            t200k=TierThresholds(
                orange_pct=_CONTEXT_TIER_200K_ORANGE_PCT,
                red_pct=_CONTEXT_TIER_200K_RED_PCT,
                critical_pct=_CONTEXT_TIER_200K_CRITICAL_PCT,
            ),
            t1000k=TierThresholds(
                orange_pct=_CONTEXT_TIER_1000K_ORANGE_PCT,
                red_pct=_CONTEXT_TIER_1000K_RED_PCT,
                critical_pct=_CONTEXT_TIER_1000K_CRITICAL_PCT,
            ),
        )


def resolve_tier_thresholds(window_size: int, cfg: TierConfig) -> TierThresholds:
    """Pick the context threshold tier for the given window size.

    Tiers are checked largest-first. If the window size meets or exceeds a
    tier's size threshold, that tier's thresholds are used. Falls back to
    the smallest tier (200k) when window_size is unknown or smaller than
    all configured tiers.

    Args:
        window_size: Context window size in tokens
        cfg: Threshold configuration to resolve against

    Returns:
        The matched tier's TierThresholds
    """
    if window_size >= _CONTEXT_TIER_1000K_SIZE:
        return cfg.t1000k

    return cfg.t200k


def classify_context(used_pct: float, window_size: int, cfg: TierConfig) -> ContextTier:
    """Classify a context usage percentage into a colour tier.

    Args:
        used_pct: Context usage percentage (0-100)
        window_size: Context window size in tokens (e.g. 200000, 1000000)
        cfg: Threshold configuration to classify against

    Returns:
        The matched ContextTier
    """
    thresholds = resolve_tier_thresholds(window_size, cfg)
    yellow_pct = thresholds.orange_pct // _YELLOW_DIVISOR

    if used_pct < yellow_pct:
        return ContextTier.GREEN
    if used_pct < thresholds.orange_pct:
        return ContextTier.YELLOW
    if used_pct < thresholds.red_pct:
        return ContextTier.ORANGE
    if used_pct < thresholds.critical_pct:
        return ContextTier.RED
    return ContextTier.CRITICAL


def is_red(used_pct: float, window_size: int, cfg: TierConfig) -> bool:
    """Return True if the usage percentage is RED **or worse** (critical).

    Convenience wrapper for callers (e.g. the compact-trigger supervisor) that
    only care about the red-or-above boolean. CRITICAL is deliberately included:
    it is the band ABOVE red, so a critical percentage is still "red" for the
    purpose of the sidecar's trigger flag — otherwise compaction would stop
    firing once context climbed past the critical threshold (Plan 00151).

    Args:
        used_pct: Context usage percentage (0-100)
        window_size: Context window size in tokens (e.g. 200000, 1000000)
        cfg: Threshold configuration to classify against

    Returns:
        True if classify_context(...) resolves to RED or CRITICAL
    """
    return classify_context(used_pct, window_size, cfg) in (
        ContextTier.RED,
        ContextTier.CRITICAL,
    )


def is_critical(used_pct: float, window_size: int, cfg: TierConfig) -> bool:
    """Return True if the usage percentage classifies as CRITICAL (Plan 00151).

    CRITICAL is the top band above red. The compact supervisor uses this to act
    more aggressively (bypassing its post-compact cooldown) and the status line
    uses it to render the loudest "compact NOW" signal.

    Args:
        used_pct: Context usage percentage (0-100)
        window_size: Context window size in tokens (e.g. 200000, 1000000)
        cfg: Threshold configuration to classify against

    Returns:
        True if classify_context(...) resolves to ContextTier.CRITICAL
    """
    return classify_context(used_pct, window_size, cfg) is ContextTier.CRITICAL


def compact_urgency_pct(thresholds: TierThresholds) -> int:
    """Return the compact-urgency midpoint between red and critical (Plan 00152).

    The midpoint is the integer mean of ``red_pct`` and ``critical_pct``
    (e.g. red=76, critical=90 -> 83). It splits the "red or worse" region into a
    lower PATIENT band ``[red, midpoint)`` and an upper PROMPT band
    ``[midpoint, critical)`` for the ccy supervisor's graduated compaction.

    Args:
        thresholds: The resolved per-window-size tier thresholds.

    Returns:
        The midpoint percentage (integer).
    """
    return (thresholds.red_pct + thresholds.critical_pct) // _COMPACT_URGENCY_DIVISOR


def is_compact_urgent(used_pct: float, window_size: int, cfg: TierConfig) -> bool:
    """Return True when usage is at/above the compact-urgency midpoint (Plan 00152).

    This is the signal the ccy supervisor uses to leave its PATIENT red band and
    compact PROMPTLY even while the child is streaming output. It is deliberately
    a superset of CRITICAL: any critical percentage is also compact-urgent,
    because critical always acts promptly.

    Args:
        used_pct: Context usage percentage (0-100)
        window_size: Context window size in tokens (e.g. 200000, 1000000)
        cfg: Threshold configuration to classify against

    Returns:
        True if ``used_pct`` is at or above ``compact_urgency_pct`` for the
        resolved tier.
    """
    thresholds = resolve_tier_thresholds(window_size, cfg)
    return used_pct >= compact_urgency_pct(thresholds)
