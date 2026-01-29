"""Constants module - Single source of truth for all identifiers and values.

This module provides centralized constants for:
- Handler identifiers and metadata (HandlerID, HandlerKey)
- Event type identifiers (EventID, EventKey)
- Priority values (Priority)
- Timeout values (Timeout)
- Path constants (DaemonPath, ProjectPath)

Usage:
    from claude_code_hooks_daemon.constants import HandlerID, Priority

    handler = MyHandler(
        handler_id=HandlerID.DESTRUCTIVE_GIT,
        priority=Priority.DESTRUCTIVE_GIT,
    )

Design Principles:
- NO MAGIC STRINGS: All identifiers come from this module
- NO MAGIC NUMBERS: All priorities, timeouts, and thresholds defined here
- DRY: Single source of truth for all naming and values
- TYPE SAFETY: Use Literal types for compile-time checking
"""

from claude_code_hooks_daemon.constants.events import EventID, EventIDMeta, EventKey
from claude_code_hooks_daemon.constants.handlers import HandlerID, HandlerIDMeta, HandlerKey
from claude_code_hooks_daemon.constants.paths import DaemonPath, ProjectPath
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.timeout import Timeout

__all__ = [
    # Handler constants
    "HandlerID",
    "HandlerIDMeta",
    "HandlerKey",
    # Event constants
    "EventID",
    "EventIDMeta",
    "EventKey",
    # Priority constants
    "Priority",
    # Timeout constants
    "Timeout",
    # Path constants
    "DaemonPath",
    "ProjectPath",
]
