"""Tests for the shared context-tier classification module.

This module is the single source of truth for "what colour/tier is this
context usage percentage in?" — shared between the status line
(ModelContextHandler) and future compact-trigger logic. Boundary values here
MUST match the historical model_context.py behaviour exactly (see
test_model_context.py for the behaviour-preservation regression suite).
"""

import dataclasses

import pytest

from claude_code_hooks_daemon.handlers.status_line.context_tiers import (
    _CONTEXT_TIER_200K_CRITICAL_PCT,
    _CONTEXT_TIER_200K_ORANGE_PCT,
    _CONTEXT_TIER_200K_RED_PCT,
    _CONTEXT_TIER_200K_SIZE,
    _CONTEXT_TIER_1000K_CRITICAL_PCT,
    _CONTEXT_TIER_1000K_ORANGE_PCT,
    _CONTEXT_TIER_1000K_RED_PCT,
    _CONTEXT_TIER_1000K_SIZE,
    ContextTier,
    TierConfig,
    TierThresholds,
    classify_context,
    compact_urgency_pct,
    is_compact_urgent,
    is_critical,
    is_red,
    resolve_tier_thresholds,
)


class TestTierThresholds:
    """Tests for the TierThresholds dataclass."""

    def test_frozen(self) -> None:
        """TierThresholds must be immutable."""
        thresholds = TierThresholds(orange_pct=51, red_pct=76)
        with pytest.raises(dataclasses.FrozenInstanceError):
            thresholds.orange_pct = 10


class TestDefaultConfig:
    """Tests that the default TierConfig matches historical constants."""

    def test_default_config_matches_200k_constants(self) -> None:
        """Default 200k tier matches the canonical module constants."""
        cfg = TierConfig.default()
        assert cfg.t200k.orange_pct == _CONTEXT_TIER_200K_ORANGE_PCT
        assert cfg.t200k.red_pct == _CONTEXT_TIER_200K_RED_PCT

    def test_default_config_matches_1000k_constants(self) -> None:
        """Default 1000k tier matches the canonical module constants."""
        cfg = TierConfig.default()
        assert cfg.t1000k.orange_pct == _CONTEXT_TIER_1000K_ORANGE_PCT
        assert cfg.t1000k.red_pct == _CONTEXT_TIER_1000K_RED_PCT

    def test_default_config_matches_critical_constants(self) -> None:
        """Default tiers carry the canonical CRITICAL thresholds (Plan 00151)."""
        cfg = TierConfig.default()
        assert cfg.t200k.critical_pct == _CONTEXT_TIER_200K_CRITICAL_PCT
        assert cfg.t1000k.critical_pct == _CONTEXT_TIER_1000K_CRITICAL_PCT


class TestResolveTierThresholds:
    """Tests for resolve_tier_thresholds."""

    def test_below_1000k_uses_200k_tier(self) -> None:
        """A window size below the 1000k threshold uses the 200k tier."""
        cfg = TierConfig.default()
        result = resolve_tier_thresholds(_CONTEXT_TIER_200K_SIZE, cfg)
        assert result == cfg.t200k

    def test_zero_window_size_uses_200k_tier(self) -> None:
        """Unknown/zero window size falls back to the 200k tier."""
        cfg = TierConfig.default()
        result = resolve_tier_thresholds(0, cfg)
        assert result == cfg.t200k

    def test_exact_1000k_uses_1000k_tier(self) -> None:
        """Window size exactly at the 1000k threshold uses the 1000k tier."""
        cfg = TierConfig.default()
        result = resolve_tier_thresholds(_CONTEXT_TIER_1000K_SIZE, cfg)
        assert result == cfg.t1000k

    def test_above_1000k_uses_1000k_tier(self) -> None:
        """A hypothetical 2M window falls back to the largest (1000k) tier."""
        cfg = TierConfig.default()
        result = resolve_tier_thresholds(2_000_000, cfg)
        assert result == cfg.t1000k

    def test_custom_config_overrides_thresholds(self) -> None:
        """Custom TierConfig values are returned, not the defaults."""
        cfg = TierConfig(
            t200k=TierThresholds(orange_pct=40, red_pct=60),
            t1000k=TierThresholds(orange_pct=20, red_pct=35),
        )
        assert resolve_tier_thresholds(_CONTEXT_TIER_200K_SIZE, cfg) == cfg.t200k
        assert resolve_tier_thresholds(_CONTEXT_TIER_1000K_SIZE, cfg) == cfg.t1000k


class TestClassifyContext200k:
    """Boundary tests for the 200k tier (orange=51, red=76, yellow=25)."""

    def test_24_percent_is_green(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(24.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.GREEN

    def test_25_percent_is_yellow(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(25.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.YELLOW

    def test_50_percent_is_yellow(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(50.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.YELLOW

    def test_51_percent_is_orange(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(51.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.ORANGE

    def test_75_percent_is_orange(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(75.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.ORANGE

    def test_76_percent_is_red(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(76.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.RED

    def test_89_percent_is_red(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(89.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.RED

    def test_90_percent_is_critical(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(90.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.CRITICAL

    def test_99_percent_is_critical(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(99.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.CRITICAL


class TestClassifyContext1000k:
    """Boundary tests for the 1000k tier (orange=30, red=40, yellow=15)."""

    def test_14_percent_is_green(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(14.0, _CONTEXT_TIER_1000K_SIZE, cfg) is ContextTier.GREEN

    def test_15_percent_is_yellow(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(15.0, _CONTEXT_TIER_1000K_SIZE, cfg) is ContextTier.YELLOW

    def test_29_percent_is_yellow(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(29.0, _CONTEXT_TIER_1000K_SIZE, cfg) is ContextTier.YELLOW

    def test_30_percent_is_orange(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(30.0, _CONTEXT_TIER_1000K_SIZE, cfg) is ContextTier.ORANGE

    def test_39_percent_is_orange(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(39.0, _CONTEXT_TIER_1000K_SIZE, cfg) is ContextTier.ORANGE

    def test_40_percent_is_red(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(40.0, _CONTEXT_TIER_1000K_SIZE, cfg) is ContextTier.RED

    def test_59_percent_is_red(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(59.0, _CONTEXT_TIER_1000K_SIZE, cfg) is ContextTier.RED

    def test_60_percent_is_critical(self) -> None:
        cfg = TierConfig.default()
        assert classify_context(60.0, _CONTEXT_TIER_1000K_SIZE, cfg) is ContextTier.CRITICAL


class TestClassifyContextConfigOverride:
    """Tests that classify_context honours a custom TierConfig."""

    def test_custom_red_pct_shifts_boundary(self) -> None:
        """A custom red_pct changes where RED begins."""
        cfg = TierConfig(
            t200k=TierThresholds(orange_pct=40, red_pct=60),
            t1000k=TierThresholds(
                orange_pct=_CONTEXT_TIER_1000K_ORANGE_PCT,
                red_pct=_CONTEXT_TIER_1000K_RED_PCT,
            ),
        )
        assert classify_context(59.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.ORANGE
        assert classify_context(60.0, _CONTEXT_TIER_200K_SIZE, cfg) is ContextTier.RED


class TestIsRed:
    """Truth table for the is_red helper."""

    def test_is_red_true_at_200k_red_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_red(76.0, _CONTEXT_TIER_200K_SIZE, cfg) is True

    def test_is_red_false_just_below_200k_red_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_red(75.0, _CONTEXT_TIER_200K_SIZE, cfg) is False

    def test_is_red_true_at_1000k_red_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_red(40.0, _CONTEXT_TIER_1000K_SIZE, cfg) is True

    def test_is_red_false_just_below_1000k_red_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_red(39.0, _CONTEXT_TIER_1000K_SIZE, cfg) is False

    def test_is_red_false_for_green(self) -> None:
        cfg = TierConfig.default()
        assert is_red(0.0, _CONTEXT_TIER_200K_SIZE, cfg) is False

    def test_is_red_with_custom_config(self) -> None:
        """is_red respects a custom TierConfig, not just defaults."""
        cfg = TierConfig(
            t200k=TierThresholds(orange_pct=40, red_pct=60),
            t1000k=TierThresholds(
                orange_pct=_CONTEXT_TIER_1000K_ORANGE_PCT,
                red_pct=_CONTEXT_TIER_1000K_RED_PCT,
            ),
        )
        assert is_red(59.0, _CONTEXT_TIER_200K_SIZE, cfg) is False
        assert is_red(60.0, _CONTEXT_TIER_200K_SIZE, cfg) is True

    def test_is_red_stays_true_in_critical_band(self) -> None:
        """CRITICAL is 'red or worse': is_red MUST remain True at/above critical.

        The sidecar's `red` flag drives the supervisor's compact trigger, so a
        critical percentage must still read as red or compaction would silently
        stop firing above the critical threshold (Plan 00151).
        """
        cfg = TierConfig.default()
        assert is_red(90.0, _CONTEXT_TIER_200K_SIZE, cfg) is True
        assert is_red(99.0, _CONTEXT_TIER_200K_SIZE, cfg) is True
        assert is_red(60.0, _CONTEXT_TIER_1000K_SIZE, cfg) is True


class TestCompactUrgencyPct:
    """The compact-urgency midpoint sits between red and critical (Plan 00152).

    The ccy supervisor treats ``[red, midpoint)`` as the *patient* red band and
    ``[midpoint, critical)`` as the *prompt* band; the midpoint is the integer
    mean of red and critical so it is a pure function of the two thresholds.
    """

    def test_200k_midpoint_is_mean_of_red_and_critical(self) -> None:
        thresholds = TierThresholds(orange_pct=51, red_pct=76, critical_pct=90)
        assert compact_urgency_pct(thresholds) == 83

    def test_1000k_midpoint_is_mean_of_red_and_critical(self) -> None:
        thresholds = TierThresholds(orange_pct=30, red_pct=40, critical_pct=60)
        assert compact_urgency_pct(thresholds) == 50

    def test_midpoint_uses_integer_division(self) -> None:
        # red=76, critical=91 -> 167 // 2 = 83 (not 83.5).
        thresholds = TierThresholds(orange_pct=51, red_pct=76, critical_pct=91)
        assert compact_urgency_pct(thresholds) == 83


class TestIsCompactUrgent:
    """Truth table for the is_compact_urgent helper (Plan 00152)."""

    def test_below_midpoint_in_red_band_is_not_urgent(self) -> None:
        cfg = TierConfig.default()
        # 76-82% at 200k is RED but below the 83% midpoint -> patient band.
        assert is_compact_urgent(76.0, _CONTEXT_TIER_200K_SIZE, cfg) is False
        assert is_compact_urgent(82.0, _CONTEXT_TIER_200K_SIZE, cfg) is False

    def test_at_midpoint_is_urgent(self) -> None:
        cfg = TierConfig.default()
        assert is_compact_urgent(83.0, _CONTEXT_TIER_200K_SIZE, cfg) is True

    def test_upper_red_band_is_urgent(self) -> None:
        cfg = TierConfig.default()
        assert is_compact_urgent(89.0, _CONTEXT_TIER_200K_SIZE, cfg) is True

    def test_critical_implies_urgent(self) -> None:
        cfg = TierConfig.default()
        assert is_compact_urgent(90.0, _CONTEXT_TIER_200K_SIZE, cfg) is True
        assert is_compact_urgent(99.0, _CONTEXT_TIER_200K_SIZE, cfg) is True

    def test_green_is_not_urgent(self) -> None:
        cfg = TierConfig.default()
        assert is_compact_urgent(0.0, _CONTEXT_TIER_200K_SIZE, cfg) is False

    def test_1000k_midpoint_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_compact_urgent(49.0, _CONTEXT_TIER_1000K_SIZE, cfg) is False
        assert is_compact_urgent(50.0, _CONTEXT_TIER_1000K_SIZE, cfg) is True

    def test_with_custom_config(self) -> None:
        # red=60, critical=80 -> midpoint 70.
        cfg = TierConfig(
            t200k=TierThresholds(orange_pct=40, red_pct=60, critical_pct=80),
            t1000k=TierThresholds(
                orange_pct=_CONTEXT_TIER_1000K_ORANGE_PCT,
                red_pct=_CONTEXT_TIER_1000K_RED_PCT,
                critical_pct=_CONTEXT_TIER_1000K_CRITICAL_PCT,
            ),
        )
        assert is_compact_urgent(69.0, _CONTEXT_TIER_200K_SIZE, cfg) is False
        assert is_compact_urgent(70.0, _CONTEXT_TIER_200K_SIZE, cfg) is True


class TestIsCritical:
    """Truth table for the is_critical helper (Plan 00151)."""

    def test_is_critical_true_at_200k_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_critical(90.0, _CONTEXT_TIER_200K_SIZE, cfg) is True

    def test_is_critical_false_just_below_200k_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_critical(89.0, _CONTEXT_TIER_200K_SIZE, cfg) is False

    def test_is_critical_true_at_1000k_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_critical(60.0, _CONTEXT_TIER_1000K_SIZE, cfg) is True

    def test_is_critical_false_just_below_1000k_boundary(self) -> None:
        cfg = TierConfig.default()
        assert is_critical(59.0, _CONTEXT_TIER_1000K_SIZE, cfg) is False

    def test_is_critical_false_in_red_band(self) -> None:
        cfg = TierConfig.default()
        assert is_critical(80.0, _CONTEXT_TIER_200K_SIZE, cfg) is False

    def test_is_critical_false_for_green(self) -> None:
        cfg = TierConfig.default()
        assert is_critical(0.0, _CONTEXT_TIER_200K_SIZE, cfg) is False

    def test_is_critical_with_custom_config(self) -> None:
        """is_critical respects a custom critical_pct."""
        cfg = TierConfig(
            t200k=TierThresholds(orange_pct=40, red_pct=60, critical_pct=80),
            t1000k=TierThresholds(
                orange_pct=_CONTEXT_TIER_1000K_ORANGE_PCT,
                red_pct=_CONTEXT_TIER_1000K_RED_PCT,
                critical_pct=_CONTEXT_TIER_1000K_CRITICAL_PCT,
            ),
        )
        assert is_critical(79.0, _CONTEXT_TIER_200K_SIZE, cfg) is False
        assert is_critical(80.0, _CONTEXT_TIER_200K_SIZE, cfg) is True
