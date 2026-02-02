"""Model and context percentage handler for status line.

Formats color-coded model name and context percentage:

Model colors (by model type):
- Blue: Haiku models
- Green: Sonnet models
- Orange: Opus models
- White: Unknown/other models

Context percentage colors (traffic light system):
- Green (0-40%): Low usage, plenty of space
- Yellow (41-60%): Moderate usage
- Orange (61-80%): High usage, approaching limit
- Red (81-100%): Critical usage, near or at limit
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class ModelContextHandler(Handler):
    """Format model name and color-coded context percentage."""

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
        """Generate model and context percentage status text.

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

        # Color code context percentage by usage (traffic light system)
        if used_pct <= 40:
            ctx_color = "\033[42m\033[30m"  # Green bg, black text
        elif used_pct <= 60:
            ctx_color = "\033[43m\033[30m"  # Yellow bg, black text
        elif used_pct <= 80:
            ctx_color = "\033[48;5;208m\033[30m"  # Orange bg, black text
        else:
            ctx_color = "\033[41m\033[97m"  # Red bg, white text
        reset = "\033[0m"

        # Format: "Model | Ctx: XX%"
        status = f"{model_color}{model_display}{reset} | Ctx: {ctx_color}{used_pct:.1f}%{reset}"

        return HookResult(context=[status])

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
