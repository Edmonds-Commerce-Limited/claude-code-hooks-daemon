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
- Red (76-100%)

1000k thresholds (Opus-1M — tighter because 400k+ tokens is already huge):
- Green (0-14%)
- Yellow (15-29%)
- Orange (30-39%)
- Red (40-100%)

Yellow is always derived as half of the orange threshold (integer division).
"""

import enum
from dataclasses import dataclass

# Context threshold tier sizes, in tokens. The tier whose size threshold is
# <= the actual context_window_size wins (checked largest-first), falling
# back to the smallest (200k) tier for unknown/zero window sizes.
_CONTEXT_TIER_200K_SIZE = 200_000
_CONTEXT_TIER_200K_ORANGE_PCT = 51
_CONTEXT_TIER_200K_RED_PCT = 76

_CONTEXT_TIER_1000K_SIZE = 1_000_000
_CONTEXT_TIER_1000K_ORANGE_PCT = 30
_CONTEXT_TIER_1000K_RED_PCT = 40

# Yellow band starts at half of orange (e.g. orange=51 -> yellow=25).
_YELLOW_DIVISOR = 2


class ContextTier(enum.Enum):
    """Classification of context usage percentage into a colour tier."""

    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


@dataclass(frozen=True)
class TierThresholds:
    """Orange and red percentage thresholds for a single context-size tier."""

    orange_pct: int
    red_pct: int


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
            ),
            t1000k=TierThresholds(
                orange_pct=_CONTEXT_TIER_1000K_ORANGE_PCT,
                red_pct=_CONTEXT_TIER_1000K_RED_PCT,
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
    return ContextTier.RED


def is_red(used_pct: float, window_size: int, cfg: TierConfig) -> bool:
    """Return True if the given usage percentage classifies as RED.

    Convenience wrapper for callers (e.g. compact-trigger logic) that only
    care about the red/not-red boolean, not the full tier.

    Args:
        used_pct: Context usage percentage (0-100)
        window_size: Context window size in tokens (e.g. 200000, 1000000)
        cfg: Threshold configuration to classify against

    Returns:
        True if classify_context(...) resolves to ContextTier.RED
    """
    return classify_context(used_pct, window_size, cfg) is ContextTier.RED
