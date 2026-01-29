"""NotificationLoggerHandler - logs all notifications to a file."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class NotificationLoggerHandler(Handler):
    """Log all notification events to a JSONL file.

    Records all notifications with timestamps for debugging and audit purposes.
    Non-terminal to allow normal notification processing.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal logger."""
        super().__init__(
            handler_id=HandlerID.NOTIFICATION_LOGGER,
            priority=Priority.NOTIFICATION_LOGGER,
            terminal=False,
            tags=[HandlerTag.LOGGING, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Match all notification events.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            Always True (log all notifications)
        """
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Log notification to file.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with allow decision (silent logging)
        """
        try:
            # Create log directory
            log_dir = Path("untracked/logs/hooks")
            log_dir.mkdir(parents=True, exist_ok=True)

            # Build log entry
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                **hook_input,  # Include all notification fields
            }

            # Write to JSONL file (one JSON object per line)
            log_file = log_dir / "notifications.jsonl"
            with log_file.open("a") as f:
                f.write(json.dumps(log_entry) + "\n")

        except OSError:
            # Silently ignore file write errors (don't block on logging failures)
            pass

        return HookResult(decision=Decision.ALLOW)
