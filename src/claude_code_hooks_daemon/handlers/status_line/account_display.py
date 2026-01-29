"""Account display handler for status line.

Reads the user's Claude account name from ~/.claude/.last-launch.conf
and displays it in the status line.
"""

import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Handler, HookResult


class AccountDisplayHandler(Handler):
    """Display Claude account username in status line."""

    def __init__(self) -> None:
        super().__init__(
            name="status-account-display",
            priority=5,
            terminal=False,
            tags=["status", "display", "non-terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Extract and format account username.

        Args:
            hook_input: Status event input (not used)

        Returns:
            HookResult with username in context list, or empty list if unavailable
        """
        try:
            conf_path = Path.home() / ".claude" / ".last-launch.conf"
            if not conf_path.exists():
                return HookResult(context=[])

            content = conf_path.read_text()
            match = re.search(r'LAST_TOKEN="([^"]*)"', content)
            if not match:
                return HookResult(context=[])

            username = match.group(1)
            return HookResult(context=[f"{username} |"])

        except Exception:
            # Silent fail - don't break status line for account display issues
            return HookResult(context=[])
