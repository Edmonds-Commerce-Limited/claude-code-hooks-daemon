"""Model and context percentage handler for status line.

Formats model name and color-coded context percentage using traffic light colors:
- Green (0-40%): Low usage, plenty of space
- Yellow (41-60%): Moderate usage
- Orange (61-80%): High usage, approaching limit
- Red (81-100%): Critical usage, near or at limit
"""

from typing import Any

from claude_code_hooks_daemon.core import Handler, HookResult


class ModelContextHandler(Handler):
    """Format model name and color-coded context percentage."""

    def __init__(self) -> None:
        super().__init__(
            name="status-model-context",
            priority=10,
            terminal=False,
            tags=["status", "display", "non-terminal"],
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
        model = hook_input.get("model", {}).get("display_name", "Claude")
        ctx_data = hook_input.get("context_window", {})
        used_pct = ctx_data.get("used_percentage", 0)

        # Color code by percentage (traffic light system)
        if used_pct <= 40:
            color = "\033[42m\033[30m"  # Green bg, black text
        elif used_pct <= 60:
            color = "\033[43m\033[30m"  # Yellow bg, black text
        elif used_pct <= 80:
            color = "\033[48;5;208m\033[30m"  # Orange bg, black text
        else:
            color = "\033[41m\033[97m"  # Red bg, white text
        reset = "\033[0m"

        # Format: "Model | Ctx: XX%"
        status = f"{model} | Ctx: {color}{used_pct:.1f}%{reset}"

        return HookResult(context=[status])
