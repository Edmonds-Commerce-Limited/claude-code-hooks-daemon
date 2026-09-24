"""Pre-write PLAN.md status snapshot store (Plan 00466 RV3-n5).

``goal_injection``'s PostToolUse flip/retirement detection previously had
to INFER the plan's pre-write status from an Edit's own
``old_string``/``new_string``, or a Write's git HEAD -- both genuinely
ambiguous in narrow but real cases (RV3-m1/RV3-m2: a table cell or a fenced
example sharing the Status VALUE; RV3-m6: HEAD lagging an uncommitted
flip). None of that inference is needed when the daemon can simply READ
the plan's status just before the write happens and hand that ground
truth to the SAME write's own PostToolUse dispatch.
``handlers.pre_tool_use.plan_status_snapshot`` records it here; the
PostToolUse ``goal_injection`` handler consumes it.

Shared in-process via ONE module-level store: both handlers run in the
same daemon process for the lifetime of a single tool call, so a plain
bounded map keyed by ``tool_use_id`` (unique per Claude Code tool
invocation) is enough -- no filesystem round trip, no lock. A daemon
restart between the Pre and Post dispatch of the SAME tool call (a very
narrow window) empties the map; callers must treat a missing entry as "no
snapshot" and fall back to inference, never as an error.
"""

import time
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PlanStatus

_MAX_ENTRIES: Final[int] = 256
# Comfortably longer than the Pre -> Post gap of a single tool call (bounded
# by the tool's own execution time), short enough that a snapshot whose
# PostToolUse dispatch never ran (the Write/Edit was itself denied by a
# different PreToolUse handler, or the daemon crashed mid-call) does not
# linger indefinitely.
_TTL_SECONDS: Final[float] = 300.0


@dataclass
class _Snapshot:
    status: PlanStatus | None
    recorded_at: float


class PlanStatusSnapshotStore:
    """Bounded, TTL'd map from ``tool_use_id`` to a pre-write PlanDoc status."""

    def __init__(
        self, *, max_entries: int = _MAX_ENTRIES, ttl_seconds: float = _TTL_SECONDS
    ) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, _Snapshot] = {}

    def record(self, tool_use_id: str, status: PlanStatus | None) -> None:
        """Record ``status`` for ``tool_use_id``; a no-op for an empty id."""
        if not tool_use_id:
            return
        self._evict_expired()
        if tool_use_id not in self._entries and len(self._entries) >= self._max_entries:
            del self._entries[next(iter(self._entries))]
        self._entries[tool_use_id] = _Snapshot(status=status, recorded_at=time.time())

    def consume(self, tool_use_id: str) -> tuple[PlanStatus | None, bool]:
        """Pop and return ``(status, found)``.

        Popped, not merely read: a retried or duplicated PostToolUse
        dispatch for the same ``tool_use_id`` must not silently reuse a
        stale snapshot left over from an earlier call.
        """
        if not tool_use_id:
            return None, False
        self._evict_expired()
        snapshot = self._entries.pop(tool_use_id, None)
        if snapshot is None:
            return None, False
        return snapshot.status, True

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [
            key
            for key, snap in self._entries.items()
            if now - snap.recorded_at >= self._ttl_seconds
        ]
        for key in expired:
            del self._entries[key]


# One shared instance: plan_status_snapshot (PreToolUse) writes, goal_injection
# (PostToolUse) reads, both in the same daemon process.
plan_status_snapshots: Final[PlanStatusSnapshotStore] = PlanStatusSnapshotStore()
