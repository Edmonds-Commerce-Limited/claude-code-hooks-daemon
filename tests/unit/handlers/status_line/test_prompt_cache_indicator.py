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

import pytest

from claude_code_hooks_daemon.handlers.status_line.prompt_cache_indicator import (
    PromptCacheIndicatorHandler,
)

_WARM_PAYLOAD = {
    "prompt_cache": {
        "warm": True,
        "caching_observed": True,
        "ttl": "1h",
        "expires_at": 1790079347,
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
