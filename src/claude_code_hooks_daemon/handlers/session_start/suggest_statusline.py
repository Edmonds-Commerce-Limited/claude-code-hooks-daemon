"""Status line suggestion handler for SessionStart events.

Suggests setting up the daemon-based status line in .claude/settings.json
if not already configured. Provides example configuration for user reference.
"""

import json
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext

# Recommended statusLine.refreshInterval (seconds). Claude Code re-runs the
# status command on this timer in ADDITION to event-driven updates. The status
# line goes quiet when the session is idle — e.g. while a coordinator waits on a
# background agent — so without a timer the clock freezes and the multithread
# indicator (🧵 Y/X) under-counts idle sibling threads whose heartbeats have gone
# stale. 10s keeps both live at negligible cost (a cached daemon socket call).
# Docs: https://code.claude.com/docs/en/statusline (minimum is 1).
_RECOMMENDED_REFRESH_INTERVAL_S = 10


class SuggestStatusLineHandler(Handler):
    """Suggest setting up daemon-based statusline on session start."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUGGEST_STATUSLINE,
            priority=Priority.SUGGEST_STATUSLINE,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.WORKFLOW,
                HandlerTag.STATUSLINE,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def _is_resume_session(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a resumed session (transcript exists with content).

        Args:
            hook_input: SessionStart hook input

        Returns:
            True if resume, False if new session
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False

        try:
            path = Path(transcript_path)
            if not path.exists():
                return False

            # If file exists and has content (>100 bytes), it's a resume
            return path.stat().st_size > 100

        except (OSError, ValueError):
            return False

    def _is_statusline_configured(self) -> bool:
        """Check if status line is already configured in .claude/settings.json.

        Returns:
            True if configured, False otherwise
        """
        try:
            settings_file = ProjectContext.config_dir() / "settings.json"
            if not settings_file.exists():
                return False

            with open(settings_file) as f:
                settings = json.load(f)

            # Check if statusLine is configured
            return "statusLine" in settings

        except (OSError, json.JSONDecodeError, RuntimeError):
            # Can't check - assume not configured
            return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only suggest on NEW sessions when status line is NOT configured."""
        # Don't show on resume sessions
        if self._is_resume_session(hook_input):
            return False

        # Don't show if already configured
        if self._is_statusline_configured():
            return False

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
                '    "command": ".claude/hooks/status-line",',
                f'    "refreshInterval": {_RECOMMENDED_REFRESH_INTERVAL_S}',
                "  }",
                "}",
                "```",
                "",
                "The status line shows: model name, context usage %, git branch, and daemon health.",
                "",
                (
                    f"`refreshInterval` ({_RECOMMENDED_REFRESH_INTERVAL_S}s) re-runs the status "
                    "line on a timer as well as on events, so the clock stays current and the "
                    "multithread indicator (🧵 Y/X) keeps counting live threads even while the "
                    "session is idle waiting on a background agent."
                ),
            ]
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="suggest statusline handler test",
                command='echo "test"',
                description="Tests suggest statusline handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
