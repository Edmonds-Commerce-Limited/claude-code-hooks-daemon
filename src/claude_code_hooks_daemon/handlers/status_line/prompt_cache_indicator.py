"""Surface the session's prompt-cache state in the status line (Plan 00452).

Input tokens bill at roughly 0.1x when the cached prefix is reused and at a
write rate whenever it has to be rebuilt, so the hit ratio is one of the
largest levers on what a session costs. **No project could see it**, which is
the problem this segment exists to fix: a session cannot introspect its own
usage (the `usage` object lives in the API RESPONSE, which never reaches the
model), so nothing inside a session knows whether it has a caching problem.

The figures are NOT derived here. Claude Code already computes them and ships
them on the Status payload as `prompt_cache`:

    warm, caching_observed, ttl, expires_at, requests, misses,
    hit_ratio, miss_causes, last_miss_cause, recache_tokens_if_cold

An earlier design for this segment parsed the session transcript for the same
numbers. That was abandoned once the payload was captured and read: the
transcript is tens of megabytes, the status line re-renders constantly, and
every figure wanted was already present and pre-computed. Reading the payload
is both cheaper and closer to the source of truth.

**Two deliberate choices about what NOT to show.**

Absence renders nothing rather than zero. A Claude Code that does not send
`prompt_cache`, or a session before any caching has been observed, has no
ratio — and a segment reading `0%` on a perfectly healthy session is worse
than an absent one, because it invites action against a problem that does not
exist. Same reasoning as `caching_observed` being checked separately from
`warm`.

A COLD cache reports what the rebuild costs, not just that it is cold. The
seriousness of an invalidation scales with the prefix — measured in this
project, the same event cost 130k tokens early in a session and 509k at its
peak — so the state alone does not tell an operator whether to care.
`recache_tokens_if_cold` is that magnitude, already computed.
"""

import time
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
from claude_code_hooks_daemon.handlers.status_line.prompt_cache_tiers import (
    PromptCacheState,
    PromptCacheTier,
    classify_prompt_cache,
)
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_cache_aggregator import (
    read_subagent_cache_totals,
)

#: Payload key carrying the harness-computed cache state.
_PROMPT_CACHE_KEY = "prompt_cache"

#: Divisor for rendering a token count as a compact "384k".
_TOKENS_PER_K = 1000

#: Below this many seconds remaining, the countdown renders in seconds.
_SECONDS_PER_MINUTE = 60


def _as_ratio(raw: object) -> float | None:
    """`hit_ratio` as a float, or None when it is absent or not a number.

    Tolerant on purpose: this segment renders on every status line, and a
    surprising payload must cost a missing segment rather than a broken status
    line for the whole session.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _compact_tokens(raw: object) -> str | None:
    """A token count as `384k`, or None when it is absent or not a number."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return f"{int(raw) // _TOKENS_PER_K}k"


def _compact_duration(seconds: int) -> str:
    """A countdown as `4m` or `45s`, clamped at zero.

    An expiry already in the past renders `0s` rather than a negative: the
    cache is about to be rebuilt either way, and a minus sign on a status bar
    reads as a bug rather than as urgency.
    """
    remaining = max(seconds, 0)
    if remaining >= _SECONDS_PER_MINUTE:
        return f"{remaining // _SECONDS_PER_MINUTE}m"
    return f"{remaining}s"


def _sub_ttl(totals: dict[str, int]) -> str:
    """The TTL(s) the sub-agents actually wrote under: `5m`, `1h`, `5m+1h` or empty.

    Read from what was written rather than from configuration, because the
    configured value can be invalid and silently ignored. Both appear when the
    sub-agent TTL setting changed mid-session.
    """
    ttls = [
        label
        for label, key in (("5m", "ttl_5m_write_tokens"), ("1h", "ttl_1h_write_tokens"))
        if (_as_ratio(totals.get(key)) or 0.0) > 0
    ]
    return "+".join(ttls)


def _main_read_and_written(cache: object, hit_ratio: float | None) -> tuple[float, float] | None:
    """Main-thread (read, written) tokens, or None when they cannot be known.

    The payload carries `cache_write_tokens` but no read count. `hit_ratio` is
    token-weighted, read / (read + write), which was checked against this
    project's transcript (0.991145 against 0.991149; a request-based ratio
    would be 0.9969), so reads follow as `ratio * written / (1 - ratio)`.

    A ratio of 1.0 leaves reads undetermined, and so does a missing write
    count. None there, because an invented total is worse than none.
    """
    if not isinstance(cache, dict) or hit_ratio is None:
        return None
    written = _as_ratio(cache.get("cache_write_tokens"))
    if written is None or written < 0 or not 0.0 <= hit_ratio < 1.0:
        return None
    return (hit_ratio * written / (1.0 - hit_ratio), written)


def _tier_warning(state: PromptCacheState) -> str:
    """The COLD or EXPIRING marker, or empty when the cache is healthy.

    COLD reports what the rebuild costs, not just that it is cold: the
    seriousness of an invalidation scales with the prefix — measured in this
    project, the same event cost 130k tokens early in a session and 509k at
    its peak — so the state alone does not tell an operator whether to care.
    The marker is emitted whether or not that magnitude is available, because
    the warning matters more than the number.

    EXPIRING reports the time left instead, because that is the band where
    acting is still cheap and the only question is how long there is to act.
    """
    if state.tier is PromptCacheTier.COLD:
        rebuild = _compact_tokens(state.rebuild_tokens)
        return f"⚠COLD {rebuild}" if rebuild else "⚠COLD"
    if state.tier is PromptCacheTier.EXPIRING:
        if state.seconds_remaining is None:
            return "⚠EXPIRING"
        return f"⚠EXPIRING {_compact_duration(state.seconds_remaining)}"
    return ""


class PromptCacheIndicatorHandler(StatusLineHandlerBase):
    """Render prompt-cache hit ratio, TTL, and a warning when the cache is cold."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PROMPT_CACHE_INDICATOR,
            priority=Priority.PROMPT_CACHE_INDICATOR,
            terminal=False,
            tags=[HandlerTag.STATUSLINE, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run; `handle` decides whether there is anything worth showing."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Render the cache segment, or nothing when the payload cannot support it."""
        cache = hook_input.get(_PROMPT_CACHE_KEY)
        state = classify_prompt_cache(cache, now=time.time())

        # UNKNOWN covers both an absent payload and a session that has not
        # cached anything yet. Rendering 0% there would invite action against a
        # problem that does not exist.
        if state.tier is PromptCacheTier.UNKNOWN:
            return AdvisoryResult(context=[])

        parts: list[str] = []

        if state.hit_ratio is not None:
            parts.append(f"{round(state.hit_ratio * 100)}%")

        ttl = cache.get("ttl") if isinstance(cache, dict) else None
        if isinstance(ttl, str) and ttl:
            parts.append(ttl)

        warning = _tier_warning(state)
        if warning:
            parts.append(warning)

        # Shown even while WARM: the cache being warm NOW says nothing about
        # the rebuild having just been paid for, and that rebuild is the
        # expensive event worth seeing. This is the visual invalidation warning.
        if state.recent_miss:
            flag = "⚠INVALIDATED"
            if state.recent_miss_cause:
                flag = f"{flag} {state.recent_miss_cause}"
            parts.append(flag)

        parts.extend(self._sub_agent_parts(hook_input, cache, state.hit_ratio))

        if not parts:
            return AdvisoryResult(context=[])

        return AdvisoryResult(context=[f"| ⚡ {' '.join(parts)}"])

    def _sub_agent_parts(
        self, hook_input: dict[str, Any], cache: object, main_ratio: float | None
    ) -> list[str]:
        """`sub NN% <ttl>` and `total NN%`, or nothing when no agent has run.

        `prompt_cache` describes the MAIN thread only, and sub-agents get no
        status line of their own — so without this the bar would report the
        healthy half of a session and hide the expensive one. Measured here:
        98.87% main against 62.17% on a short sub-agent.

        The sub side carries its OWN TTL because the halves run different ones
        (1h main, 5m sub by default), so a single indicator would be wrong for
        one of them.

        Nothing is rendered when no agent has run. A session that spawned none
        has no sub-agent ratio, and `sub 0%` would read as a catastrophe rather
        than an absence. Its total would just repeat the main figure.

        Fails silent: the MAIN figure is the load-bearing one and must survive
        anything the sub-agent sidecar does.
        """
        try:
            totals = read_subagent_cache_totals(str(hook_input.get("session_id") or ""))
        except (OSError, RuntimeError, ValueError):
            return []

        if not totals.get("agents_seen"):
            return []

        sub_read = _as_ratio(totals.get("cache_read_tokens")) or 0.0
        sub_written = _as_ratio(totals.get("cache_write_tokens")) or 0.0
        if sub_read + sub_written <= 0:
            return []

        sub = f"sub {round(sub_read / (sub_read + sub_written) * 100)}%"
        sub_ttl = _sub_ttl(totals)
        if sub_ttl:
            sub = f"{sub} {sub_ttl}"
        parts = [sub]

        main_tokens = _main_read_and_written(cache, main_ratio)
        if main_tokens is not None:
            read = main_tokens[0] + sub_read
            written = main_tokens[1] + sub_written
            parts.append(f"total {round(read / (read + written) * 100)}%")
        return parts

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment (read-only, no I/O)."""
        return SegmentExplanation(
            glyphs=("⚡",),
            name="Prompt Cache",
            what_it_is=(
                "The session's prompt-cache hit ratio and the TTL in force, read from the "
                "`prompt_cache` object Claude Code ships on every status-line render."
            ),
            how_to_read=(
                "`⚡ 99% 1h` is a healthy session reusing its cached prefix at about a tenth "
                "of the input price. `⚠COLD` means the prefix is gone, and the token figure "
                "beside it is what the next request will pay to rebuild it. `⚠EXPIRING 4m` "
                "means it is still alive but inside the tail of its TTL — the band where "
                "acting is still cheap. `⚠INVALIDATED <cause>` means something rebuilt the "
                "cache within the last few minutes, and names what Claude Code attributed it "
                "to; it is shown even while the cache is warm again, because the rebuild has "
                "already been paid for. `sub NN% 5m` is the sub-agent half, which has no status "
                "line of its own, with the TTL its agents actually wrote under. `total NN%` "
                "is the whole session weighted by tokens, not an average of the two figures. "
                "Both appear only once a sub-agent has run. Nothing is shown when Claude Code does not report cache "
                "state, or before any caching has been observed — no ratio is honest there, "
                "and 0% would not be."
            ),
            current_value=(
                "Rendered per session from the live payload; there is no value outside a "
                "status-line render."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="prompt cache indicator renders cache state",
                command='echo "test"',
                description=(
                    "Verify the status line carries a '⚡' segment showing the prompt-cache "
                    "hit ratio and TTL. Absent when Claude Code reports no cache state."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Display-only status-line segment; renders nothing it cannot source",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
