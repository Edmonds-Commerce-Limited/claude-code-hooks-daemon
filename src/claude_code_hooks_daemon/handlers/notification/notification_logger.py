"""NotificationLoggerHandler - logs all notifications to a file."""

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.retention import cap_log_file

# Plan 00181: this append-only JSONL had no bound (408 KB observed, never
# rotated). Cap it after each write; on breach keep the newest half so a busy
# session does not rewrite the whole file on every append. Config-overridable
# via ``options.max_log_bytes`` (registry injects it as ``self._max_log_bytes``).
_DEFAULT_MAX_LOG_BYTES = 5 * 1024 * 1024


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
        # Plan 00181 retention budget (config-overridable via options.*).
        self._max_log_bytes = _DEFAULT_MAX_LOG_BYTES

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
            # Resolve under daemon's untracked dir so logs land in the project
            # regardless of process CWD (regression fix: Issue 3).
            log_dir = ProjectContext.daemon_untracked_dir() / "logs" / "hooks"
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

            # Plan 00181: bound the append-only log (keep newest half on breach).
            cap_log_file(
                log_file, max_bytes=self._max_log_bytes, retain_bytes=self._max_log_bytes // 2
            )

        except RuntimeError as e:
            # ProjectContext not initialised — happens in the default-config /
            # standalone entry-point branch where no .claude/hooks-daemon.yaml
            # is present. Silently skip logging rather than fail the dispatch.
            logger.warning("Skipping notification log (no project context): %s", e)
        except OSError as e:
            logger.warning("Failed to write notification log: %s", e)

        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Notification Logger."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Notification logging",
                command="Notification event",
                description="Logs notification events",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"notification"],
                safety_notes="Logging only",
                test_type=TestType.CONTEXT,
                requires_event="Notification event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
