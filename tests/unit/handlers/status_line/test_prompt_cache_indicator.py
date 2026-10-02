"""Tests for PromptCacheIndicatorHandler (Plan 00452), the compact-chip design.

The Status payload already carries a `prompt_cache` object computed by the
harness. The segment renders it as background-coloured chips after a `⚡`
icon: `main`, then `⑂` (sub-agents) and `Σ` (whole session) once a sub-agent
has run. A chip is its label alone while green; otherwise it adds the figures.

Two behaviours carry most of the value and both are pinned below. A COLD cache
is a red `❄` chip with what the rebuild costs, because the seriousness of an
invalidation scales with the prefix. And a payload with no `prompt_cache` key
renders NOTHING rather than a zero: a segment reading "0%" on a healthy
session is worse than an absent one.
"""

import re
import time
from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.status_line import prompt_cache_indicator
from claude_code_hooks_daemon.handlers.status_line.prompt_cache_indicator import (
    PromptCacheIndicatorHandler,
)

_ONE_HOUR = 3600

_RESET = "\033[0m"
_GREEN = "\033[42m\033[30m"
_YELLOW = "\033[43m\033[30m"
_ORANGE = "\033[48;5;208m\033[30m"
_RED = "\033[41m\033[97m"
_ANSI = re.compile(r"\033\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _payload(**overrides: Any) -> dict[str, Any]:
    """A healthy 1h payload, with `prompt_cache` fields overridden.

    Expiries are relative to NOW: the classifier compares `expires_at` against
    the wall clock, so a hard-coded timestamp would drift into the past and
    silently turn every warm fixture into an expiring one.
    """
    cache: dict[str, Any] = {
        "warm": True,
        "caching_observed": True,
        "ttl": "1h",
        "expires_at": int(time.time()) + _ONE_HOUR,
        "requests": 4610,
        "misses": 14,
        "hit_ratio": 0.9912764873518866,
        "cache_write_tokens": 100,
        "recache_tokens_if_cold": 383761,
    }
    cache.update(overrides)
    return {"session_id": "s", "prompt_cache": cache}


def _no_sub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        prompt_cache_indicator,
        "read_subagent_cache_totals",
        lambda session_id, root=None: {"agents_seen": 0},
    )


def _sub(monkeypatch: pytest.MonkeyPatch, **totals: int) -> None:
    merged = {
        "agents_seen": 2,
        "cache_read_tokens": 900,
        "cache_write_tokens": 100,
        "ttl_5m_write_tokens": 100,
        "ttl_1h_write_tokens": 0,
        **totals,
    }
    monkeypatch.setattr(
        prompt_cache_indicator,
        "read_subagent_cache_totals",
        lambda session_id, root=None: merged,
    )


@pytest.fixture
def handler() -> PromptCacheIndicatorHandler:
    return PromptCacheIndicatorHandler()


@pytest.fixture(autouse=True)
def _default_no_sub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test off the real sidecar unless it asks for sub-agents."""
    _no_sub(monkeypatch)


def _render(handler: PromptCacheIndicatorHandler, payload: dict[str, Any]) -> str:
    return handler.handle(payload).context[0]


class TestBasics:
    def test_init_sets_correct_name(self, handler: PromptCacheIndicatorHandler) -> None:
        assert handler.name == "status-prompt-cache-indicator"

    def test_init_is_not_terminal(self, handler: PromptCacheIndicatorHandler) -> None:
        assert handler.terminal is False

    def test_matches_any_status_render(self, handler: PromptCacheIndicatorHandler) -> None:
        assert handler.matches({}) is True

    def test_handle_sets_no_guidance_or_reason(self, handler: PromptCacheIndicatorHandler) -> None:
        result = handler.handle(_payload())
        assert result.guidance is None
        assert result.reason is None

    def test_explain_segment_reports_a_current_value(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        explanation = handler.explain_segment()
        assert explanation.name
        assert explanation.current_value

    def test_explain_segment_lists_every_glyph(self, handler: PromptCacheIndicatorHandler) -> None:
        explanation = handler.explain_segment()
        for glyph in ("⚡", "⑂", "Σ", "❄", "⏳", "↻"):
            assert glyph in explanation.glyphs

    def test_explain_segment_states_the_thresholds(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        how = handler.explain_segment().how_to_read
        assert "90%" in how
        assert "75%" in how
        assert "50%" in how


class TestHealthyMainOnly:
    def test_a_healthy_main_only_session_is_a_green_label_chip(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        assert _render(handler, _payload()) == f"| ⚡ {_GREEN}main{_RESET}"

    def test_plain_text_is_the_icon_and_label(self, handler: PromptCacheIndicatorHandler) -> None:
        assert _plain(_render(handler, _payload())) == "| ⚡ main"

    def test_a_healthy_chip_carries_no_percentage_or_ttl(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        plain = _plain(_render(handler, _payload()))
        assert "%" not in plain
        assert "1h" not in plain

    def test_a_missing_hit_ratio_is_a_green_label_and_does_not_raise(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = {"prompt_cache": {"caching_observed": True, "warm": True, "ttl": "1h"}}
        assert _plain(_render(handler, payload)) == "| ⚡ main"

    def test_a_non_numeric_hit_ratio_does_not_raise(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = {
            "prompt_cache": {"caching_observed": True, "warm": True, "hit_ratio": "nonsense"}
        }
        assert _plain(_render(handler, payload)) == "| ⚡ main"


class TestRatioBands:
    @pytest.mark.parametrize(
        ("ratio", "colour"),
        [
            (1.0, _GREEN),
            (0.9, _GREEN),
            (0.899, _YELLOW),
            (0.75, _YELLOW),
            (0.749, _ORANGE),
            (0.5, _ORANGE),
            (0.499, _RED),
            (0.0, _RED),
        ],
    )
    def test_the_main_chip_colour_follows_the_ratio(
        self, handler: PromptCacheIndicatorHandler, ratio: float, colour: str
    ) -> None:
        assert _render(handler, _payload(hit_ratio=ratio)).startswith(f"| ⚡ {colour}main")

    def test_a_non_green_chip_shows_ratio_and_ttl(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        assert _plain(_render(handler, _payload(hit_ratio=0.82))) == "| ⚡ main 82% 1h"

    def test_the_displayed_percentage_rounds_down(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        """89.6% must not read as 90%, which is the green threshold."""
        assert "main 89% 1h" in _plain(_render(handler, _payload(hit_ratio=0.896)))

    def test_a_non_green_chip_without_a_ttl_omits_it(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(hit_ratio=0.6)
        del payload["prompt_cache"]["ttl"]
        assert _plain(_render(handler, payload)) == "| ⚡ main 60%"

    def test_the_thresholds_are_options(self, handler: PromptCacheIndicatorHandler) -> None:
        handler._healthy_pct = 95
        handler._warn_pct = 80
        handler._critical_pct = 60
        assert _render(handler, _payload(hit_ratio=0.93)).startswith(f"| ⚡ {_YELLOW}")
        assert _render(handler, _payload(hit_ratio=0.7)).startswith(f"| ⚡ {_ORANGE}")
        assert _render(handler, _payload(hit_ratio=0.55)).startswith(f"| ⚡ {_RED}")


class TestStateOverrides:
    def test_a_cold_cache_is_a_red_chip_with_the_rebuild_cost(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(warm=False, recache_tokens_if_cold=509_000)
        assert _render(handler, payload) == f"| ⚡ {_RED}❄ 509k{_RESET}"

    def test_a_cold_cache_beats_a_perfect_ratio(self, handler: PromptCacheIndicatorHandler) -> None:
        payload = _payload(warm=False, hit_ratio=0.99)
        assert _render(handler, payload).startswith(f"| ⚡ {_RED}")

    def test_a_cold_cache_without_a_rebuild_figure_is_a_bare_snowflake(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        """The warning matters more than the magnitude; never drop it for lack of a number."""
        payload = _payload(warm=False)
        del payload["prompt_cache"]["recache_tokens_if_cold"]
        assert _render(handler, payload) == f"| ⚡ {_RED}❄{_RESET}"

    def test_an_expiring_cache_is_yellow_with_the_countdown(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(hit_ratio=0.99, expires_at=int(time.time()) + 4 * 60 - 5)
        # 4m window is below the 10% tail of a 1h TTL only when under 360s.
        assert _render(handler, payload).startswith(f"| ⚡ {_YELLOW}main 99% ⏳3m")

    def test_an_expiring_cache_is_not_also_reported_as_cold(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(expires_at=int(time.time()) + 60)
        assert "❄" not in _render(handler, payload)

    def test_an_expiring_countdown_under_a_minute_is_in_seconds(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(hit_ratio=0.99, expires_at=int(time.time()) + 31)
        assert re.search(r"⏳(2\d|3\d)s", _plain(_render(handler, payload)))

    def test_an_expiring_cache_with_a_bad_ratio_keeps_the_worse_ratio_colour(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(hit_ratio=0.6, expires_at=int(time.time()) + 60)
        rendered = _render(handler, payload)
        assert rendered.startswith(f"| ⚡ {_ORANGE}main 60% ⏳")

    def test_a_recent_invalidation_is_yellow_with_its_cause(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(
            hit_ratio=0.99,
            last_miss_at=int(time.time()) - 5,
            last_miss_cause={"causes": ["messages_rewritten"]},
        )
        assert _render(handler, payload) == (f"| ⚡ {_YELLOW}main 99% ↻ messages_rewritten{_RESET}")

    def test_a_recent_invalidation_without_a_cause_omits_it(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(hit_ratio=0.99, last_miss_at=int(time.time()) - 5)
        assert _render(handler, payload) == f"| ⚡ {_YELLOW}main 99% ↻{_RESET}"

    def test_an_old_invalidation_is_not_flagged(self, handler: PromptCacheIndicatorHandler) -> None:
        """Every long session has old misses; a permanent warning would be ignored."""
        payload = _payload(
            last_miss_at=int(time.time()) - 86_400,
            last_miss_cause={"causes": ["messages_rewritten"]},
        )
        assert _plain(_render(handler, payload)) == "| ⚡ main"

    def test_an_invalidation_with_a_bad_ratio_keeps_the_worse_colour(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(hit_ratio=0.3, last_miss_at=int(time.time()) - 5)
        assert _render(handler, payload).startswith(f"| ⚡ {_RED}main 30% ↻")

    def test_expiring_and_invalidated_show_both_details(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = _payload(
            hit_ratio=0.99,
            expires_at=int(time.time()) + 125,
            last_miss_at=int(time.time()) - 5,
            last_miss_cause={"causes": ["effort_changed"]},
        )
        assert "main 99% ⏳2m ↻ effort_changed" in _plain(_render(handler, payload))

    def test_the_fixtures_actually_differ(self, handler: PromptCacheIndicatorHandler) -> None:
        """A warm/cold pair that rendered identically would pass every test above."""
        assert _render(handler, _payload()) != _render(handler, _payload(warm=False))


class TestAbsence:
    def test_a_payload_without_prompt_cache_renders_nothing(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        assert handler.handle({}).context == []

    def test_a_null_prompt_cache_renders_nothing(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        assert handler.handle({"prompt_cache": None}).context == []

    def test_caching_not_observed_yet_renders_nothing(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        payload = {"prompt_cache": {"caching_observed": False, "warm": False}}
        assert handler.handle(payload).context == []


class TestTheSubAgentChips:
    """Sub-agents have no status line, so this bar is the only place they show."""

    def test_all_healthy_with_sub_agents_is_three_green_label_chips(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # main 0.9 over 100 written = 900 read; sub 900/100; total 1800/200 = 90%.
        _sub(monkeypatch)
        rendered = _render(handler, _payload(hit_ratio=0.9))
        assert rendered == (f"| ⚡ {_GREEN}main{_RESET}|{_GREEN}⑂{_RESET}|{_GREEN}Σ{_RESET}")

    def test_no_sub_agents_adds_no_sub_or_total_chip(
        self, handler: PromptCacheIndicatorHandler
    ) -> None:
        plain = _plain(_render(handler, _payload()))
        assert "⑂" not in plain
        assert "Σ" not in plain

    def test_a_degraded_sub_chip_shows_ratio_and_its_own_ttl(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sub(monkeypatch, cache_read_tokens=620, cache_write_tokens=380, ttl_5m_write_tokens=380)
        rendered = _render(handler, _payload(hit_ratio=0.99))
        assert f"{_ORANGE}⑂ 62% 5m{_RESET}" in rendered
        assert rendered.startswith(f"| ⚡ {_GREEN}main{_RESET}|")

    def test_the_sub_ttl_can_be_1h_or_both(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sub(
            monkeypatch,
            cache_read_tokens=100,
            cache_write_tokens=300,
            ttl_5m_write_tokens=0,
            ttl_1h_write_tokens=300,
        )
        assert "⑂ 25% 1h" in _plain(_render(handler, _payload()))
        _sub(
            monkeypatch,
            cache_read_tokens=100,
            cache_write_tokens=300,
            ttl_5m_write_tokens=200,
            ttl_1h_write_tokens=100,
        )
        assert "⑂ 25% 5m+1h" in _plain(_render(handler, _payload()))

    def test_a_sub_side_with_no_ttl_split_shows_no_ttl(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sub(
            monkeypatch,
            cache_read_tokens=100,
            cache_write_tokens=300,
            ttl_5m_write_tokens=0,
            ttl_1h_write_tokens=0,
        )
        plain = _plain(_render(handler, _payload()))
        assert "⑂ 25%" in plain
        assert "⑂ 25% 5m" not in plain

    def test_the_total_is_weighted_by_tokens_not_averaged(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Main 90% over 100 written, sub 100/300: 1000/1400 = 71%, not 57.5%."""
        _sub(monkeypatch, cache_read_tokens=100, cache_write_tokens=300)
        rendered = _render(handler, _payload(hit_ratio=0.9))
        assert f"{_ORANGE}Σ 71%{_RESET}" in rendered

    def test_chips_are_joined_by_an_uncoloured_separator(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sub(monkeypatch)
        assert f"{_RESET}|{_GREEN}⑂" in _render(handler, _payload(hit_ratio=0.9))

    def test_no_main_write_count_means_no_total_but_sub_still_shows(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without `cache_write_tokens` main's reads cannot be recovered; guessing is worse."""
        _sub(monkeypatch)
        payload = _payload(hit_ratio=0.9)
        del payload["prompt_cache"]["cache_write_tokens"]
        plain = _plain(_render(handler, payload))
        assert "⑂" in plain
        assert "Σ" not in plain

    def test_a_perfect_main_ratio_with_no_writes_means_no_total(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """1.0 over zero writes says nothing about how many tokens were read."""
        _sub(monkeypatch)
        payload = _payload(hit_ratio=1.0, cache_write_tokens=0)
        assert "Σ" not in _plain(_render(handler, payload))

    def test_a_zero_main_ratio_still_totals(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """0.0 means main read nothing, a known quantity: 100 over 0+100 and 100+300 is 20%."""
        _sub(monkeypatch, cache_read_tokens=100, cache_write_tokens=300)
        payload = _payload(hit_ratio=0.0)
        assert "Σ 20%" in _plain(_render(handler, payload))

    def test_a_sub_agent_with_no_tokens_adds_no_chips(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sub(monkeypatch, cache_read_tokens=0, cache_write_tokens=0)
        assert "⑂" not in _plain(_render(handler, _payload()))

    def test_a_failing_sub_read_does_not_break_the_main_chip(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The MAIN chip must survive anything the sub-agent sidecar does."""

        def _boom(session_id: str, root: object = None) -> dict[str, int]:
            raise OSError("sidecar unreadable")

        monkeypatch.setattr(prompt_cache_indicator, "read_subagent_cache_totals", _boom)
        assert _render(handler, _payload(hit_ratio=0.82)).startswith(f"| ⚡ {_YELLOW}main 82%")

    def test_a_cold_main_still_lets_the_sub_chips_render(
        self, handler: PromptCacheIndicatorHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sub(monkeypatch)
        plain = _plain(_render(handler, _payload(warm=False, recache_tokens_if_cold=130_000)))
        assert plain.startswith("| ⚡ ❄ 130k|⑂")
