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

**Compact chips, styled like the usage segment.** After a `⚡` icon the segment
is up to three background-coloured chips joined by an uncoloured `|`: `main`,
then `⑂` (sub-agents) and `Σ` (the whole session) once a sub-agent has run. A
green chip is its label alone; a chip that is not green adds the figures worth
reading (`main 82% 1h`, `⑂ 62% 5m`, `Σ 70%`). The colours are the
``model_context`` chip bands.

**The direction is the opposite of the usage segment.** Usage gets worse as the
percentage rises; a hit ratio gets worse as it FALLS. So a ratio at or above
`healthy_pct` is green, at or above `warn_pct` yellow, at or above
`critical_pct` orange, and below `critical_pct` red.

**State beats ratio, and the worst of the two wins.** The main chip also
reflects the cache's state, which a good ratio can hide: COLD is a red
`❄ <rebuild tokens>` chip; EXPIRING is at least yellow with a `⏳` countdown;
a recent miss is at least yellow with `↻ <cause>`. A state never makes a chip
greener than its ratio.

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

import math
import time
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
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

_RESET: Final[str] = "\033[0m"
# The same background chips model_context and usage_indicator use, indexed by severity.
_GREEN: Final[str] = "\033[42m\033[30m"
_YELLOW: Final[str] = "\033[43m\033[30m"
_ORANGE: Final[str] = "\033[48;5;208m\033[30m"
_RED: Final[str] = "\033[41m\033[97m"
_SEVERITY_COLOURS: Final[tuple[str, ...]] = (_GREEN, _YELLOW, _ORANGE, _RED)
_SEV_GREEN: Final[int] = 0
_SEV_YELLOW: Final[int] = 1
_SEV_ORANGE: Final[int] = 2
_SEV_RED: Final[int] = 3

_DEFAULT_HEALTHY_PCT: Final[int] = 90
_DEFAULT_WARN_PCT: Final[int] = 75
_DEFAULT_CRITICAL_PCT: Final[int] = 50

_ICON: Final[str] = "⚡"
_MAIN_LABEL: Final[str] = "main"
_SUB_LABEL: Final[str] = "⑂"
_TOTAL_LABEL: Final[str] = "Σ"
_COLD_GLYPH: Final[str] = "❄"
_EXPIRING_GLYPH: Final[str] = "⏳"
_MISS_GLYPH: Final[str] = "↻"
_SEPARATOR: Final[str] = "|"

_PERCENT_PRECISION: Final[int] = 6


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


def _percent(ratio: float) -> float:
    """A 0-1 ratio as a percentage, with float noise (0.29 * 100) removed."""
    return round(ratio * 100, _PERCENT_PRECISION)


def _shown_percent(ratio: float) -> str:
    """A ratio as `NN%`, rounded DOWN so 89.6% never reads as the 90% green line."""
    return f"{math.floor(_percent(ratio))}%"


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


class PromptCacheIndicatorHandler(StatusLineHandlerBase):
    """Render prompt-cache health as `main`, `⑂` and `Σ` background-coloured chips."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PROMPT_CACHE_INDICATOR,
            priority=Priority.PROMPT_CACHE_INDICATOR,
            terminal=False,
            tags=[HandlerTag.STATUSLINE, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )
        # Overridable via handler options of the same names. A hit ratio below
        # a threshold is WORSE, the opposite direction from usage_indicator.
        self._healthy_pct: float = _DEFAULT_HEALTHY_PCT
        self._warn_pct: float = _DEFAULT_WARN_PCT
        self._critical_pct: float = _DEFAULT_CRITICAL_PCT

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run; `handle` decides whether there is anything worth showing."""
        return True

    def _ratio_severity(self, ratio: float | None) -> int:
        """Green at or above `healthy_pct`, then yellow, orange, red as it falls.

        A missing ratio is green: absence is not evidence of a problem.
        """
        if ratio is None:
            return _SEV_GREEN
        pct = _percent(ratio)
        if pct >= self._healthy_pct:
            return _SEV_GREEN
        if pct >= self._warn_pct:
            return _SEV_YELLOW
        if pct >= self._critical_pct:
            return _SEV_ORANGE
        return _SEV_RED

    @staticmethod
    def _chip(severity: int, text: str) -> str:
        return f"{_SEVERITY_COLOURS[severity]}{text}{_RESET}"

    def _ratio_chip(self, label: str, ratio: float, ttl: str) -> str:
        """A sub or total chip: the label alone while green, else with ratio and TTL."""
        severity = self._ratio_severity(ratio)
        text = label
        if severity != _SEV_GREEN:
            text = " ".join(part for part in (label, _shown_percent(ratio), ttl) if part)
        return self._chip(severity, text)

    def _main_chip(self, state: PromptCacheState, ttl: object) -> str:
        """The main chip: its ratio band, raised by COLD, EXPIRING or a recent miss.

        COLD replaces the figures with what the rebuild costs and is always
        red. The other states raise the chip to at least yellow and add their
        own detail; they never make it greener than its ratio.
        """
        if state.tier is PromptCacheTier.COLD:
            rebuild = _compact_tokens(state.rebuild_tokens)
            return self._chip(_SEV_RED, f"{_COLD_GLYPH} {rebuild}" if rebuild else _COLD_GLYPH)

        severity = self._ratio_severity(state.hit_ratio)
        details: list[str] = []
        if state.tier is PromptCacheTier.EXPIRING:
            severity = max(severity, _SEV_YELLOW)
            if state.seconds_remaining is not None:
                details.append(f"{_EXPIRING_GLYPH}{_compact_duration(state.seconds_remaining)}")
        if state.recent_miss:
            severity = max(severity, _SEV_YELLOW)
            details.append(
                f"{_MISS_GLYPH} {state.recent_miss_cause}"
                if state.recent_miss_cause
                else _MISS_GLYPH
            )

        if severity == _SEV_GREEN:
            return self._chip(severity, _MAIN_LABEL)
        if not details and isinstance(ttl, str) and ttl:
            details.append(ttl)
        ratio_text = _shown_percent(state.hit_ratio) if state.hit_ratio is not None else ""
        text = " ".join(part for part in (_MAIN_LABEL, ratio_text, *details) if part)
        return self._chip(severity, text)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Render the cache chips, or nothing when the payload cannot support it."""
        cache = hook_input.get(_PROMPT_CACHE_KEY)
        state = classify_prompt_cache(cache, now=time.time())

        # UNKNOWN covers both an absent payload and a session that has not
        # cached anything yet. Rendering 0% there would invite action against a
        # problem that does not exist.
        if state.tier is PromptCacheTier.UNKNOWN:
            return AdvisoryResult(context=[])

        ttl = cache.get("ttl") if isinstance(cache, dict) else None
        chips = [self._main_chip(state, ttl)]
        chips.extend(self._sub_agent_chips(hook_input, cache, state.hit_ratio))
        return AdvisoryResult(context=[f"| {_ICON} {_SEPARATOR.join(chips)}"])

    def _sub_agent_chips(
        self, hook_input: dict[str, Any], cache: object, main_ratio: float | None
    ) -> list[str]:
        """The `⑂` and `Σ` chips, or nothing when no agent has run.

        `prompt_cache` describes the MAIN thread only, and sub-agents get no
        status line of their own — so without this the bar would report the
        healthy half of a session and hide the expensive one. Measured here:
        98.87% main against 62.17% on a short sub-agent.

        The sub side carries its OWN TTL because the halves run different ones
        (1h main, 5m sub by default), so a single indicator would be wrong for
        one of them.

        Nothing is rendered when no agent has run. A session that spawned none
        has no sub-agent ratio, and `0%` would read as a catastrophe rather
        than an absence. Its total would just repeat the main figure.

        Fails silent: the MAIN chip is the load-bearing one and must survive
        anything the sub-agent sidecar does.
        """
        try:
            session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
            totals = read_subagent_cache_totals(session_id)
        except (OSError, RuntimeError, ValueError):
            return []

        if not totals.get("agents_seen"):
            return []

        sub_read = _as_ratio(totals.get("cache_read_tokens")) or 0.0
        sub_written = _as_ratio(totals.get("cache_write_tokens")) or 0.0
        if sub_read + sub_written <= 0:
            return []

        chips = [
            self._ratio_chip(_SUB_LABEL, sub_read / (sub_read + sub_written), _sub_ttl(totals))
        ]

        main_tokens = _main_read_and_written(cache, main_ratio)
        if main_tokens is not None:
            read = main_tokens[0] + sub_read
            written = main_tokens[1] + sub_written
            chips.append(self._ratio_chip(_TOTAL_LABEL, read / (read + written), ""))
        return chips

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment (read-only, no I/O)."""
        return SegmentExplanation(
            glyphs=(_ICON, _SUB_LABEL, _TOTAL_LABEL, _COLD_GLYPH, _EXPIRING_GLYPH, _MISS_GLYPH),
            name="Prompt Cache",
            what_it_is=(
                "How well the session reuses its cached prompt prefix, read from the "
                "`prompt_cache` object Claude Code ships on every status-line render."
            ),
            how_to_read=(
                "`⚡ main|⑂|Σ` are the main thread, the sub-agents and the whole session, each "
                "on a background coloured by its cache hit ratio. A HIGH ratio is good, the "
                f"opposite of the usage segment: green at {self._healthy_pct:g}% or more, "
                f"yellow from {self._warn_pct:g}%, orange from {self._critical_pct:g}%, red "
                f"below {self._critical_pct:g}%. A green chip shows only its label; any other "
                "adds its figures, e.g. `main 82% 1h`, `⑂ 62% 5m`, `Σ 70%` (the TTL is the one "
                "in force; `Σ` is weighted by tokens, not an average). `⑂` and `Σ` appear only "
                "once a sub-agent has run. The main chip also reflects state, and the worst "
                "of ratio and state wins: `❄ 509k` (red) means the prefix is gone and the "
                "figure is what the next request pays to rebuild it; `⏳4m` means it is alive "
                "but inside the tail of its TTL, the band where acting is still cheap; "
                "`↻ <cause>` means something rebuilt the cache within the last few minutes "
                "and names what Claude Code blamed. Nothing is shown when Claude Code does "
                "not report cache state, or before any caching has been observed — no ratio "
                "is honest there, and 0% would not be."
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
                title="prompt cache indicator renders cache chips",
                command='echo "test"',
                description=(
                    "Verify the status line carries a '⚡ main' chip segment, background "
                    "coloured by the prompt-cache hit ratio (green label only when healthy), "
                    "with '⑂' and 'Σ' chips once a sub-agent has run. Absent when Claude Code "
                    "reports no cache state."
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
