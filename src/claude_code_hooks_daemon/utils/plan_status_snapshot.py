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
invocation) is enough -- no filesystem round trip. A daemon restart
between the Pre and Post dispatch of the SAME tool call (a very narrow
window) empties the map; callers must treat a missing entry as "no
snapshot" and fall back to inference, never as an error.

RV4-m1: the daemon dispatches every hook event through
``loop.run_in_executor(None, ...)`` (``daemon/server.py``), whose default
executor is a ``ThreadPoolExecutor`` -- this module-level store is
therefore read and written from concurrent THREADS, the same pattern
``utils/config_cache.py`` already guards with a ``threading.Lock``. An
unlocked dict mutated by ``record``'s eviction and ``consume``'s pop
concurrently raises ``RuntimeError`` ("dictionary changed size during
iteration") or ``KeyError`` -- an exception here escapes the handler
dispatching it (``PlanStatusSnapshotHandler.handle`` for ``record``,
``GoalInjectionHandler.handle`` for ``consume``), and orphaned
Pre-without-Post entries (the NORMAL case, not an edge case -- see
``goal_injection.py``'s retirement-refresh docstring) keep the store near
its cap, where an unlocked mutation is likeliest to collide with another.

RV5-M2: freshness is judged by comparing a PREDICTED post-image hash
against the real one, not by a wall clock. The Pre handler applies this
call FORWARD (:func:`claude_code_hooks_daemon.handlers.utils.would_be_
content.would_be_content`) to the pre-write text it just read off disk --
a known, unambiguous starting point -- and records the hash of that
prediction alongside the status. ``goal_injection`` then only has to hash
the REAL post-edit text and compare: no reconstruction, no clock. An
orphaned entry (Pre ran, Post's own ``consume`` never did) is bounded
purely by ``max_entries`` (the oldest entry is evicted once the store is
full) -- not by any time-based expiry, which RV5-M2 removed entirely: a
wall clock can step backward, and nothing about "how long ago" answers
"is this still correct" the way the hash comparison does.
"""

import hashlib
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.handlers.utils.bounded_fifo_map import BoundedFifoMap

_MAX_ENTRIES: Final[int] = 256


def hash_plan_text(text: str | None) -> str:
    """Content digest of a plan's text, for RV5-M2 freshness comparisons.

    ``None`` (no file / no Status line) hashes the same as an empty string
    -- both sides of a Pre/Post comparison agree on this convention, so a
    plan that was genuinely absent both times still matches.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class PlanStatusSnapshot:
    """One recorded pre-write snapshot: the plan's status VALUE (a plain
    string, not :class:`~claude_code_hooks_daemon.plan_qa.model.PlanStatus`
    -- RV5-M3: this module sits in ``utils``, which must not import from
    ``plan_qa``, so callers on both sides convert at their own boundary:
    the Pre handler stores ``status.value``, ``goal_injection`` rehydrates
    with ``PlanStatus(value)``), and the hash of the PREDICTED post-image
    the Pre handler computed by applying this same call forward (RV5-M2).
    Public -- :meth:`PlanStatusSnapshotStore.consume_snapshot` hands this
    to ``goal_injection``'s own freshness check."""

    status: str | None
    predicted_post_hash: str


class PlanStatusSnapshotStore:
    """Bounded map from ``tool_use_id`` to a pre-write PlanDoc status.

    RV4-m1: every mutation is atomic -- see the module docstring for why
    this store, unlike a per-call-only structure, genuinely races.
    RV5-M2: bounded by ``max_entries`` alone, no TTL -- see the module
    docstring. RV6-n4: backed by :class:`~handlers.utils.bounded_fifo_map.
    BoundedFifoMap` (Plan 00449 P2's atomic FIFO-bounded map), the same
    type ``goal_injection``'s own ``_fired``/``_reasserted`` latches use --
    this store used to hand-roll the identical select-then-evict pattern
    Plan 00449 replaced there; reusing it here removes the second copy.
    """

    def __init__(self, *, max_entries: int = _MAX_ENTRIES) -> None:
        self._entries: BoundedFifoMap[str, PlanStatusSnapshot] = BoundedFifoMap(
            max_entries=max_entries
        )

    def record(self, tool_use_id: str, status: str | None, predicted_post_hash: str) -> None:
        """Record ``status``/``predicted_post_hash`` for ``tool_use_id``; a
        no-op for an empty id. ``status`` is a plain status VALUE string
        (RV5-M3: the caller's own ``PlanStatus.value``, not the enum
        itself -- see the class docstring). ``predicted_post_hash`` is
        :func:`hash_plan_text` of the text this SAME call is predicted to
        produce (RV5-M2) -- the freshness check the consuming side runs
        against it."""
        if not tool_use_id:
            return
        self._entries[tool_use_id] = PlanStatusSnapshot(
            status=status, predicted_post_hash=predicted_post_hash
        )

    def consume(self, tool_use_id: str) -> tuple[str | None, bool]:
        """Pop and return ``(status, found)``.

        Popped, not merely read: a retried or duplicated PostToolUse
        dispatch for the same ``tool_use_id`` must not silently reuse a
        stale snapshot left over from an earlier call. Does not itself
        judge RV5-M2 freshness (no caller of this 2-tuple form needs the
        hash) -- see :meth:`consume_snapshot`.
        """
        snapshot = self.consume_snapshot(tool_use_id)
        if snapshot is None:
            return None, False
        return snapshot.status, True

    def consume_snapshot(self, tool_use_id: str) -> PlanStatusSnapshot | None:
        """Pop and return the full :class:`PlanStatusSnapshot` (status,
        predicted_post_hash), or ``None`` when nothing was recorded.
        RV5-M2: ``goal_injection`` uses this form so it can judge
        freshness against ``predicted_post_hash`` before trusting the
        snapshot as ground truth."""
        if not tool_use_id:
            return None
        return self._entries.pop(tool_use_id, None)


# One shared instance: plan_status_snapshot (PreToolUse) writes, goal_injection
# (PostToolUse) reads, both in the same daemon process.
plan_status_snapshots: Final[PlanStatusSnapshotStore] = PlanStatusSnapshotStore()
