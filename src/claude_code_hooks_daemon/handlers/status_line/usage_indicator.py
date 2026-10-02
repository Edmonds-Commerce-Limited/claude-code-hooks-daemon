"""UsageIndicatorHandler - subscription usage in the status line (Plan 00479).

Renders the 5-hour and weekly usage windows as compact background-coloured
chips after a line-graph icon. A window below the warning level is its label alone
(``📈 5h|7d``); a window at or above it adds its percentage and reset countdown
(``📈 5h 67% 3h 20m|7d``). Owner ruling: green needs no number, so the segment
stays narrow until there is something worth reading.

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

**Background colour** follows the context-usage chip bands (``model_context``):
green, yellow, orange and red, each window coloured by its own percentage. The
``|`` between chips carries no background. Percentages display rounded DOWN,
so a ceiling of 80 is never displayed as reached while the real figure is 79.9.
"""

import logging
import math
import re
import time
from datetime import UTC, datetime
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.data_layer import latest_usage
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.utils.usage_pause_gate import active_usage_pause, resume_schedule

logger = logging.getLogger(__name__)

_RESET: Final[str] = "\033[0m"
# The same background chips model_context uses for its green/yellow/orange/critical bands.
_GREEN: Final[str] = "\033[42m\033[30m"
_YELLOW: Final[str] = "\033[43m\033[30m"
_ORANGE: Final[str] = "\033[48;5;208m\033[30m"
_CRITICAL: Final[str] = "\033[41m\033[97m"
_ANSI: Final[re.Pattern[str]] = re.compile(r"\033\[[0-9;]*m")

_DEFAULT_WARN_PCT: Final[int] = 60
_DEFAULT_HIGH_PCT: Final[int] = 80
_DEFAULT_CRITICAL_PCT: Final[int] = 90

_ICON: Final[str] = "📈"
_PAUSE_ICON: Final[str] = "⏸"
_SEPARATOR: Final[str] = "|"
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

    def _chip(self, label: str, window: UsageWindow, now: float) -> str:
        """One window: the label alone below the warning level, else with % and countdown."""
        text = label
        if window.used_percentage >= self._warn_pct:
            countdown = format_countdown(window.seconds_until_reset(now))
            text = f"{label} {math.floor(window.used_percentage)}% {countdown}"
        return f"{self._colour(window.used_percentage)}{text}{_RESET}"

    def _render(self, snapshot: UsageSnapshot, now: float) -> str:
        chips: list[str] = []
        if snapshot.five_hour is not None:
            chips.append(self._chip("5h", snapshot.five_hour, now))
        if snapshot.seven_day is not None:
            chips.append(self._chip("7d", snapshot.seven_day, now))
        return f"{_ICON} {_SEPARATOR.join(chips)}"

    @staticmethod
    def _pause_chip(hook_input: dict[str, Any], now: float) -> str | None:
        """``⏸ usage HH:MM`` while the session is paused on its usage ceiling, else None.

        HH:MM is the resume time in the machine's local zone (Plan 00479 Task 4.7).
        """
        pause = active_usage_pause(str(hook_input.get(HookInputField.SESSION_ID) or ""), now=now)
        if pause is None:
            return None
        # A human reads this, so it is the machine's local time (the resume cron's own
        # expression is in UTC; see ``resume_schedule``).
        hhmm = resume_schedule(pause.resume_at, tz=datetime.now().astimezone().tzinfo or UTC).hhmm
        return f"{_CRITICAL}{_PAUSE_ICON} usage {hhmm}{_RESET}"

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Return the usage segment, or no segment when there is no live usage data.

        A session paused on its usage ceiling leads with ``⏸ usage HH:MM``, and
        shows it even when there is no usage snapshot.
        """
        now = time.time()
        pause_chip = self._pause_chip(hook_input, now)
        try:
            snapshot = latest_usage(now=now)
        except OSError as exc:
            logger.warning("Skipping usage indicator: %s", exc)
            snapshot = None
        parts = [
            part for part in (pause_chip, self._render(snapshot, now) if snapshot else None) if part
        ]
        if not parts:
            return AdvisoryResult(context=[])
        return AdvisoryResult(context=[f"| {' '.join(parts)}"])

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
            current_value = f"Currently shows: {_ANSI.sub('', self._render(snapshot, now))}"
        return SegmentExplanation(
            glyphs=(_ICON, "5h", "7d", _PAUSE_ICON),
            name="Subscription Usage",
            what_it_is=(
                "How much of the claude.ai subscription's 5-hour and weekly usage windows "
                "is used, read from the `rate_limits` Claude Code ships on each status render."
            ),
            how_to_read=(
                "`📈 5h|7d` are the 5-hour and weekly windows, each on a background "
                f"coloured by its usage: green below {self._warn_pct:g}%, yellow from "
                f"{self._warn_pct:g}%, orange from {self._high_pct:g}%, red from "
                f"{self._critical_pct:g}%. A green window shows only its label; from "
                f"{self._warn_pct:g}% it adds its percentage and reset countdown, e.g. "
                "`5h 67% 3h 20m`. Percentages are rounded down. A window past "
                "its reset is dropped; nothing is shown when no usage data exists (API-key "
                "sessions, or before the first response). `⏸ usage 14:35` in red means the "
                "session is paused on its host's usage ceiling and resumes at that local time."
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
                    "Verify the status line carries a '📈 5h|7d' usage segment on a "
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
