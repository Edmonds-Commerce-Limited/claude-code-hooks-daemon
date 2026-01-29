"""Status line suggestion handler for SessionStart events.

Suggests setting up the daemon-based status line in .claude/settings.json
if not already configured. Provides example configuration for user reference.
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult


class SuggestStatusLineHandler(Handler):
    """Suggest setting up daemon-based statusline on session start."""

    def __init__(self) -> None:
        super().__init__(
            name="suggest-statusline",
            priority=Priority.SUGGEST_STATUSLINE,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.WORKFLOW, HandlerTag.STATUSLINE, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always suggest (Claude will check if already configured)."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Generate status line setup suggestion.

        Args:
            hook_input: SessionStart event input (not used, but required by interface)

        Returns:
            HookResult with suggestion context for setting up status line
        """
        return HookResult(
            context=[
                "💡 **Status Line Available**: This project has a daemon-based status line.",
                "",
                "To enable it, check if `.claude/settings.json` has a `statusLine` configuration.",
                "If not configured, consider adding:",
                "```json",
                "{",
                '  "statusLine": {',
                '    "type": "command",',
                '    "command": ".claude/hooks/status-line"',
                "  }",
                "}",
                "```",
                "",
                "The status line shows: model name, context usage %, git branch, and daemon health.",
            ]
        )
