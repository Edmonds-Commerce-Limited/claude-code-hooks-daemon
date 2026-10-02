"""UsageIndicatorHandler - subscription usage in the status line (Plan 00479).

Renders the 5-hour and weekly usage windows, e.g. ``5h 13% (3h 20m) · 7d 3%``.

The figures come from the daemon's usage snapshot
(:func:`claude_code_hooks_daemon.core.data_layer.latest_usage`), which the
controller fills from ``rate_limits`` on every Status event. Reading the
snapshot rather than this render's own payload means the segment also shows
the last known reading on a render whose payload carries none (a thread that
has not yet had a response), and it shares one definition of "absent" with
every other consumer: a window past its ``resets_at`` is gone.

**Hidden entirely when there is no data.** An API-key session, a session
before its first response, and a plan without usage windows have nothing
honest to show, and ``0%`` would be a claim rather than an absence.

**Countdown.** The 5-hour window always shows the time to its reset, because
it rolls over within the working day and that is the number that decides
whether to wait. The weekly window shows its countdown only once it is at or
above ``seven_day_countdown_pct`` (default 80): at 3% used a reset six days
away is noise, and at 85% it is the thing worth knowing.

**Colour** follows the context-usage bands (``model_context``): green, yellow,
orange, and bold bright red. Each window is coloured by its own percentage.
Percentages display rounded DOWN, so a ceiling of 80 is never displayed as
reached while the real figure is 79.9.
"""

import logging
import math
import time
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.data_layer import latest_usage
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow

logger = logging.getLogger(__name__)

_RESET: Final[str] = "\033[0m"
# The same SGR sequences model_context uses for its green/yellow/orange/critical bands.
_GREEN: Final[str] = "\033[32m"
_YELLOW: Final[str] = "\033[33m"
_ORANGE: Final[str] = "\033[38;5;208m"
_CRITICAL: Final[str] = "\033[1;91m"

_DEFAULT_WARN_PCT: Final[int] = 60
_DEFAULT_HIGH_PCT: Final[int] = 80
_DEFAULT_CRITICAL_PCT: Final[int] = 90
_DEFAULT_SEVEN_DAY_COUNTDOWN_PCT: Final[int] = 80

_SEPARATOR: Final[str] = " · "
_SECONDS_PER_MINUTE: Final[int] = 60
_SECONDS_PER_HOUR: Final[int] = 3600
_SECONDS_PER_DAY: Final[int] = 86400


def format_countdown(seconds: int) -> str:
    """A reset countdown as ``6d 23h``, ``3h 20m``, ``50m`` or ``<1m``."""
    if seconds >= _SECONDS_PER_DAY:
        days, rest = divmod(seconds, _SECONDS_PER_DAY)
        return f"{days}d {rest // _SECONDS_PER_HOUR}h"
    if seconds >= _SECONDS_PER_HOUR:
        hours, rest = divmod(seconds, _SECONDS_PER_HOUR)
        return f"{hours}h {rest // _SECONDS_PER_MINUTE}m"
    if seconds >= _SECONDS_PER_MINUTE:
        return f"{seconds // _SECONDS_PER_MINUTE}m"
    return "<1m"


class UsageIndicatorHandler(StatusLineHandlerBase):
    """Show 5-hour and weekly subscription usage, colour-coded, with reset countdown."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.USAGE_INDICATOR,
            priority=Priority.USAGE_INDICATOR,
            terminal=False,
            tags=[HandlerTag.STATUSLINE, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )
        # Overridable via handler options of the same names.
        self._warn_pct: float = _DEFAULT_WARN_PCT
        self._high_pct: float = _DEFAULT_HIGH_PCT
        self._critical_pct: float = _DEFAULT_CRITICAL_PCT
        self._seven_day_countdown_pct: float = _DEFAULT_SEVEN_DAY_COUNTDOWN_PCT

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status line events."""
        return True

    def _colour(self, used_percentage: float) -> str:
        if used_percentage >= self._critical_pct:
            return _CRITICAL
        if used_percentage >= self._high_pct:
            return _ORANGE
        if used_percentage >= self._warn_pct:
            return _YELLOW
        return _GREEN

    def _part(self, label: str, window: UsageWindow, now: float, *, countdown: bool) -> str:
        text = f"{label} {math.floor(window.used_percentage)}%"
        if countdown:
            text += f" ({format_countdown(window.seconds_until_reset(now))})"
        return f"{self._colour(window.used_percentage)}{text}{_RESET}"

    def _render(self, snapshot: UsageSnapshot, now: float) -> str:
        parts: list[str] = []
        if snapshot.five_hour is not None:
            parts.append(self._part("5h", snapshot.five_hour, now, countdown=True))
        if snapshot.seven_day is not None:
            show_countdown = snapshot.seven_day.used_percentage >= self._seven_day_countdown_pct
            parts.append(self._part("7d", snapshot.seven_day, now, countdown=show_countdown))
        return _SEPARATOR.join(parts)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Return the usage segment, or no segment when there is no live usage data."""
        now = time.time()
        try:
            snapshot = latest_usage(now=now)
        except OSError as exc:
            logger.warning("Skipping usage indicator: %s", exc)
            return AdvisoryResult(context=[])
        if snapshot is None:
            return AdvisoryResult(context=[])
        return AdvisoryResult(context=[f"| {self._render(snapshot, now)}"])

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment; the current value is read from the usage snapshot."""
        now = time.time()
        try:
            snapshot = latest_usage(now=now)
        except OSError as exc:
            logger.debug("Failed to read usage snapshot for explain_segment: %s", exc)
            snapshot = None
        if snapshot is None:
            current_value = (
                "Not shown now - no usage data yet. It appears after the first response "
                "of a claude.ai Pro or Max session."
            )
        else:
            plain = self._render(snapshot, now)
            for colour in (_GREEN, _YELLOW, _ORANGE, _CRITICAL, _RESET):
                plain = plain.replace(colour, "")
            current_value = f"Currently shows: {plain}"
        return SegmentExplanation(
            glyphs=("5h", "7d"),
            name="Subscription Usage",
            what_it_is=(
                "How much of the claude.ai subscription's 5-hour and weekly usage windows "
                "is used, read from the `rate_limits` Claude Code ships on each status render."
            ),
            how_to_read=(
                "`5h 13% (3h 20m)` is 13% of the 5-hour window used, resetting in 3h 20m. "
                "`7d 3%` is the weekly window; its reset countdown appears once it reaches "
                f"{self._seven_day_countdown_pct:g}%. Green below {self._warn_pct:g}%, "
                f"yellow from {self._warn_pct:g}%, orange from {self._high_pct:g}%, bold red "
                f"from {self._critical_pct:g}%. Percentages are rounded down. A window past "
                "its reset is dropped; nothing is shown when no usage data exists (API-key "
                "sessions, or before the first response)."
            ),
            current_value=current_value,
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="usage indicator renders subscription usage",
                command='echo "test"',
                description=(
                    "Verify the status line carries a '5h NN% (..) · 7d NN%' segment on a "
                    "claude.ai subscription session. Absent when Claude Code reports no "
                    "usage data. Confirmed active by the daemon loading without errors."
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
