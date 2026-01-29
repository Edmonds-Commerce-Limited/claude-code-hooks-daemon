"""Daemon statistics handler for status line.

Shows daemon health metrics: uptime, memory usage, log level, and error count.
Fails silently if stats cannot be retrieved to avoid breaking the status line.
"""

import logging
from typing import Any

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.daemon.controller import get_controller

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)


class DaemonStatsHandler(Handler):
    """Show daemon health: uptime, memory, last error, log level."""

    def __init__(self) -> None:
        super().__init__(
            name="status-daemon-stats",
            priority=30,
            terminal=False,
            tags=["status", "daemon", "health", "non-terminal"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Generate daemon statistics for status line.

        Args:
            hook_input: Status event input (not used, but required by interface)

        Returns:
            HookResult with formatted daemon stats, or empty if stats unavailable
        """
        parts = []

        try:
            # Get daemon stats
            controller = get_controller()
            stats = controller.get_stats()

            # Uptime formatting
            uptime = stats.uptime_seconds
            if uptime < 60:
                uptime_str = f"{uptime:.1f}s"
            elif uptime < 3600:
                uptime_str = f"{uptime/60:.1f}m"
            else:
                uptime_str = f"{uptime/3600:.1f}h"

            # Memory usage (if psutil is available)
            mem_str = ""
            if psutil is not None:
                try:
                    process = psutil.Process()
                    mem_mb = process.memory_info().rss / (1024 * 1024)
                    mem_str = f" | {mem_mb:.0f}MB"
                except (OSError, AttributeError) as e:
                    logger.debug("Failed to get process memory: %s", e)
                except Exception as e:
                    logger.error("Unexpected error getting memory stats: %s", e, exc_info=True)

            # Log level
            log_level = logging.getLogger().level
            level_name = logging.getLevelName(log_level)

            # Format: "| 🪝 12.3s 45MB | INFO"
            parts.append(f"| 🪝 {uptime_str}{mem_str} | {level_name}")

            # Last error (if any)
            if stats.errors > 0:
                parts.append(f"| ❌ {stats.errors} err")

        except Exception as e:
            logger.debug(f"Failed to get daemon stats: {e}")
            # Fail silently - don't break status line

        return HookResult(context=parts)
