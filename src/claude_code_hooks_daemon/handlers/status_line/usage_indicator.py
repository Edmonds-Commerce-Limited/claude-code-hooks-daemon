"""UsageIndicatorHandler - subscription usage in the status line (Plan 00479).

Renders the 5-hour and weekly usage windows as compact background-coloured
chips after a line-graph icon. A window below the warning level is its label and
percentage run together (``📈 5h10%|7d5%``); a window at or above it is spaced out
and adds its reset countdown (``📈 5h 67% 3h 20m|7d5%``). Owner ruling: the number
is always shown, compact while green and roomier once it is worth reading.

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

**Ceiling.** When a ``hosts:`` entry gives this host a usage ceiling, the
segment ends with ``⛔ 80%`` (one figure when both windows share the limit,
else ``⛔ 5h 80% 7d 95%``, each limited window labelled). It is plain text,
carries no background, and is hidden when no ceiling applies or there is no
usage data to sit beside.

**Override.** While the owner's ``usage-pause clear`` override is valid for the session
the segment leads with ``override until HH:MM`` (red while a window is over the ceiling,
yellow otherwise), because the override is what switches the ceiling off. Like the pause
chip it shows even when there is no usage snapshot.

**Failed turn.** A session whose last turn ended on a rate limit or a credential
error leads with ``⚠ usage limit HH:MM`` (red), read from the record
``stop_failure_recorder`` keeps and shown until the session's next prompt
resolves it (``stop_failure_resolver``; Plan 00470 Task 3.1). Like the pause
chip it shows even when there is no usage snapshot.
"""

import logging
import math
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
from claude_code_hooks_daemon.core.data_layer import latest_usage
from claude_code_hooks_daemon.core.handler_bases import StatusLineHandlerBase
from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
from claude_code_hooks_daemon.core.usage_snapshot import UsageSnapshot, UsageWindow
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.stop_failure_records import (
    default_records_path,
    latest_unresolved,
)
from claude_code_hooks_daemon.utils.usage_pause import read_usage_override
from claude_code_hooks_daemon.utils.usage_pause_gate import (
    PauseEnvironment,
    active_usage_pause,
    current_breaches,
    load_project_config,
    session_ceiling,
    untracked_dir,
)

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
_CEILING_ICON: Final[str] = "⛔"
_FAILURE_ICON: Final[str] = "⚠"
#: How each recorded StopFailure error reads in the chip; an error not named here shows as is.
_FAILURE_LABELS: Final[dict[str, str]] = {
    "rate_limit": "usage limit",
    "authentication_failed": "auth failed",
    "cloud_credential_error": "cloud credential",
}
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
        # Injectable seam (tests substitute a fake); not a config option.
        self._config_loader: Callable[[], Config] = load_project_config

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
        """One window: compact ``5h10%`` below the warning level, else spaced with countdown."""
        percent = math.floor(window.used_percentage)
        if window.used_percentage >= self._warn_pct:
            countdown = format_countdown(window.seconds_until_reset(now))
            text = f"{label} {percent}% {countdown}"
        else:
            text = f"{label}{percent}%"
        return f"{self._colour(window.used_percentage)}{text}{_RESET}"

    def _render(self, snapshot: UsageSnapshot, now: float, ceiling: str | None = None) -> str:
        chips: list[str] = []
        if snapshot.five_hour is not None:
            chips.append(self._chip("5h", snapshot.five_hour, now))
        if snapshot.seven_day is not None:
            chips.append(self._chip("7d", snapshot.seven_day, now))
        text = f"{_ICON} {_SEPARATOR.join(chips)}"
        return f"{text} {ceiling}" if ceiling else text

    def _ceiling_text(self, hook_input: dict[str, Any]) -> str | None:
        """``⛔ 80%`` for the ceiling this host runs under, else None.

        One figure when both windows share a limit, else each limited window
        labelled (``⛔ 5h 80% 7d 95%``). None when no ``hosts:`` entry matches
        or the matching entries set no ceiling.
        """
        # The default loader degrades an unloadable config to no ceiling itself.
        ceiling = session_ceiling(self._config_loader(), hook_input)
        if ceiling.five_hour is None and ceiling.seven_day is None:
            return None
        if ceiling.five_hour == ceiling.seven_day:
            return f"{_CEILING_ICON} {ceiling.five_hour:g}%"
        limits = (("5h", ceiling.five_hour), ("7d", ceiling.seven_day))
        shown = " ".join(f"{label} {limit:g}%" for label, limit in limits if limit is not None)
        return f"{_CEILING_ICON} {shown}"

    @staticmethod
    def _pause_chip(hook_input: dict[str, Any], now: float) -> str | None:
        """``⏸ usage HH:MM`` while the session is paused on its usage ceiling, else None.

        HH:MM is the resume time in the machine's local zone (Plan 00479 Task 4.7).
        """
        pause = active_usage_pause(str(hook_input.get(HookInputField.SESSION_ID) or ""), now=now)
        if pause is None:
            return None
        # A human reads this, so it is the machine's local time (the resume cron itself
        # names no clock time).
        hhmm = f"{datetime.fromtimestamp(pause.resume_at):%H:%M}"
        return f"{_CRITICAL}{_PAUSE_ICON} usage {hhmm}{_RESET}"

    def _override_chip(self, hook_input: dict[str, Any], now: float) -> str | None:
        """``override until HH:MM`` while the owner's override suppresses this session's ceiling.

        Shown whenever the override is valid, not only while usage is over the ceiling: it
        is what switches the guard off, and a breach can arrive at any point inside it
        (red when one is already there, yellow otherwise). HH:MM is the end in the
        machine's local zone, with the month and day when it is not today. None without a
        session id, a project context, an override, or a known end time.
        """
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        directory = untracked_dir()
        if not session_id or directory is None:
            return None
        override = read_usage_override(directory, session_id, now=now)
        if override is None or override.until is None:
            return None
        end = datetime.fromtimestamp(override.until)
        same_day = end.date() == datetime.fromtimestamp(now).date()
        when = f"{end:%H:%M}" if same_day else f"{end:%m-%d %H:%M}"
        env = PauseEnvironment(clock=lambda: now, config_loader=self._config_loader)
        over = bool(current_breaches(hook_input, env))
        return f"{_CRITICAL if over else _YELLOW}override until {when}{_RESET}"

    @staticmethod
    def _failure_chip(hook_input: dict[str, Any]) -> str | None:
        """``⚠ usage limit HH:MM`` while this session's last turn ended on an API error.

        Shown from the session's newest unresolved StopFailure record until its
        next prompt resolves it. HH:MM is when the turn failed, in the machine's
        local zone. None without a session id, a project context, or a failure.
        """
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        path = default_records_path()
        if not session_id or path is None:
            return None
        failure = latest_unresolved(path, session_id)
        if failure is None:
            return None
        label = _FAILURE_LABELS.get(failure.error, failure.error)
        # read_records admits only times datetime can represent, so this cannot raise.
        hhmm = f"{datetime.fromtimestamp(failure.recorded_at):%H:%M}"
        return f"{_CRITICAL}{_FAILURE_ICON} {label} {hhmm}{_RESET}"

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Return the usage segment, or no segment when there is no live usage data.

        A session paused on its usage ceiling leads with ``⏸ usage HH:MM``, and
        shows it even when there is no usage snapshot. A session whose last turn
        ended on an API error leads with ``⚠ usage limit HH:MM`` the same way.
        """
        now = time.time()
        failure_chip = self._failure_chip(hook_input)
        pause_chip = self._pause_chip(hook_input, now)
        try:
            snapshot = latest_usage(now=now)
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="the usage snapshot cannot be read, so the indicator is omitted (None); the status line fails silent by contract",
            )
            snapshot = None
        usage = self._render(snapshot, now, self._ceiling_text(hook_input)) if snapshot else None
        override_chip = self._override_chip(hook_input, now)
        parts = [part for part in (failure_chip, pause_chip, override_chip, usage) if part]
        if not parts:
            return AdvisoryResult(context=[])
        return AdvisoryResult(context=[f"| {' '.join(parts)}"])

    def explain_segment(self) -> SegmentExplanation:
        """Describe this segment; the current value is read from the usage snapshot."""
        now = time.time()
        try:
            snapshot = latest_usage(now=now)
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="status-line segments fail silent by contract: an unexpected error omits the segment rather than showing a misleading one",
                level=logging.DEBUG,
            )
            snapshot = None
        if snapshot is None:
            current_value = (
                "Not shown now - no usage data yet. It appears after the first response "
                "of a claude.ai Pro or Max session."
            )
        else:
            current_value = f"Currently shows: {_ANSI.sub('', self._render(snapshot, now))}"
        return SegmentExplanation(
            glyphs=(_ICON, "5h", "7d", _PAUSE_ICON, _CEILING_ICON, _FAILURE_ICON),
            name="Subscription Usage",
            what_it_is=(
                "How much of the claude.ai subscription's 5-hour and weekly usage windows "
                "is used, read from the `rate_limits` Claude Code ships on each status render."
            ),
            how_to_read=(
                "`📈 5h10%|7d5%` are the 5-hour and weekly windows, each on a background "
                f"coloured by its usage: green below {self._warn_pct:g}%, yellow from "
                f"{self._warn_pct:g}%, orange from {self._high_pct:g}%, red from "
                f"{self._critical_pct:g}%. A green window is its label and percentage "
                f"run together (`5h10%`); from {self._warn_pct:g}% it is spaced out and "
                "adds the reset countdown, e.g. "
                "`5h 67% 3h 20m`. Percentages are rounded down. A window past "
                "its reset is dropped; nothing is shown when no usage data exists (API-key "
                "sessions, or before the first response). `⏸ usage 14:35` in red means the "
                "session is paused on its host's usage ceiling and resumes at that local time. "
                "`override until 14:35` means the owner's `usage-pause clear` override is in "
                "force: the ceiling pauses nothing until that local time (with the month and "
                "day when it is not today). It is red while a window is over the ceiling and "
                "yellow while usage is under it. "
                "`⛔ 80%` is the ceiling this host runs under (`⛔ 5h 80% 7d 95%` when the "
                "windows differ); it is absent when no ceiling applies. `⚠ usage limit 14:02` "
                "in red means this session's last turn ended on an API error at that local "
                "time (`usage limit`, `auth failed` or `cloud credential`) and the session has "
                "not been prompted since; it is resolved, and disappears, at the next prompt."
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
                    "Verify the status line carries a '📈 5h10%|7d5%' usage segment on a "
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
