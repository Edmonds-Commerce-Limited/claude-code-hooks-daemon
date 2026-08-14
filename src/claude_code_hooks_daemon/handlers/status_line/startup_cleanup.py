"""Startup cleanup status handler.

Shows a brief 🧹 indicator after daemon startup when stale files were cleaned.
Disappears after 30 seconds so it doesn't clutter the status line permanently.
"""

import json
import logging
import time
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.handlers.status_line.mtime_cache import MtimeCachedFile

logger = logging.getLogger(__name__)

_STATUS_FILENAME = "cleanup_status.json"

# How long (seconds) to show the startup indicator after daemon start
_DISPLAY_WINDOW_SECONDS = 30

# Transition point between "starting" icon and "result" message
_STARTUP_PHASE_SECONDS = 5

_TIMESTAMP_FIELD = "timestamp"
_COUNT_FIELD = "count"
_MISSING_TIMESTAMP = 0.0
_MISSING_COUNT = 0


def _parse_status(content: str) -> dict[str, Any]:
    """Parse the cleanup status document, rejecting anything but an object.

    A valid-JSON-but-not-an-object document (``[1,2,3]``) used to parse fine and
    then raise ``AttributeError`` on ``.get`` — which the caller's
    ``OSError/JSONDecodeError/KeyError`` guard did not catch, so it escaped into
    the render. Rejecting it here turns that into the fail-silent default.
    """
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("cleanup status is not a JSON object")
    result: dict[str, Any] = parsed
    return result


# ``cleanup_status.json`` is written ONCE per daemon start and read on every
# render thereafter — and after the 30-second window it can never produce a
# segment again. The gate keeps the stat() (a re-``start`` against a live
# daemon rewrites the file, and that must still display) and drops the read +
# parse (Plan 00238).
_status_reader: MtimeCachedFile[dict[str, Any]] = MtimeCachedFile(
    parse=_parse_status,
    default={},
)


class StartupCleanupHandler(Handler):
    """Show 🧹 briefly after daemon startup to indicate stale-file cleanup ran."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.STARTUP_CLEANUP,
            priority=Priority.STARTUP_CLEANUP,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DAEMON, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Show cleanup indicator briefly after daemon startup.

        - First 5 seconds:  | 🧹  (startup phase — brush icon only)
        - 5-30 seconds, files cleaned: | 🧹 N stale  (result phase)
        - After 30 seconds: nothing

        Returns:
            HookResult with cleanup context, or empty if outside display window
        """
        try:
            status_file = ProjectContext.daemon_untracked_dir() / _STATUS_FILENAME
            data = _status_reader.read(status_file)
            timestamp: float = data.get(_TIMESTAMP_FIELD, _MISSING_TIMESTAMP)
            count: int = data.get(_COUNT_FIELD, _MISSING_COUNT)
            elapsed = time.time() - timestamp

            if elapsed < _STARTUP_PHASE_SECONDS:
                return HookResult(context=["| 🧹"])
            elif elapsed < _DISPLAY_WINDOW_SECONDS and count > 0:
                return HookResult(context=[f"| 🧹 {count} stale"])

        except (OSError, RuntimeError) as e:
            # The read itself is fail-silent (see MtimeCachedFile); what can
            # still raise here is resolving the daemon's untracked dir.
            logger.debug("Failed to read cleanup status: %s", e)

        return HookResult(context=[])

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
                title="startup cleanup handler test",
                command='echo "test"',
                description="Tests startup cleanup statusline handler",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler — minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
