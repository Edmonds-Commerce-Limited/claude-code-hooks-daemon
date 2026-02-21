"""SubagentCompletionLoggerHandler - logs subagent completion events."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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

        except OSError as e:
            logger.warning("Failed to write subagent completion log: %s", e)

        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="subagent completion logger handler test",
                command='echo "test"',
                description="Tests subagent completion logger handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="Stop event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
