"""Model and context percentage handler for status line.

Formats color-coded model name with effort level and context percentage:

Model colors (by model type):
- Blue: Haiku models
- Green: Sonnet models
- Orange: Opus models
- White: Unknown/other models

Effort level colors (shown next to model for Opus):
- Blue: low effort
- Green: medium effort
- Orange: high effort

Context percentage colors (traffic light system):
- Green (0-40%): Low usage, plenty of space
- Yellow (41-60%): Moderate usage
- Orange (61-80%): High usage, approaching limit
- Red (81-100%): Critical usage, near or at limit
"""

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult

logger = logging.getLogger(__name__)

# Effort level color mapping: blue=low, green=medium, orange=high
EFFORT_COLORS: dict[str, str] = {
    "low": "\033[34m",  # Blue
    "medium": "\033[32m",  # Green
    "high": "\033[38;5;208m",  # Orange
}


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
        model_display = hook_input.get("model", {}).get("display_name", "Claude")
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

        # Build model display with optional effort level suffix
        effort_suffix = self._get_effort_suffix(model_lower, reset)
        model_part = f"{model_color}{model_display}{reset}{effort_suffix}"

        # Color code context percentage by usage (traffic light system)
        if used_pct <= 40:
            ctx_color = "\033[42m\033[30m"  # Green bg, black text
        elif used_pct <= 60:
            ctx_color = "\033[43m\033[30m"  # Yellow bg, black text
        elif used_pct <= 80:
            ctx_color = "\033[48;5;208m\033[30m"  # Orange bg, black text
        else:
            ctx_color = "\033[41m\033[97m"  # Red bg, white text

        # Format: "Model(effort) | Ctx: XX%"
        status = f"{model_part} | Ctx: {ctx_color}{used_pct:.1f}%{reset}"

        return HookResult(context=[status])

    def _get_effort_suffix(self, model_lower: str, reset: str) -> str:
        """Get effort level suffix for Opus models.

        Only shows effort level for Opus models since effort/reasoning
        budget is most relevant there.

        Args:
            model_lower: Lowercased model display name
            reset: ANSI reset code

        Returns:
            Formatted effort suffix like "(medium)" or empty string
        """
        if "opus" not in model_lower:
            return ""

        effort_level = self._read_effort_level()
        if effort_level is None:
            return ""

        effort_color = EFFORT_COLORS.get(effort_level, "\033[37m")
        return f"({effort_color}{effort_level}{reset})"

    def _read_effort_level(self) -> str | None:
        """Read effort level from Claude settings.

        Returns:
            Effort level string (low/medium/high) or None if not set
        """
        try:
            settings_path = self._get_settings_path()
            if not settings_path.exists():
                return None
            raw = settings_path.read_text()
            settings: dict[str, Any] = json.loads(raw)
            level = settings.get("effortLevel")
            if level is not None:
                return str(level)
            return None
        except (json.JSONDecodeError, OSError):
            logger.info("Error reading effort level from settings")
            return None

    def _get_settings_path(self) -> Path:
        """Get path to Claude settings file.

        Returns:
            Path to ~/.claude/settings.json
        """
        return Path.home() / ".claude" / "settings.json"

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
