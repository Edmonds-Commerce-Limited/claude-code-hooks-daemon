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
2. Default "high" for Claude 4+ models (Claude Code default, not written to settings)
3. No bars for pre-4.x models (effort feature not available)

Context usage (quarter circle icons with color-coded percentages):
- ◔ Green (0-25%): 1/4 filled - Low usage, plenty of space
- ◑ Yellow (26-50%): Right half filled - Moderate usage
- ◕ Orange (51-75%): 3/4 filled - High usage, approaching limit
- ● Red (76-100%): Full circle - Critical usage, near or at limit
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

# Claude Code default effort level when effortLevel absent from settings
_EFFORT_DEFAULT = "high"

# Minimum Claude major version that supports effort configuration
_EFFORT_MIN_MAJOR_VERSION = 4

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
        ctx_icon, icon_color, pct_color = self._get_context_icon_and_color(used_pct)

        # Format: "🤖 Model ▌▌▌ | ◔ XX%" with colored icon and percentage
        status = f"{model_part} | {icon_color}{ctx_icon}{reset} {pct_color}{used_pct:.1f}%{reset}"

        return HookResult(context=[status])

    def _get_effort_suffix(self, model_id: str, reset: str) -> str:
        """Get effort level signal bars for Claude 4+ models.

        Shows three signal bars (▌▌▌) where active bars are orange, inactive dim grey.
        Reads effortLevel from settings; defaults to "high" for Claude 4+ when unset.

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
        2. _EFFORT_DEFAULT ("high") for Claude 4+ models (Claude Code default)
        3. None for pre-4.x models (effort not supported)

        Args:
            model_id: Model ID string (e.g. "claude-sonnet-4-6")

        Returns:
            Effort level string (low/medium/high) or None if not applicable
        """
        try:
            settings_path = self._get_settings_path()
            settings: dict[str, Any] = {}
            if settings_path.exists():
                raw = settings_path.read_text()
                settings = json.loads(raw)

            level = settings.get("effortLevel")
            if level is not None:
                return str(level)

            # Not in settings - use default "high" for Claude 4+ (not written when default)
            if self._model_supports_effort(model_id):
                return _EFFORT_DEFAULT

            return None
        except (json.JSONDecodeError, OSError):
            logger.info("Error reading effort level from settings")
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

    def _get_context_icon_and_color(self, used_pct: float) -> tuple[str, str, str]:
        """Get quarter circle icon, icon color, and percentage background color.

        Args:
            used_pct: Context usage percentage (0-100)

        Returns:
            Tuple of (icon, icon_fg_color, percentage_bg_color)
        """
        if used_pct <= 25:
            return "◔", "\033[32m", "\033[42m\033[30m"  # 1/4 filled, green fg + bg
        elif used_pct <= 50:
            return "◑", "\033[33m", "\033[43m\033[30m"  # Right half, yellow fg + bg
        elif used_pct <= 75:
            return "◕", "\033[38;5;208m", "\033[48;5;208m\033[30m"  # 3/4, orange fg + bg
        else:
            return "●", "\033[31m", "\033[41m\033[97m"  # Full, red fg + bg

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

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
            ),
        ]
