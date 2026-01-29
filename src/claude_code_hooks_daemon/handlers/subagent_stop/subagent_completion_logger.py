"""SubagentCompletionLoggerHandler - logs subagent completion events."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class SubagentCompletionLoggerHandler(Handler):
    """Log subagent completion events to a JSONL file.

    Records when subagents complete with timestamps for debugging and tracking.
    Non-terminal to allow normal completion processing.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal logger."""
        super().__init__(
            handler_id=HandlerID.SUBAGENT_COMPLETION_LOGGER,
            priority=Priority.SUBAGENT_COMPLETION_LOGGER,
            terminal=False,
            tags=[HandlerTag.LOGGING, HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Match all subagent stop events.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            Always True (log all subagent completions)
        """
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Log subagent completion to file.

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
                **hook_input,
            }

            # Write to JSONL file
            log_file = log_dir / "subagent_completions.jsonl"
            with log_file.open("a") as f:
                f.write(json.dumps(log_entry) + "\n")

        except OSError:
            # Silently ignore file write errors
            pass

        return HookResult(decision=Decision.ALLOW)
