"""Handler decision history log.

Tracks previous handler decisions within a session for cross-handler
access via the DaemonDataLayer.

Usage:
    history = HandlerHistory()
    history.record(handler_id="destructive-git", event_type="PreToolUse",
                   decision="deny", tool_name="Bash", reason="Blocked force push")
    if history.was_blocked("Bash"):
        ...
"""

import logging
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default maximum number of decision records to retain
DEFAULT_MAX_SIZE = 1000


@dataclass(frozen=True, slots=True)
class HandlerDecisionRecord:
    """Immutable record of a single handler decision.

    Attributes:
        handler_id: Handler that made the decision
        event_type: Event type (PreToolUse, PostToolUse, etc.)
        decision: Decision made (allow, deny, ask)
        tool_name: Tool involved in the event
        reason: Optional reason for the decision
        timestamp: Unix timestamp when decision was made
    """

    handler_id: str
    event_type: str
    decision: str
    tool_name: str
    reason: str | None
    timestamp: float


class HandlerHistory:
    """In-memory log of handler decisions within a session.

    Records handler decisions and provides query methods for
    other handlers to check previous decisions.

    Attributes:
        total_count: Total number of decisions ever recorded (not limited by max_size)
    """

    __slots__ = ("_max_size", "_records", "_total_count")

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE) -> None:
        """Initialise with empty history.

        Args:
            max_size: Maximum number of records to retain (oldest evicted first)
        """
        self._records: deque[HandlerDecisionRecord] = deque(maxlen=max_size)
        self._max_size = max_size
        self._total_count = 0

    @property
    def total_count(self) -> int:
        """Total number of decisions ever recorded."""
        return self._total_count

    def record(
        self,
        *,
        handler_id: str,
        event_type: str,
        decision: str,
        tool_name: str,
        reason: str | None = None,
    ) -> None:
        """Record a handler decision.

        Args:
            handler_id: Handler that made the decision
            event_type: Event type (PreToolUse, PostToolUse, etc.)
            decision: Decision made (allow, deny, ask)
            tool_name: Tool involved in the event
            reason: Optional reason for the decision
        """
        record = HandlerDecisionRecord(
            handler_id=handler_id,
            event_type=event_type,
            decision=decision,
            tool_name=tool_name,
            reason=reason,
            timestamp=time.time(),
        )
        self._records.append(record)
        self._total_count += 1

        logger.debug(
            "HandlerHistory: %s -> %s for %s (%s)",
            handler_id,
            decision,
            tool_name,
            event_type,
        )

    def get_recent(self, n: int) -> list[HandlerDecisionRecord]:
        """Get the N most recent decision records.

        Args:
            n: Number of records to return

        Returns:
            List of records, most recent first
        """
        if n <= 0:
            return []
        # Return most recent first
        records = list(self._records)
        records.reverse()
        return records[:n]

    def count_blocks(self) -> int:
        """Count total block decisions (deny + ask) in history.

        Returns:
            Number of deny and ask decisions
        """
        return sum(1 for r in self._records if r.decision in ("deny", "ask"))

    def count_blocks_by_handler(self, handler_id: str) -> int:
        """Count block decisions (deny + ask) from a specific handler.

        Args:
            handler_id: Handler ID to filter by

        Returns:
            Number of deny and ask decisions from the specified handler
        """
        return sum(
            1 for r in self._records if r.handler_id == handler_id and r.decision in ("deny", "ask")
        )

    def was_blocked(self, tool_name: str) -> bool:
        """Check if a tool was ever blocked (deny or ask) in this session.

        Args:
            tool_name: Tool name to check (e.g. "Bash", "Write")

        Returns:
            True if tool was blocked at least once
        """
        return any(
            r.tool_name == tool_name and r.decision in ("deny", "ask") for r in self._records
        )

    def reset(self) -> None:
        """Reset all history.

        WARNING: Only use in testing or session cleanup.
        """
        self._records.clear()
        self._total_count = 0
