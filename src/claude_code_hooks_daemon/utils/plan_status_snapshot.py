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
unlocked dict mutated by ``record``'s eviction and ``consume``/
``_evict_expired``'s iteration concurrently raises ``RuntimeError``
("dictionary changed size during iteration") or ``KeyError`` -- an
exception here escapes the handler dispatching it (``PlanStatusSnapshot-
Handler.handle`` for ``record``, ``GoalInjectionHandler.handle`` for
``consume``), and orphaned Pre-without-Post entries (the NORMAL case, not
an edge case -- see ``goal_injection.py``'s retirement-refresh docstring)
keep the store near its cap, where an unlocked iteration is likeliest to
collide with a concurrent mutation.

RV4-m2: the TTL bounds how long an ORPHANED snapshot (Pre ran, Post never
did) lingers, but it does NOT bound the Pre -> Post gap of a call that
DOES complete -- PreToolUse runs before Claude Code's permission prompt,
so that gap can be however long a person takes to answer one, and another
session's write can land in the meantime. A snapshot is therefore no
longer trusted unconditionally: it also carries a content hash
(:func:`hash_plan_text`) of the text it read, and ``goal_injection``
verifies the file it actually modified still matches before treating the
snapshot as ground truth (see ``GoalInjectionHandler._snapshot_is_fresh``).
"""

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.plan_qa.model import PlanStatus

_MAX_ENTRIES: Final[int] = 256
# Bounds how long an ORPHANED entry (Pre ran, Post's own consume() never
# did -- a denied/failed/deferred call, or a daemon crash mid-call)
# lingers before eviction. NOT a claim about the Pre -> Post gap of a call
# that DOES complete, which can span a permission prompt (RV4-m2) --
# staleness for THAT gap is judged separately, at consume time, via each
# snapshot's own content hash.
_TTL_SECONDS: Final[float] = 300.0


def hash_plan_text(text: str | None) -> str:
    """Content digest of a plan's text, for RV4-m2 staleness comparisons.

    ``None`` (no file / no Status line) hashes the same as an empty string
    -- both sides of a Pre/Post comparison agree on this convention, so a
    plan that was genuinely absent both times still matches.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class PlanStatusSnapshot:
    """One recorded pre-write snapshot: parsed status, content hash of the
    text it was parsed from (RV4-m2), and when it was recorded. Public --
    :meth:`PlanStatusSnapshotStore.consume_snapshot` hands this to
    ``goal_injection``'s own staleness check."""

    status: PlanStatus | None
    text_hash: str
    recorded_at: float


class PlanStatusSnapshotStore:
    """Bounded, TTL'd map from ``tool_use_id`` to a pre-write PlanDoc status.

    RV4-m1: every mutation and every iteration over ``_entries`` holds
    ``_lock`` -- see the module docstring for why this store, unlike a
    per-call-only structure, genuinely races.
    """

    def __init__(
        self, *, max_entries: int = _MAX_ENTRIES, ttl_seconds: float = _TTL_SECONDS
    ) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, PlanStatusSnapshot] = {}
        self._lock = threading.Lock()

    def record(self, tool_use_id: str, status: PlanStatus | None, text_hash: str) -> None:
        """Record ``status``/``text_hash`` for ``tool_use_id``; a no-op for
        an empty id. ``text_hash`` is :func:`hash_plan_text` of the SAME
        text ``status`` was parsed from -- the RV4-m2 staleness check the
        consuming side runs against it."""
        if not tool_use_id:
            return
        with self._lock:
            self._evict_expired_locked()
            if tool_use_id not in self._entries and len(self._entries) >= self._max_entries:
                self._entries.pop(next(iter(self._entries)), None)
            self._entries[tool_use_id] = PlanStatusSnapshot(
                status=status, text_hash=text_hash, recorded_at=time.time()
            )

    def consume(self, tool_use_id: str) -> tuple[PlanStatus | None, bool]:
        """Pop and return ``(status, found)``.

        Popped, not merely read: a retried or duplicated PostToolUse
        dispatch for the same ``tool_use_id`` must not silently reuse a
        stale snapshot left over from an earlier call. Does not itself
        judge RV4-m2 staleness (no caller of this 2-tuple form needs the
        hash) -- see :meth:`consume_snapshot`.
        """
        snapshot = self.consume_snapshot(tool_use_id)
        if snapshot is None:
            return None, False
        return snapshot.status, True

    def consume_snapshot(self, tool_use_id: str) -> PlanStatusSnapshot | None:
        """Pop and return the full :class:`PlanStatusSnapshot` (status,
        text_hash, recorded_at), or ``None`` when nothing was recorded (or
        it expired). RV4-m2: ``goal_injection`` uses this form so it can
        judge staleness against ``text_hash``/``recorded_at`` before
        trusting the snapshot as ground truth."""
        if not tool_use_id:
            return None
        with self._lock:
            self._evict_expired_locked()
            return self._entries.pop(tool_use_id, None)

    def _evict_expired_locked(self) -> None:
        """Drop every entry past its TTL. Caller must hold ``_lock``."""
        now = time.time()
        expired = [
            key
            for key, snap in self._entries.items()
            if now - snap.recorded_at >= self._ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)


# One shared instance: plan_status_snapshot (PreToolUse) writes, goal_injection
# (PostToolUse) reads, both in the same daemon process.
plan_status_snapshots: Final[PlanStatusSnapshotStore] = PlanStatusSnapshotStore()
