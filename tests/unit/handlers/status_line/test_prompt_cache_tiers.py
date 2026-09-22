"""Tests for the shared prompt-cache classifier (Plan 00452 Task 1.7).

The point of the module under test is that there is exactly ONE place where
"is this cache in trouble?" is decided. Plan 00135 Decision J established the
pattern for context tiers: the status line and the supervisor read the same
predicate, so "the bar is showing a warning" and "the supervisor should act"
can never disagree. These tests hold that line by exercising the predicates
directly rather than through either consumer.

Time is always passed in. A classifier that read the clock itself could not be
tested at a boundary, and the boundaries are the whole substance here.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.handlers.status_line.prompt_cache_tiers import (
    PromptCacheThresholds,
    PromptCacheTier,
    classify_prompt_cache,
    is_cold,
    needs_attention,
    parse_ttl_seconds,
)

_NOW = 1_790_000_000.0

_ONE_HOUR = 3600
_FIVE_MINUTES = 300


def _cache(**overrides) -> dict:
    """A warm, healthy payload — the shape Claude Code actually ships."""
    base = {
        "caching_observed": True,
        "warm": True,
        "ttl": "1h",
        "expires_at": int(_NOW) + _ONE_HOUR,
        "hit_ratio": 0.9887,
        "misses": 14,
        "recache_tokens_if_cold": 383_761,
        "last_miss_at": int(_NOW) - 86_400,
        "last_miss_cause": {"causes": ["messages_rewritten"]},
    }
    base.update(overrides)
    return base


class TestParseTtlSeconds:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1h", _ONE_HOUR),
            ("5m", _FIVE_MINUTES),
            ("30s", 30),
        ],
    )
    def test_it_parses_the_shapes_claude_code_ships(self, raw, expected):
        assert parse_ttl_seconds(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "later", 3600, True, "h", "1x"])
    def test_anything_unrecognised_is_none_not_a_guess(self, raw):
        """A wrong TTL silently mis-times every expiry decision downstream."""
        assert parse_ttl_seconds(raw) is None


class TestClassification:
    def test_a_healthy_session_is_warm(self):
        assert classify_prompt_cache(_cache(), now=_NOW).tier is PromptCacheTier.WARM

    def test_an_unwarm_cache_is_cold(self):
        state = classify_prompt_cache(_cache(warm=False), now=_NOW)
        assert state.tier is PromptCacheTier.COLD

    def test_caching_not_yet_observed_is_unknown_not_cold(self):
        """A session before any caching has happened has no state to report.

        Calling it COLD would invite action against a problem that does not
        exist — the same reason the status segment renders nothing there.
        """
        state = classify_prompt_cache(_cache(caching_observed=False), now=_NOW)
        assert state.tier is PromptCacheTier.UNKNOWN

    def test_an_absent_payload_is_unknown(self):
        assert classify_prompt_cache(None, now=_NOW).tier is PromptCacheTier.UNKNOWN

    def test_a_non_dict_payload_is_unknown(self):
        assert classify_prompt_cache("nope", now=_NOW).tier is PromptCacheTier.UNKNOWN


class TestTheExpiringBoundary:
    """The deadline is `expires_at`, so this is arithmetic, not estimation."""

    def test_just_inside_the_window_is_expiring(self):
        cfg = PromptCacheThresholds()
        window = int(_ONE_HOUR * cfg.expiring_fraction)
        state = classify_prompt_cache(_cache(expires_at=int(_NOW) + window - 1), now=_NOW, cfg=cfg)
        assert state.tier is PromptCacheTier.EXPIRING

    def test_just_outside_the_window_is_warm(self):
        cfg = PromptCacheThresholds()
        window = int(_ONE_HOUR * cfg.expiring_fraction)
        state = classify_prompt_cache(_cache(expires_at=int(_NOW) + window + 1), now=_NOW, cfg=cfg)
        assert state.tier is PromptCacheTier.WARM

    def test_the_window_scales_with_the_ttl(self):
        """A 5-minute TTL must not inherit a 1-hour TTL's 6-minute window.

        With a fixed window the entire 5m band would read as expiring for its
        whole life, which is the same as having no signal at all.
        """
        cfg = PromptCacheThresholds()
        five_m_window = int(_FIVE_MINUTES * cfg.expiring_fraction)
        assert five_m_window < _FIVE_MINUTES
        state = classify_prompt_cache(
            _cache(ttl="5m", expires_at=int(_NOW) + five_m_window + 1), now=_NOW, cfg=cfg
        )
        assert state.tier is PromptCacheTier.WARM

    def test_an_expiry_already_past_is_expiring_not_warm(self):
        state = classify_prompt_cache(_cache(expires_at=int(_NOW) - 1), now=_NOW)
        assert state.tier is PromptCacheTier.EXPIRING

    def test_an_unparseable_ttl_cannot_produce_an_expiring_verdict(self):
        """Without a TTL there is no window, and a guessed one would be wrong."""
        state = classify_prompt_cache(_cache(ttl="unknowable", expires_at=int(_NOW) + 1), now=_NOW)
        assert state.tier is PromptCacheTier.WARM

    def test_a_missing_expires_at_cannot_produce_an_expiring_verdict(self):
        state = classify_prompt_cache(_cache(expires_at=None), now=_NOW)
        assert state.tier is PromptCacheTier.WARM
        assert state.seconds_remaining is None


class TestTheRecentMissFlag:
    """Task 1.6: an invalidation has to be VISIBLE at the moment it happens."""

    def test_a_miss_inside_the_window_is_surfaced_with_its_cause(self):
        cfg = PromptCacheThresholds()
        state = classify_prompt_cache(
            _cache(last_miss_at=int(_NOW) - cfg.recent_miss_seconds + 1), now=_NOW, cfg=cfg
        )
        assert state.recent_miss_cause == "messages_rewritten"

    def test_an_old_miss_is_not_surfaced(self):
        """Every long session has old misses; reporting them would be constant noise."""
        cfg = PromptCacheThresholds()
        state = classify_prompt_cache(
            _cache(last_miss_at=int(_NOW) - cfg.recent_miss_seconds - 1), now=_NOW, cfg=cfg
        )
        assert state.recent_miss_cause is None

    def test_a_recent_miss_with_no_stated_cause_still_reports_the_miss(self):
        """The invalidation is the fact; the cause is a nicety Claude Code may omit."""
        state = classify_prompt_cache(
            _cache(last_miss_at=int(_NOW) - 1, last_miss_cause={}), now=_NOW
        )
        assert state.recent_miss is True
        assert state.recent_miss_cause is None

    def test_multiple_causes_are_all_reported(self):
        state = classify_prompt_cache(
            _cache(
                last_miss_at=int(_NOW) - 1,
                last_miss_cause={"causes": ["effort_changed", "messages_rewritten"]},
            ),
            now=_NOW,
        )
        assert state.recent_miss_cause == "effort_changed+messages_rewritten"

    def test_a_session_with_no_miss_at_all_reports_none(self):
        state = classify_prompt_cache(_cache(last_miss_at=None, misses=0), now=_NOW)
        assert state.recent_miss is False


class TestTheCarriedFigures:
    def test_the_rebuild_cost_is_carried_through(self):
        """The magnitude is what tells an operator whether to care (user's point).

        The same invalidation cost 130k tokens early in a session and 509k at
        its peak, so the tier alone does not convey seriousness.
        """
        state = classify_prompt_cache(_cache(recache_tokens_if_cold=509_000), now=_NOW)
        assert state.rebuild_tokens == 509_000

    def test_a_non_numeric_rebuild_cost_is_none_not_zero(self):
        """Zero would read as 'an invalidation is free', which is never true."""
        state = classify_prompt_cache(_cache(recache_tokens_if_cold="lots"), now=_NOW)
        assert state.rebuild_tokens is None

    def test_a_boolean_is_not_accepted_as_a_token_count(self):
        """bool is an int in Python, and True would render as 0k."""
        state = classify_prompt_cache(_cache(recache_tokens_if_cold=True), now=_NOW)
        assert state.rebuild_tokens is None

    def test_the_hit_ratio_and_ttl_are_carried_through(self):
        state = classify_prompt_cache(_cache(), now=_NOW)
        assert state.hit_ratio == pytest.approx(0.9887)
        assert state.ttl_seconds == _ONE_HOUR


class TestThePredicates:
    """The booleans a supervisor reads, so it cannot re-threshold and drift."""

    def test_is_cold_is_true_only_when_cold(self):
        assert is_cold(classify_prompt_cache(_cache(warm=False), now=_NOW)) is True
        assert is_cold(classify_prompt_cache(_cache(), now=_NOW)) is False

    def test_is_cold_is_false_for_unknown(self):
        """UNKNOWN is an absence of information, never a cold verdict."""
        state = classify_prompt_cache(_cache(caching_observed=False), now=_NOW)
        assert is_cold(state) is False

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({}, False),
            ({"warm": False}, True),
            ({"expires_at": int(_NOW) + 1}, True),
            ({"caching_observed": False}, False),
        ],
    )
    def test_needs_attention_covers_expiring_and_cold_but_not_unknown(self, overrides, expected):
        state = classify_prompt_cache(_cache(**overrides), now=_NOW)
        assert needs_attention(state) is expected

    def test_a_recent_miss_needs_attention_even_while_warm(self):
        """The cache was rebuilt moments ago: warm now, but it just cost real tokens."""
        state = classify_prompt_cache(_cache(last_miss_at=int(_NOW) - 1), now=_NOW)
        assert state.tier is PromptCacheTier.WARM
        assert needs_attention(state) is True
