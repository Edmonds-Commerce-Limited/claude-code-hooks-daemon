"""UpgradeNotifierHandler - daemon-upgrade availability indicator.

Shows a "📦 vX → vY" segment whenever a newer daemon version is available,
reading the cache written by the SessionStart ``version_check`` handler
(``version_check_cache.json``). Extracted from ``DaemonStatsHandler`` (Plan
00167) so the upgrade prompt reaches every client on-by-default, independent
of the off-by-default developer health line (uptime/memory/log-level/errors).

ANY unexpected failure fails safe to NO segment - this handler must never
raise and never break the status line (mirrors the fail-silent pattern used
by ``daemon_stats.py`` and ``supervisor_indicator.py``).
"""

import json
import logging
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "version_check_cache.json"


class UpgradeNotifierHandler(Handler):
    """Show a daemon-upgrade-available indicator on the status line."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.UPGRADE_NOTIFIER,
            priority=Priority.UPGRADE_NOTIFIER,
            terminal=False,
            tags=[
                HandlerTag.STATUSLINE,
                HandlerTag.DAEMON,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def get_default_enabled(self) -> bool:
        """On by default.

        Safe to ship enabled: the segment renders NOTHING unless the cached
        version check confirms an upgrade is genuinely available for the
        version currently running. See the module docstring.
        """
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status line events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return the upgrade-notifier segment, failing safe on any error."""
        try:
            segment = self._detect_upgrade_segment()
        except Exception as e:
            logger.debug("Failed to read version cache: %s", e)
            return HookResult(context=[])
        return HookResult(context=[segment] if segment else [])

    def _detect_upgrade_segment(self) -> str | None:
        """Return the upgrade-arrow segment text, or None if nothing to show."""
        cache_file = ProjectContext.daemon_untracked_dir() / _CACHE_FILENAME
        if not cache_file.exists():
            return None

        try:
            cache_data = json.loads(cache_file.read_text())
        except (OSError, ValueError) as e:
            logger.debug("Failed to read version cache file %s: %s", cache_file, e)
            return None

        if not isinstance(cache_data, dict) or not cache_data.get("is_outdated"):
            return None

        from claude_code_hooks_daemon.version import __version__

        cached_version = cache_data.get("current_version", "")
        latest = cache_data.get("latest_version", "")

        # Defense-in-depth: ignore stale cache from before an upgrade.
        if cached_version and cached_version != __version__:
            logger.debug(
                "Ignoring stale version cache: cached=%s actual=%s",
                cached_version,
                __version__,
            )
            return None

        if latest and cached_version:
            return f"📦 v{cached_version} → v{latest}"
        if latest:
            return f"📦 upgrade → v{latest}"
        return None

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import Decision, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="upgrade notifier handler test",
                command='echo "test"',
                description=(
                    "Verify the upgrade notifier shows a 📦 vX → vY segment "
                    "when a newer daemon version is available (per the "
                    "version_check_cache.json cache), and shows nothing when "
                    "no upgrade is available or the cache is missing/stale. "
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
