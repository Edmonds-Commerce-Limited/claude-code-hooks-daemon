"""Nitpick data types for pseudo-event state tracking.

Provides NitpickState for incremental transcript auditing.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class NitpickState:
    """Mutable state for incremental transcript auditing.

    Persisted in DaemonDataLayer (in-memory, keyed by session_id).
    Reset on context compaction.

    Attributes:
        last_byte_offset: File seek position for incremental reading
        last_audited_uuid: UUID of last audited transcript message
        findings_count: Running count of findings this session
    """

    last_byte_offset: int = 0
    last_audited_uuid: str | None = None
    findings_count: int = 0
