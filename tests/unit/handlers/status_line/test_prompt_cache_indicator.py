"""Tests for PromptCacheIndicatorHandler (Plan 00452).

The Status payload already carries a `prompt_cache` object computed by the
harness — `warm`, `ttl`, `expires_at`, `hit_ratio`, `misses`, `miss_causes`
and `recache_tokens_if_cold`. This segment surfaces it, because no project
can currently see its own cache hit ratio and so none knows whether it has a
problem.

Two behaviours carry most of the value and both are pinned below. A COLD cache
is shown with what going cold actually costs (`recache_tokens_if_cold`),
because the seriousness of an invalidation scales with the prefix and nothing
else tells you the magnitude. And a payload with no `prompt_cache` key renders
NOTHING rather than a zero: older Claude Code versions do not send the field,
and a segment reading "0%" on a healthy session is worse than an absent one.
"""

import time

import pytest

from claude_code_hooks_daemon.handlers.status_line.prompt_cache_indicator import (
    PromptCacheIndicatorHandler,
)

_ONE_HOUR = 3600

#: Expiries are relative to NOW on purpose. The classifier compares
#: `expires_at` against the wall clock, so a hard-coded timestamp would drift
#: into the past and silently turn every "warm" fixture into an expiring one.
_WARM_PAYLOAD = {
    "prompt_cache": {
        "warm": True,
        "caching_observed": True,
        "ttl": "1h",
        "expires_at": int(time.time()) + _ONE_HOUR,
        "requests": 4610,
        "misses": 14,
        "hit_ratio": 0.9912764873518866,
        "miss_causes": {"effort_changed": 2, "messages_rewritten": 12},
        "recache_tokens_if_cold": 383761,
    }
}

_COLD_PAYLOAD = {
    "prompt_cache": {
        "warm": False,
        "caching_observed": True,
        "ttl": "5m",
        "hit_ratio": 0.6217,
        "requests": 12,
        "misses": 5,
        "recache_tokens_if_cold": 302080,
    }
}


class TestPromptCacheIndicatorHandler:
    @pytest.fixture
    def handler(self):
        return PromptCacheIndicatorHandler()

    def test_init_sets_correct_name(self, handler):
        assert handler.name == "status-prompt-cache-indicator"

    def test_init_is_not_terminal(self, handler):
        assert handler.terminal is False

    def test_matches_any_status_render(self, handler):
        assert handler.matches({}) is True

    # --- rendering ---

    def test_warm_cache_shows_hit_ratio_as_a_percentage(self, handler):
        segment = handler.handle(_WARM_PAYLOAD).context[0]
        assert "99%" in segment

    def test_warm_cache_shows_the_ttl_in_force(self, handler):
        """Main and sub-agents run DIFFERENT TTLs, so the figure must be shown."""
        assert "1h" in handler.handle(_WARM_PAYLOAD).context[0]

    def test_a_warm_cache_carries_no_warning_marker(self, handler):
        assert "⚠" not in handler.handle(_WARM_PAYLOAD).context[0]

    def test_a_cold_cache_is_flagged_visually(self, handler):
        """The visual warning the owner asked for: something invalidated it."""
        assert "⚠" in handler.handle(_COLD_PAYLOAD).context[0]

    def test_a_cold_cache_reports_what_a_rebuild_costs(self, handler):
        """Seriousness scales with the prefix, so show the magnitude, not just the state."""
        segment = handler.handle(_COLD_PAYLOAD).context[0]
        assert "302k" in segment

    def test_a_cold_cache_shows_its_own_ttl(self, handler):
        assert "5m" in handler.handle(_COLD_PAYLOAD).context[0]

    # --- degradation: absent or partial data must never render a lie ---

    def test_a_payload_without_prompt_cache_renders_nothing(self, handler):
        """Older Claude Code does not send the field. `0%` would be a lie."""
        assert handler.handle({}).context == []

    def test_a_null_prompt_cache_renders_nothing(self, handler):
        assert handler.handle({"prompt_cache": None}).context == []

    def test_caching_not_observed_yet_renders_nothing(self, handler):
        """Before any caching happens a ratio is meaningless, not zero."""
        payload = {"prompt_cache": {"caching_observed": False, "warm": False}}
        assert handler.handle(payload).context == []

    def test_a_missing_hit_ratio_does_not_raise(self, handler):
        payload = {"prompt_cache": {"caching_observed": True, "warm": True, "ttl": "1h"}}
        handler.handle(payload)

    def test_a_non_numeric_hit_ratio_does_not_raise(self, handler):
        payload = {
            "prompt_cache": {"caching_observed": True, "warm": True, "hit_ratio": "nonsense"}
        }
        handler.handle(payload)

    def test_a_missing_recache_figure_still_flags_cold(self, handler):
        """The warning matters more than the magnitude; never drop it for lack of a number."""
        payload = {"prompt_cache": {"caching_observed": True, "warm": False, "hit_ratio": 0.5}}
        assert "⚠" in handler.handle(payload).context[0]

    # --- the expiring band and the invalidation flag (Tasks 1.6, 1.7) ---

    def test_a_cache_inside_the_tail_of_its_ttl_is_flagged_as_expiring(self, handler):
        """This is the band where acting is still CHEAP, so it has to be visible."""
        payload = {
            "prompt_cache": {
                "caching_observed": True,
                "warm": True,
                "ttl": "1h",
                "expires_at": int(time.time()) + 60,
                "hit_ratio": 0.99,
            }
        }
        assert "EXPIRING" in handler.handle(payload).context[0]

    def test_an_expiring_cache_is_not_also_reported_as_cold(self, handler):
        """Alive-but-nearly-expired and already-gone are different situations."""
        payload = {
            "prompt_cache": {
                "caching_observed": True,
                "warm": True,
                "ttl": "1h",
                "expires_at": int(time.time()) + 60,
                "hit_ratio": 0.99,
            }
        }
        assert "COLD" not in handler.handle(payload).context[0]

    def test_a_recent_invalidation_is_flagged_with_its_cause(self, handler):
        """The user's requirement: a visual warning when something invalidates the cache."""
        payload = {
            "prompt_cache": {
                "caching_observed": True,
                "warm": True,
                "ttl": "1h",
                "expires_at": int(time.time()) + _ONE_HOUR,
                "hit_ratio": 0.99,
                "last_miss_at": int(time.time()) - 5,
                "last_miss_cause": {"causes": ["messages_rewritten"]},
            }
        }
        segment = handler.handle(payload).context[0]
        assert "INVALIDATED" in segment
        assert "messages_rewritten" in segment

    def test_an_old_invalidation_is_not_flagged(self, handler):
        """Every long session has old misses; a permanent warning would be ignored."""
        payload = {
            "prompt_cache": {
                "caching_observed": True,
                "warm": True,
                "ttl": "1h",
                "expires_at": int(time.time()) + _ONE_HOUR,
                "hit_ratio": 0.99,
                "last_miss_at": int(time.time()) - 86_400,
                "last_miss_cause": {"causes": ["messages_rewritten"]},
            }
        }
        assert "INVALIDATED" not in handler.handle(payload).context[0]

    # --- the guard on the guard ---

    def test_the_fixtures_actually_differ(self):
        """A warm/cold pair that rendered identically would pass every test above."""
        handler = PromptCacheIndicatorHandler()
        assert handler.handle(_WARM_PAYLOAD).context != handler.handle(_COLD_PAYLOAD).context

    def test_handle_sets_no_guidance_or_reason(self, handler):
        result = handler.handle(_WARM_PAYLOAD)
        assert result.guidance is None
        assert result.reason is None

    def test_explain_segment_reports_a_current_value(self, handler):
        explanation = handler.explain_segment()
        assert explanation.name
        assert explanation.current_value


class TestTheSubAgentHalf:
    """Sub-agents have no status line, so this bar is the only place they show.

    Measured in this project, the two halves diverge sharply — 98.87% main
    against 62.17% on a short sub-agent — so a MAIN-only segment reports a
    healthy session while the expensive half stays invisible.
    """

    @pytest.fixture
    def handler(self):
        return PromptCacheIndicatorHandler()

    def test_sub_totals_are_rendered_when_agents_have_run(self, handler, tmp_path, monkeypatch):
        from claude_code_hooks_daemon.handlers.status_line import prompt_cache_indicator

        monkeypatch.setattr(
            prompt_cache_indicator,
            "read_subagent_cache_totals",
            lambda session_id, root=None: {
                "agents_seen": 3,
                "cache_read_tokens": 900,
                "cache_write_tokens": 100,
            },
        )
        segment = handler.handle({**_WARM_PAYLOAD, "session_id": "s"}).context[0]
        assert "sub" in segment.lower()
        assert "90%" in segment

    def test_no_sub_agents_adds_nothing(self, handler, monkeypatch):
        """A session that spawned none must not carry an empty or 0% sub figure."""
        from claude_code_hooks_daemon.handlers.status_line import prompt_cache_indicator

        monkeypatch.setattr(
            prompt_cache_indicator,
            "read_subagent_cache_totals",
            lambda session_id, root=None: {
                "agents_seen": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            },
        )
        segment = handler.handle({**_WARM_PAYLOAD, "session_id": "s"}).context[0]
        assert "sub" not in segment.lower()

    def test_a_failing_sub_read_does_not_break_the_main_figure(self, handler, monkeypatch):
        """The MAIN half must survive anything the sub-agent sidecar does."""
        from claude_code_hooks_daemon.handlers.status_line import prompt_cache_indicator

        def _boom(session_id, root=None):
            raise OSError("sidecar unreadable")

        monkeypatch.setattr(prompt_cache_indicator, "read_subagent_cache_totals", _boom)
        segment = handler.handle({**_WARM_PAYLOAD, "session_id": "s"}).context[0]
        assert "99%" in segment


#: Main: hit_ratio 0.9 over 100 written tokens, so 900 were read.
_MAIN_90_PAYLOAD = {
    "session_id": "s",
    "prompt_cache": {
        "warm": True,
        "caching_observed": True,
        "ttl": "1h",
        "expires_at": int(time.time()) + _ONE_HOUR,
        "hit_ratio": 0.9,
        "cache_write_tokens": 100,
    },
}

#: Sub: 100 read, 300 written, so 25%. Token-weighted with main that is
#: 1000 / 1400 = 71%, while averaging the two percentages would give 57.5%.
_SUB_25_TOTALS = {
    "agents_seen": 2,
    "cache_read_tokens": 100,
    "cache_write_tokens": 300,
    "ttl_5m_write_tokens": 300,
    "ttl_1h_write_tokens": 0,
}


class TestTheSessionTotal:
    """MAIN, SUB and TOTAL: the plan's first finding, and the owner's request.

    `hit_ratio` on the payload is TOKEN-weighted, read / (read + write).
    Checked against this project's own transcript: 0.991145 from the payload
    against 0.991149 from summing the transcript, where a request-based ratio
    would read 0.9969. That is what makes main's read tokens recoverable from
    `hit_ratio` and `cache_write_tokens`, and so a true session total possible.
    """

    @pytest.fixture
    def handler(self):
        return PromptCacheIndicatorHandler()

    @staticmethod
    def _sub(monkeypatch, totals):
        from claude_code_hooks_daemon.handlers.status_line import prompt_cache_indicator

        monkeypatch.setattr(
            prompt_cache_indicator,
            "read_subagent_cache_totals",
            lambda session_id, root=None: totals,
        )

    def test_the_total_is_weighted_by_tokens_not_averaged(self, handler, monkeypatch):
        self._sub(monkeypatch, _SUB_25_TOTALS)
        segment = handler.handle(_MAIN_90_PAYLOAD).context[0]
        assert "total 71%" in segment

    def test_all_three_values_appear_in_order(self, handler, monkeypatch):
        self._sub(monkeypatch, _SUB_25_TOTALS)
        segment = handler.handle(_MAIN_90_PAYLOAD).context[0]
        assert segment.index("90%") < segment.index("sub 25%") < segment.index("total 71%")

    def test_the_sub_side_shows_its_own_ttl(self, handler, monkeypatch):
        """The halves run different TTLs, so one indicator would be wrong for one of them."""
        self._sub(monkeypatch, _SUB_25_TOTALS)
        segment = handler.handle(_MAIN_90_PAYLOAD).context[0]
        assert "sub 25% 5m" in segment

    def test_a_sub_side_on_the_1h_ttl_says_so(self, handler, monkeypatch):
        self._sub(
            monkeypatch, {**_SUB_25_TOTALS, "ttl_5m_write_tokens": 0, "ttl_1h_write_tokens": 300}
        )
        segment = handler.handle(_MAIN_90_PAYLOAD).context[0]
        assert "sub 25% 1h" in segment

    def test_a_sub_side_that_wrote_under_both_ttls_shows_both(self, handler, monkeypatch):
        """Possible when the sub-agent TTL setting changes mid-session."""
        self._sub(
            monkeypatch, {**_SUB_25_TOTALS, "ttl_5m_write_tokens": 200, "ttl_1h_write_tokens": 100}
        )
        segment = handler.handle(_MAIN_90_PAYLOAD).context[0]
        assert "sub 25% 5m+1h" in segment

    def test_a_sub_side_with_no_ttl_split_shows_no_ttl(self, handler, monkeypatch):
        self._sub(
            monkeypatch, {**_SUB_25_TOTALS, "ttl_5m_write_tokens": 0, "ttl_1h_write_tokens": 0}
        )
        segment = handler.handle(_MAIN_90_PAYLOAD).context[0]
        assert "sub 25%" in segment
        assert "sub 25% 5m" not in segment
        assert "sub 25% 1h" not in segment

    def test_no_sub_agents_means_no_total(self, handler, monkeypatch):
        """With no sub-agents the total IS the main figure; repeating it is noise."""
        self._sub(monkeypatch, {**_SUB_25_TOTALS, "agents_seen": 0})
        segment = handler.handle(_MAIN_90_PAYLOAD).context[0]
        assert "total" not in segment
        assert "90%" in segment

    def test_no_main_write_count_means_no_total_but_sub_still_shows(self, handler, monkeypatch):
        """Without `cache_write_tokens` main's reads cannot be recovered; guessing is worse."""
        self._sub(monkeypatch, _SUB_25_TOTALS)
        payload = {
            **_MAIN_90_PAYLOAD,
            "prompt_cache": {
                k: v
                for k, v in _MAIN_90_PAYLOAD["prompt_cache"].items()
                if k != "cache_write_tokens"
            },
        }
        segment = handler.handle(payload).context[0]
        assert "total" not in segment
        assert "sub 25%" in segment

    def test_a_perfect_main_ratio_with_no_writes_means_no_total(self, handler, monkeypatch):
        """1.0 over zero writes says nothing about how many tokens were read."""
        self._sub(monkeypatch, _SUB_25_TOTALS)
        payload = {
            **_MAIN_90_PAYLOAD,
            "prompt_cache": {
                **_MAIN_90_PAYLOAD["prompt_cache"],
                "hit_ratio": 1.0,
                "cache_write_tokens": 0,
            },
        }
        segment = handler.handle(payload).context[0]
        assert "total" not in segment

    def test_a_zero_main_ratio_still_totals(self, handler, monkeypatch):
        """0.0 means main read nothing, which is a known quantity, not a missing one.

        100 sub reads over 0 + 100 main and 100 + 300 sub tokens: 20%.
        """
        self._sub(monkeypatch, _SUB_25_TOTALS)
        payload = {
            **_MAIN_90_PAYLOAD,
            "prompt_cache": {**_MAIN_90_PAYLOAD["prompt_cache"], "hit_ratio": 0.0},
        }
        segment = handler.handle(payload).context[0]
        assert "total 20%" in segment
