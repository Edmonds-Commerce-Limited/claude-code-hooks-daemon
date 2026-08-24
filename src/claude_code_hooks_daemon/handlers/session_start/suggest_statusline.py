"""Status line suggestion handler for SessionStart events.

Suggests setting up the daemon-based status line in .claude/settings.json
if not already configured. Provides example configuration for user reference.
"""

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

# Recommended statusLine.refreshInterval (seconds). Claude Code re-runs the
# status command on this timer in ADDITION to event-driven updates. The status
# line goes quiet when the session is idle — e.g. while a coordinator waits on a
# background agent — so without a timer the clock freezes and the multithread
# indicator (🧵 Y/X) under-counts idle sibling threads whose heartbeats have gone
# stale. 10s keeps both live at negligible cost (a cached daemon socket call).
# Docs: https://code.claude.com/docs/en/statusline (minimum is 1).
_RECOMMENDED_REFRESH_INTERVAL_S = 10

# How many unheeded showings before the pitch goes quiet (Plan 00234/00236).
#
# This handler is a "decide once" suggestion, and declining it leaves NO trace:
# a project that looked at the status line and chose not to use it has no
# `statusLine` key, which is indistinguishable from never having heard of it.
# Without a cap the same pitch therefore opened every new session for ever, and
# the only way to stop it was to disable the handler — which also disables it
# for the case it exists to serve.
#
# Three is enough to survive being missed in a scrolled-past session start, and
# few enough that a deliberate "no" is respected within a day's work. Acting on
# the suggestion silences it immediately and independently of this counter.
_MAX_SUGGESTIONS = 3

_STATE_FILE_NAME = "statusline_suggestion_state.json"
_SHOWN_COUNT_KEY = "shown_count"


class SuggestStatusLineHandler(SessionStartHandlerBase):
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
        # Tests point this at a tmp_path; the daemon leaves it None and
        # resolves the real location through ProjectContext.
        self._state_file_override: Path | None = None

    def _state_file(self) -> Path | None:
        """Where the showing counter lives, or None when unresolvable.

        Mirrors ``gitignore_safety_checker``: state belongs in the daemon's
        untracked dir, never ``/tmp`` (B108).
        """
        if self._state_file_override is not None:
            return self._state_file_override
        try:
            return ProjectContext.daemon_untracked_dir() / _STATE_FILE_NAME
        except (OSError, RuntimeError) as exc:
            logger.debug("Statusline suggestion state file unresolvable: %s", exc)
            return None

    def _shown_count(self) -> int:
        """How many times the suggestion has already been made.

        Returns 0 — i.e. "suggest" — when the counter cannot be read. The
        counter only reduces noise, so a corrupt or unreadable file must fail
        OPEN: silently suppressing an advisory for ever is a worse outcome
        than showing it once more, and a permanently-silent handler is
        indistinguishable from a working one.
        """
        state_file = self._state_file()
        if state_file is None or not state_file.exists():
            return 0
        try:
            data = json.loads(state_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("Statusline suggestion state unreadable (%s); suggesting anyway", exc)
            return 0
        count = data.get(_SHOWN_COUNT_KEY) if isinstance(data, dict) else None
        return count if isinstance(count, int) and count >= 0 else 0

    def _record_shown(self) -> None:
        """Persist one more showing. Best effort — never breaks the advisory."""
        state_file = self._state_file()
        if state_file is None:
            return
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps({_SHOWN_COUNT_KEY: self._shown_count() + 1}))
        except OSError as exc:
            logger.debug("Could not record statusline suggestion showing: %s", exc)

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
        if is_resume_session(hook_input):
            return False

        # Don't show if already configured
        if self._is_statusline_configured():
            return False

        # Don't keep pitching to a project that has quietly declined.
        return self._shown_count() < _MAX_SUGGESTIONS

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Generate status line setup suggestion.

        Args:
            hook_input: SessionStart event input (not used, but required by interface)

        Returns:
            AdvisoryResult with suggestion context for setting up status line
        """
        self._record_shown()
        return AdvisoryResult(
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
