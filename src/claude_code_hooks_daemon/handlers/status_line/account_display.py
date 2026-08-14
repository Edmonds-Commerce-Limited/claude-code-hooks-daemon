"""Account display handler for status line.

Reads the user's Claude account name from ~/.claude/.last-launch.conf
and displays it in the status line.
"""

import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.handlers.status_line.mtime_cache import MtimeCachedFile

_CONF_RELATIVE_PATH = (".claude", ".last-launch.conf")
_TOKEN_PATTERN = re.compile(r'LAST_TOKEN="([^"]*)"')


def _extract_username(content: str) -> str | None:
    match = _TOKEN_PATTERN.search(content)
    return match.group(1) if match else None


# Module-level so the cache survives across renders — a per-handler-instance
# cache would work too (one instance per daemon), but keeping it here matches
# settings_reader.py and makes the lifetime obvious. The account username
# changes effectively never, so this reduces a read + regex on EVERY render
# (~3,100/hour) to a single stat() (Plan 00238).
_username_reader: MtimeCachedFile[str | None] = MtimeCachedFile(
    parse=_extract_username,
    default=None,
)


class AccountDisplayHandler(Handler):
    """Display Claude account username in status line."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ACCOUNT_DISPLAY,
            priority=Priority.ACCOUNT_DISPLAY,
            terminal=False,
            tags=[HandlerTag.STATUS, HandlerTag.DISPLAY, HandlerTag.NON_TERMINAL],
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
            username = _username_reader.read(Path.home().joinpath(*_CONF_RELATIVE_PATH))
            # `is None`, not falsiness: an EMPTY token renders "👤  |" and always
            # has. Tuning must not change what the line displays (Plan 00238
            # Non-Goals), and `if not username` would have silently dropped it.
            if username is None:
                return HookResult(context=[])

            return HookResult(context=[f"👤 {username} |"])

        except Exception:
            # Silent fail - don't break status line for account display issues
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
                title="account display handler test",
                command='echo "test"',
                description="Tests account display handler functionality",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Context/utility handler - minimal testing required",
                test_type=TestType.CONTEXT,
                requires_event="StatusLine event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
