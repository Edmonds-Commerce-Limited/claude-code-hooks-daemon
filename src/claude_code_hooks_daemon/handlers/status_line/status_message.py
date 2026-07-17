"""StatusMessageHandler - render transient supervisor -> status-line messages.

The ccy PTY supervisor (``claude-supervise.py``) can post short, TTL-bounded
notices to a shared message file (``supervise/status-message.json``) via its
``StatusMessagePoster``. This handler reads that file on every status render and
shows the message, auto-omitting it once expired. The Ctrl+Z "ignored" notice
(Plan 00173) is its first consumer; the channel is general — future supervisor
events can post through it too.

THREAD / PROCESS SAFETY (first-class concern — mirrors the note in
``claude-supervise.py`` and this package's ``CLAUDE.md``): the message file is
WRITTEN by the supervisor (a separate process, possibly several threads) and
READ here in the daemon on every render, while multiple Claude sessions can
share one daemon. The writer uses atomic-replace (temp file + ``os.replace``),
so a reader always sees a COMPLETE file; this reader is defensive and
FAIL-SILENT — an absent, malformed, non-dict, or unexpectedly-unreadable file
renders NO segment and never raises (a broken status line would be worse than a
missing message). That fail-silent contract is why the handler is safe on by
default: a project that never runs the supervisor simply shows nothing.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest

logger = logging.getLogger(__name__)

# These MUST match the supervisor's own constants in
# ``.claude/ccy/claude-supervise.py`` (``_LOG_SUBDIRECTORY`` /
# ``_STATUS_MESSAGE_FILENAME``) — the supervisor writes the message file there
# and this handler must read the exact same path.
_MESSAGE_SUBDIRECTORY = "supervise"
_MESSAGE_FILENAME = "status-message.json"


class StatusMessageHandler(Handler):
    """Render a transient supervisor message from the shared message file."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.STATUS_MESSAGE,
            priority=Priority.STATUS_MESSAGE,
            terminal=False,
            tags=[
                HandlerTag.STATUSLINE,
                HandlerTag.DISPLAY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def get_default_enabled(self) -> bool:
        """On by default.

        Safe to ship enabled because an absent/expired/malformed message file
        renders NOTHING — a project that never runs the ccy supervisor shows no
        segment at all; a supervised project sees a notice only while one is
        live and unexpired.
        """
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status line events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return the message segment, failing silent on any error."""
        try:
            segment = self._render()
        except Exception as e:
            # Fail silent: a broken status line is worse than a missing message.
            logger.debug("Failed to render status message: %s", e)
            return HookResult(context=[])
        if segment is None:
            return HookResult(context=[])
        return HookResult(context=[segment])

    def _render(self) -> str | None:
        """Resolve the current message segment, or None when nothing to show."""
        message = self._read_message(self._message_file_path())
        if message is None:
            return None
        text = message.get("text")
        expires_at = message.get("expires_at")
        if not isinstance(text, str) or not text.strip():
            return None
        # bool is a subclass of int — exclude it so a stray `true` is not a time.
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            return None
        if self._now() >= expires_at:
            return None
        return f"| {text}"

    def _now(self) -> float:
        """Current wall-clock epoch (indirected for deterministic testing).

        Wall clock (not monotonic) because ``expires_at`` is written by the
        supervisor as ``time.time() + ttl`` — both sides must use the same clock.
        """
        return time.time()

    def _message_file_path(self) -> Path:
        """Return the path to the supervisor's transient message file."""
        return ProjectContext.daemon_untracked_dir() / _MESSAGE_SUBDIRECTORY / _MESSAGE_FILENAME

    def _read_message(self, path: Path) -> dict[str, Any] | None:
        """Read and parse the message file, or None if absent/unusable."""
        if not path.exists():
            return None
        try:
            data: Any = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            logger.debug("Failed to read status message file %s: %s", path, e)
            return None
        if not isinstance(data, dict):
            return None
        return data

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="status message handler test",
                command='echo "test"',
                description=(
                    "Verify the status message handler renders a transient "
                    "supervisor notice (e.g. the Ctrl+Z 'ignored' message) when "
                    "the shared message file is present and unexpired, and shows "
                    "no segment when it is absent, expired, or malformed. "
                    "Confirmed active by the daemon loading without errors."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            )
        ]
