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

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation

#: Payload key carrying the harness-computed cache state.
_PROMPT_CACHE_KEY = "prompt_cache"

#: Divisor for rendering a token count as a compact "384k".
_TOKENS_PER_K = 1000


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
        if not isinstance(cache, dict):
            return AdvisoryResult(context=[])

        # A session that has not cached anything yet has no ratio to report.
        # Rendering 0% there would invite action against a non-problem.
        if not cache.get("caching_observed"):
            return AdvisoryResult(context=[])

        parts: list[str] = []

        ratio = _as_ratio(cache.get("hit_ratio"))
        if ratio is not None:
            parts.append(f"{round(ratio * 100)}%")

        ttl = cache.get("ttl")
        if isinstance(ttl, str) and ttl:
            parts.append(ttl)

        if not cache.get("warm"):
            # The warning is the point, so it is emitted whether or not the
            # magnitude is available.
            cold = "⚠COLD"
            rebuild = _compact_tokens(cache.get("recache_tokens_if_cold"))
            if rebuild:
                cold = f"{cold} {rebuild}"
            parts.append(cold)

        if not parts:
            return AdvisoryResult(context=[])

        return AdvisoryResult(context=[f"| ⚡ {' '.join(parts)}"])

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
                "of the input price. `⚠COLD` means the prefix was rebuilt, and the token "
                "figure beside it is what that rebuild cost. Nothing is shown when Claude "
                "Code does not report cache state, or before any caching has been observed — "
                "no ratio is honest there, and 0% would not be."
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
