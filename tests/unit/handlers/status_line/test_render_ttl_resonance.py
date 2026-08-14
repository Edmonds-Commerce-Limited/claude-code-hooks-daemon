"""Guard: a render-path TTL must never sit in the resonance band (Plan 00238).

A TTL between 1x and 2x the render interval does not merely cache poorly, it
RESONATES. A miss at render ``k`` caches at ``t_k``; the next render lands
inside the window (hit); the one after lands outside it (miss). The cache
settles into an exact alternating hit/miss steady state and discards half its
own value **by construction**, not by chance.

``git_branch`` shipped at 2.0s against a measured ~1.04s render interval and
did exactly that: 57 misses in 115 renders (49.6%) over a live 120s window,
~5,760 git subprocess spawns/hour from one handler.

Nothing reported it, and nothing would have. A resonant cache is
indistinguishable from a healthy one at every surface a human looks at — it
logs nothing, it returns correct values, and its hit rate is only wrong if you
know what it *could* have been. The number was reasonable when chosen; it
became wrong when the render rate moved underneath it, and that can happen
again in either direction. Hence a guard rather than a one-time fix.

**The basis must be the TYPICAL interval, not the fastest.** A LONGER interval
is the worse case for a fixed TTL, because the window then covers fewer
renders. The first version of this guard measured against the fastest observed
interval (0.939s), where the shipped 2.0s value scores 3 renders per miss and
sails through — it would have passed the exact defect it was written to catch.
That is the failure mode this whole plan is about, reproduced inside its own
guard, so it is recorded here rather than quietly corrected.
"""

import math

from claude_code_hooks_daemon.handlers.status_line import git_branch

# Live render intervals (Plan 00238 Task 1.1): 86 renders in 90s — min 0.939s,
# median 1.039s, max 1.833s; a second 120s window measured 115 renders
# (1.043s mean). The MEDIAN governs the steady-state miss rate, so it is the
# basis for the primary check; the MAX is the worst case and gets a weaker bar.
_TYPICAL_RENDER_INTERVAL_SECONDS = 1.043
_SLOWEST_RENDER_INTERVAL_SECONDS = 1.833

# The value that shipped, kept so the anti-vacuity check can assert the guard
# rejects it. Do not use it for anything else.
_PRE_FIX_RESONANT_TTL_SECONDS = 2.0

# Renders served per miss below which a cache is resonant: at 1 it never hits,
# at 2 it alternates. Anything strictly under 3 is in or adjacent to the band.
_RESONANT_RENDERS_PER_MISS = 2
_MINIMUM_RENDERS_PER_MISS = 3


def _renders_per_miss(ttl_seconds: float, interval_seconds: float) -> int:
    """Renders served per cache miss for ``ttl`` at ``interval``.

    A miss refreshes the cache at ``t``; every render strictly inside
    ``[t, t + ttl)`` is a hit; the first render at or beyond ``t + ttl`` is the
    next miss. So the cycle length in renders is ``ceil(ttl / interval)``.
    """
    if interval_seconds <= 0:
        raise ValueError("render interval must be positive")
    return math.ceil(ttl_seconds / interval_seconds)


class TestResonanceDetector:
    """Guard the guard — prove the detector fires before trusting it to be quiet.

    Without these, an arithmetic slip (or the wrong interval basis) would make
    the real check below pass by computing a comfortable number for every
    input, which reads identically to finding nothing wrong.
    """

    def test_the_shipped_resonant_value_is_rejected(self) -> None:
        """The whole point: 2.0s at the typical interval must FAIL the bar."""
        served = _renders_per_miss(_PRE_FIX_RESONANT_TTL_SECONDS, _TYPICAL_RENDER_INTERVAL_SECONDS)
        assert served == _RESONANT_RENDERS_PER_MISS
        assert served < _MINIMUM_RENDERS_PER_MISS

    def test_sizing_against_the_fastest_interval_would_have_missed_it(self) -> None:
        """Records WHY the basis is the median — this is the trap, pinned.

        At the fastest observed interval the shipped value scores 3 and passes.
        If someone later 'simplifies' this guard to use the minimum, this test
        fails and explains itself.
        """
        fastest = 0.939
        assert (
            _renders_per_miss(_PRE_FIX_RESONANT_TTL_SECONDS, fastest) >= _MINIMUM_RENDERS_PER_MISS
        )

    def test_a_ttl_shorter_than_the_interval_never_hits(self) -> None:
        assert _renders_per_miss(0.5, _TYPICAL_RENDER_INTERVAL_SECONDS) == 1


class TestGitBranchRenderTtl:
    def test_the_render_ttl_is_outside_the_resonance_band(self) -> None:
        ttl = git_branch._DEFAULT_RENDER_TTL_SECONDS
        served = _renders_per_miss(ttl, _TYPICAL_RENDER_INTERVAL_SECONDS)

        assert served >= _MINIMUM_RENDERS_PER_MISS, (
            f"_DEFAULT_RENDER_TTL_SECONDS is {ttl}s, which serves only {served} "
            f"render(s) per cache miss at the typical render interval "
            f"({_TYPICAL_RENDER_INTERVAL_SECONDS}s). A TTL between 1x and 2x the "
            "render interval RESONATES: the cache alternates hit/miss forever "
            "and throws away half its value by construction. Re-derive the "
            "value from a fresh render-interval measurement — do not nudge it, "
            "and do not lower the bar here to make this pass."
        )

    def test_it_is_not_resonant_even_at_the_slowest_observed_render_rate(self) -> None:
        ttl = git_branch._DEFAULT_RENDER_TTL_SECONDS
        served = _renders_per_miss(ttl, _SLOWEST_RENDER_INTERVAL_SECONDS)

        assert served > _RESONANT_RENDERS_PER_MISS, (
            f"{ttl}s serves {served} renders per miss at the slowest observed "
            f"interval ({_SLOWEST_RENDER_INTERVAL_SECONDS}s) — that is the "
            "alternating hit/miss steady state. Render intervals jitter, so a "
            "TTL that is only safe at the typical rate is not safe."
        )

    def test_the_ttl_is_derived_from_the_measured_interval(self) -> None:
        """The value must stay a derivation, not drift back to a round number.

        A hardcoded TTL is what produced the defect: it was reasonable when
        written and became wrong silently when the render rate moved. Keeping
        the arithmetic in the source is what makes the next reader re-derive
        rather than re-guess.
        """
        expected = round(
            git_branch._RENDER_TTL_INTERVAL_MULTIPLE * git_branch._MEASURED_RENDER_INTERVAL_SECONDS,
            git_branch._RENDER_TTL_ROUNDING_PLACES,
        )
        assert git_branch._DEFAULT_RENDER_TTL_SECONDS == expected

    def test_the_fetch_interval_is_far_above_the_render_ttl(self) -> None:
        """Sanity: the two TTLs in this handler bound different things.

        The background fetch TTL (300s) bounds ahead/behind staleness and is
        deliberately orders of magnitude looser. If these two ever converge,
        one of them has been edited without understanding what it bounds.
        """
        assert (
            git_branch._DEFAULT_FETCH_INTERVAL_SECONDS > git_branch._DEFAULT_RENDER_TTL_SECONDS * 10
        )
