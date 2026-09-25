"""Tests for the PreToolUse -> PostToolUse plan status snapshot store.

Plan 00466 RV3-n5: `plan_status_snapshot` (PreToolUse) records the plan's
disk status just before a Write/Edit runs, keyed by `tool_use_id`;
`goal_injection` (PostToolUse) consumes it as ground truth in place of
inference. This file tests the shared store in isolation.
"""

from claude_code_hooks_daemon.plan_qa.model import PlanStatus
from claude_code_hooks_daemon.utils.plan_status_snapshot import PlanStatusSnapshotStore

# These tests exercise record/consume/bounds mechanics only -- the actual
# predicted_post_hash value is irrelevant to them (RV5-M2's freshness
# comparison is tested separately, against goal_injection's consumer).
_H = "irrelevant-hash"


class TestRecordAndConsume:
    def test_consume_returns_the_recorded_status(self) -> None:
        store = PlanStatusSnapshotStore()
        store.record("tu-1", PlanStatus.NOT_STARTED, _H)

        status, found = store.consume("tu-1")

        assert found is True
        assert status == PlanStatus.NOT_STARTED

    def test_a_none_status_is_a_valid_recorded_value(self) -> None:
        """A plan with no Status line at all (status_line_present=False)
        still records a real snapshot -- None IS the pre-write status, not
        an absent entry."""
        store = PlanStatusSnapshotStore()
        store.record("tu-1", None, _H)

        status, found = store.consume("tu-1")

        assert found is True
        assert status is None

    def test_consume_is_missing_for_an_unrecorded_id(self) -> None:
        store = PlanStatusSnapshotStore()

        status, found = store.consume("never-recorded")

        assert found is False
        assert status is None

    def test_consume_pops_the_entry(self) -> None:
        """A second consume for the same id must not silently reuse a
        stale snapshot from an earlier, already-handled dispatch."""
        store = PlanStatusSnapshotStore()
        store.record("tu-1", PlanStatus.IN_PROGRESS, _H)
        store.consume("tu-1")

        status, found = store.consume("tu-1")

        assert found is False
        assert status is None

    def test_recording_an_empty_tool_use_id_is_a_no_op(self) -> None:
        store = PlanStatusSnapshotStore()
        store.record("", PlanStatus.IN_PROGRESS, _H)

        status, found = store.consume("")

        assert found is False
        assert status is None

    def test_consuming_an_empty_tool_use_id_never_finds_anything(self) -> None:
        store = PlanStatusSnapshotStore()

        status, found = store.consume("")

        assert found is False
        assert status is None


class TestConsumeSnapshot:
    """RV5-M2: the full-object consumer ``goal_injection`` uses to judge
    freshness (``predicted_post_hash``), distinct from the 2-tuple
    ``consume`` form other callers use."""

    def test_consume_snapshot_returns_the_full_object(self) -> None:
        store = PlanStatusSnapshotStore()
        store.record("tu-1", PlanStatus.NOT_STARTED, "abc123")

        snapshot = store.consume_snapshot("tu-1")

        assert snapshot is not None
        assert snapshot.status == PlanStatus.NOT_STARTED
        assert snapshot.predicted_post_hash == "abc123"

    def test_consume_snapshot_pops_the_entry(self) -> None:
        store = PlanStatusSnapshotStore()
        store.record("tu-1", PlanStatus.NOT_STARTED, _H)
        store.consume_snapshot("tu-1")

        assert store.consume_snapshot("tu-1") is None

    def test_consume_snapshot_is_none_for_an_unrecorded_id(self) -> None:
        store = PlanStatusSnapshotStore()

        assert store.consume_snapshot("never-recorded") is None

    def test_consume_snapshot_of_an_empty_id_never_finds_anything(self) -> None:
        store = PlanStatusSnapshotStore()
        store.record("tu-1", PlanStatus.NOT_STARTED, _H)

        assert store.consume_snapshot("") is None


class TestBoundedGrowth:
    """RV5-M2: eviction is bounded by ``max_entries`` alone -- there is no
    TTL left to evict on (a wall clock can step backward; see the module
    docstring), so an orphaned Pre-without-Post entry only ever leaves the
    store by being the oldest once it fills up."""

    def test_entries_are_capped_with_fifo_eviction(self) -> None:
        store = PlanStatusSnapshotStore(max_entries=3)
        for i in range(5):
            store.record(f"tu-{i}", PlanStatus.IN_PROGRESS, _H)

        # The oldest two (tu-0, tu-1) must have been evicted.
        assert store.consume("tu-0") == (None, False)
        assert store.consume("tu-1") == (None, False)
        assert store.consume("tu-4")[1] is True


class TestConcurrency:
    """RV4-m1: the daemon dispatches hook events on a thread pool
    (``run_in_executor``), so ``record``/``consume``/eviction racing on the
    same unlocked ``dict`` can raise ``RuntimeError`` ("dictionary changed
    size during iteration") or ``KeyError`` -- an exception here escapes
    the handler dispatching it. Modeled on the reviewer's
    ``probe_gf4_threads2.py``: two threads doing record-then-consume
    against a store pre-filled with orphan entries (never-consumed Pre
    snapshots are the NORMAL case, not an edge case -- see
    ``goal_injection.py``'s docstring on ``_maybe_refresh_on_retirement``),
    at the shipped TTL."""

    def test_concurrent_record_and_consume_never_raises(self) -> None:
        import threading
        import time

        store = PlanStatusSnapshotStore()
        for i in range(200):
            store.record(f"orphan-{i}", PlanStatus.NOT_STARTED, _H)

        errors: list[BaseException] = []
        stop_at = time.time() + 1.0

        def worker(n: int) -> None:
            i = 0
            try:
                while time.time() < stop_at:
                    i += 1
                    key = f"t{n}-{i}"
                    store.record(key, PlanStatus.NOT_STARTED, _H)
                    store.consume(key)
            except BaseException as exc:  # capture for the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
