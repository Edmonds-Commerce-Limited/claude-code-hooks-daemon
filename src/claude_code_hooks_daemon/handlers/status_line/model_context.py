"""Model and context percentage handler for status line.

Formats color-coded model name with effort level signal bars and context percentage:

Format: 🤖 Model ▌▌▌ | ◔ XX%

Model colors (by model type):
- Blue: Haiku models
- Green: Sonnet models
- Orange: Opus models
- White: Unknown/other models

Effort level signal bars (shown for Claude 4+ models):
- Low:    ▌░░  (one bar orange,  two dim grey)
- Medium: ▌▌░  (two bars orange, one dim grey)
- High:   ▌▌▌  (all three bars orange)

Matches Claude Code's own ▌▌▌ bar style - always orange active, grey inactive.

Effort level source (in priority order):
1. effortLevel key in ~/.claude/settings.json (set explicitly via /model)
2. Default "high" for Claude 4+ models (daemon default — optimal_config_checker enforces high)
3. No bars for pre-4.x models (effort feature not available)

Context usage (quarter circle icons with color-coded percentages):

Standard thresholds (Sonnet, Haiku, etc. — 200k context):
- ◔ Green (0-25%): 1/4 filled - Low usage, plenty of space
- ◑ Yellow (26-50%): Right half filled - Moderate usage
- ◕ Orange (51-75%): 3/4 filled - High usage, approaching limit
- ● Red (76-100%): Full circle - Critical usage, near or at limit

Opus thresholds (1M context — tighter because 400k+ tokens is already huge):
- ◔ Green (0-14%): Low usage
- ◑ Yellow (15-29%): Moderate — already 150-300k tokens in flight
- ◕ Orange (30-39%): High — 300-400k tokens, diminishing returns territory
- ● Red (40-100%): Critical — 400k+ tokens is an enormous context to push back
  and forth per API call. Quality degrades, latency spikes, and costs balloon.
  Even if the window technically fits more, you should compact or start fresh.

Opus thresholds are configurable via handler options:
  opus_context_orange_pct: 30  (default)
  opus_context_red_pct: 40     (default)
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)

# Active effort bar color (orange) - matches Claude Code UI
_EFFORT_ACTIVE = "\033[38;5;208m"

# Signal bar character - three identical left-half blocks matching Claude Code UI (▌▌▌)
_EFFORT_BAR = "▌"

# ANSI dim grey for unlit effort bars
_EFFORT_DIM = "\033[2;37m"

# Daemon default effort level when effortLevel absent from settings.
# Claude Code defaults to "medium", but daemon users expect "high" because
# optimal_config_checker enforces high effort. When CC overwrites the settings
# file and removes effortLevel, we show "high" rather than misleading "medium".
_EFFORT_DEFAULT = "high"

# Minimum Claude major version that supports effort configuration
_EFFORT_MIN_MAJOR_VERSION = 4

# Opus large-context thresholds (configurable via handler options).
# Opus has a 1M token context window. At 30% that's already 300k tokens and at
# 40% it's 400k — an enormous payload to shuttle per API round-trip. Quality
# degrades from noise, latency spikes, and costs balloon well before the window
# is technically full. These tighter defaults nudge the user to compact early.
_OPUS_CONTEXT_ORANGE_PCT = 30
_OPUS_CONTEXT_RED_PCT = 40

# Regex to extract major version from Claude 4+ model IDs
# Matches: claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5-20251001
# Does NOT match Claude 3.x format: claude-3-5-sonnet-20241022
_MODEL_VERSION_PATTERN = re.compile(r"claude-(?:opus|sonnet|haiku)-(\d+)-")


class ModelContextHandler(Handler):
    """Format model name with effort level and color-coded context percentage."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MODEL_CONTEXT,
            priority=Priority.MODEL_CONTEXT,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
        )
        # Opus large-context thresholds — overridable via config options
        self._opus_context_orange_pct: int = _OPUS_CONTEXT_ORANGE_PCT
        self._opus_context_red_pct: int = _OPUS_CONTEXT_RED_PCT

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Generate model, effort level, and context percentage status text.

        Args:
            hook_input: Status event input with model and context_window data

        Returns:
            HookResult with formatted status text in context list
        """
        # Extract data with safe defaults
        model_data = hook_input.get("model", {})
        model_display = model_data.get("display_name", "Claude")
        model_id = model_data.get("id", "")
        ctx_data = hook_input.get("context_window", {})
        used_pct = ctx_data.get("used_percentage") or 0

        # Color code model name by model type
        model_lower = model_display.lower()
        if "haiku" in model_lower:
            model_color = "\033[34m"  # Blue for Haiku
        elif "sonnet" in model_lower:
            model_color = "\033[32m"  # Green for Sonnet
        elif "opus" in model_lower:
            model_color = "\033[38;5;208m"  # Orange for Opus
        else:
            model_color = "\033[37m"  # White for unknown

        reset = "\033[0m"

        # Build model display with optional effort signal bars
        effort_suffix = self._get_effort_suffix(model_id, reset)
        model_part = f"🤖 {model_color}{model_display}{reset}{effort_suffix}"

        # Get quarter circle icon and colors based on usage threshold
        is_opus = "opus" in model_lower
        ctx_icon, icon_color, pct_color = self._get_context_icon_and_color(
            used_pct, is_opus=is_opus
        )

        # Format: "🤖 Model ▌▌▌ | ◔ XX%" with colored icon and percentage
        status = f"{model_part} | {icon_color}{ctx_icon}{reset} {pct_color}{used_pct:.1f}%{reset}"

        return HookResult(context=[status])

    def _get_effort_suffix(self, model_id: str, reset: str) -> str:
        """Get effort level signal bars for Claude 4+ models.

        Shows three signal bars (▌▌▌) where active bars are orange, inactive dim grey.
        Reads effortLevel from settings; defaults to "medium" for Claude 4+ when unset.

        Args:
            model_id: Model ID string (e.g. "claude-sonnet-4-6")
            reset: ANSI reset code

        Returns:
            Formatted effort bars like " ▌▌▌" or empty string for unsupported models
        """
        effort_level = self._read_effort_level(model_id)
        if effort_level is None:
            return ""

        if effort_level == "low":
            bars = f"{_EFFORT_ACTIVE}{_EFFORT_BAR}{_EFFORT_DIM}{_EFFORT_BAR}{_EFFORT_BAR}{reset}"
        elif effort_level == "medium":
            bars = f"{_EFFORT_ACTIVE}{_EFFORT_BAR}{_EFFORT_BAR}{_EFFORT_DIM}{_EFFORT_BAR}{reset}"
        else:
            # High (or unknown): all bars orange
            bars = f"{_EFFORT_ACTIVE}{_EFFORT_BAR}{_EFFORT_BAR}{_EFFORT_BAR}{reset}"

        return f" {bars}"

    def _read_effort_level(self, model_id: str) -> str | None:
        """Determine effort level for the given model.

        Priority:
        1. effortLevel from ~/.claude/settings.json (explicitly set via /model)
        2. _EFFORT_DEFAULT ("high") for Claude 4+ models (daemon optimal default)
        3. None for pre-4.x models (effort not supported)

        Args:
            model_id: Model ID string (e.g. "claude-sonnet-4-6")

        Returns:
            Effort level string (low/medium/high) or None if not applicable
        """
        settings: dict[str, Any] = {}
        try:
            settings_path = self._get_settings_path()
            if settings_path.exists():
                raw = settings_path.read_text()
                settings = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cannot read effort level from settings: %s", exc)
            # settings stays empty — fall through to default logic below

        level = settings.get("effortLevel")
        if level is not None:
            return str(level)

        # Not in settings - use default "high" for Claude 4+ (daemon optimal)
        if self._model_supports_effort(model_id):
            return _EFFORT_DEFAULT

        return None

    def _model_supports_effort(self, model_id: str) -> bool:
        """Check if model supports effort configuration (Claude 4+).

        Claude 4+ model IDs follow: claude-{family}-{major}-{minor}
        e.g. claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5-20251001

        Args:
            model_id: Model ID string to check

        Returns:
            True if model is Claude 4 or later
        """
        match = _MODEL_VERSION_PATTERN.search(model_id)
        if match:
            major = int(match.group(1))
            return major >= _EFFORT_MIN_MAJOR_VERSION
        return False

    def _get_settings_path(self) -> Path:
        """Get path to Claude settings file.

        Returns:
            Path to ~/.claude/settings.json
        """
        return Path.home() / ".claude" / "settings.json"

    def _get_context_icon_and_color(
        self, used_pct: float, *, is_opus: bool = False
    ) -> tuple[str, str, str]:
        """Get quarter circle icon, icon color, and percentage background color.

        Opus models use tighter thresholds because their 1M context window means
        even moderate percentages represent enormous token counts (300k-400k+).
        At that scale, quality degrades, latency spikes, and costs balloon —
        the user should compact well before hitting 50%.

        Args:
            used_pct: Context usage percentage (0-100)
            is_opus: Whether the active model is Opus (uses tighter thresholds)

        Returns:
            Tuple of (icon, icon_fg_color, percentage_bg_color)
        """
        if is_opus:
            return self._opus_context_icon_and_color(used_pct)

        if used_pct <= 25:
            return "◔", "\033[32m", "\033[42m\033[30m"  # 1/4 filled, green fg + bg
        elif used_pct <= 50:
            return "◑", "\033[33m", "\033[43m\033[30m"  # Right half, yellow fg + bg
        elif used_pct <= 75:
            return "◕", "\033[38;5;208m", "\033[48;5;208m\033[30m"  # 3/4, orange fg + bg
        else:
            return "●", "\033[31m", "\033[41m\033[97m"  # Full, red fg + bg

    def _opus_context_icon_and_color(self, used_pct: float) -> tuple[str, str, str]:
        """Opus-specific context thresholds for 1M token window.

        Uses tighter bands than standard models. The orange and red thresholds
        are configurable via handler options (opus_context_orange_pct,
        opus_context_red_pct). The yellow threshold is derived as half of orange.

        Args:
            used_pct: Context usage percentage (0-100)

        Returns:
            Tuple of (icon, icon_fg_color, percentage_bg_color)
        """
        orange_pct = self._opus_context_orange_pct
        red_pct = self._opus_context_red_pct
        # Yellow band starts at half of orange (e.g. 30 -> 15)
        yellow_pct = orange_pct // 2

        if used_pct < yellow_pct:
            return "◔", "\033[32m", "\033[42m\033[30m"  # Green
        elif used_pct < orange_pct:
            return "◑", "\033[33m", "\033[43m\033[30m"  # Yellow
        elif used_pct < red_pct:
            return "◕", "\033[38;5;208m", "\033[48;5;208m\033[30m"  # Orange
        else:
            return "●", "\033[31m", "\033[41m\033[97m"  # Red

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="model context handler test",
                command='echo "test"',
                description="Tests model context handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
