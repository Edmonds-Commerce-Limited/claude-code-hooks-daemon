"""Tests for the PreToolUse -> PostToolUse plan status snapshot store.

Plan 00466 RV3-n5: `plan_status_snapshot` (PreToolUse) records the plan's
disk status just before a Write/Edit runs, keyed by `tool_use_id`;
`goal_injection` (PostToolUse) consumes it as ground truth in place of
inference. This file tests the shared store in isolation.
"""

from claude_code_hooks_daemon.plan_qa.model import PlanStatus
from claude_code_hooks_daemon.utils.plan_status_snapshot import PlanStatusSnapshotStore


class TestRecordAndConsume:
    def test_consume_returns_the_recorded_status(self) -> None:
        store = PlanStatusSnapshotStore()
        store.record("tu-1", PlanStatus.NOT_STARTED)

        status, found = store.consume("tu-1")

        assert found is True
        assert status == PlanStatus.NOT_STARTED

    def test_a_none_status_is_a_valid_recorded_value(self) -> None:
        """A plan with no Status line at all (status_line_present=False)
        still records a real snapshot -- None IS the pre-write status, not
        an absent entry."""
        store = PlanStatusSnapshotStore()
        store.record("tu-1", None)

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
        store.record("tu-1", PlanStatus.IN_PROGRESS)
        store.consume("tu-1")

        status, found = store.consume("tu-1")

        assert found is False
        assert status is None

    def test_recording_an_empty_tool_use_id_is_a_no_op(self) -> None:
        store = PlanStatusSnapshotStore()
        store.record("", PlanStatus.IN_PROGRESS)

        status, found = store.consume("")

        assert found is False
        assert status is None

    def test_consuming_an_empty_tool_use_id_never_finds_anything(self) -> None:
        store = PlanStatusSnapshotStore()

        status, found = store.consume("")

        assert found is False
        assert status is None


class TestBoundedGrowth:
    def test_entries_are_capped_with_fifo_eviction(self) -> None:
        store = PlanStatusSnapshotStore(max_entries=3, ttl_seconds=3600.0)
        for i in range(5):
            store.record(f"tu-{i}", PlanStatus.IN_PROGRESS)

        # The oldest two (tu-0, tu-1) must have been evicted.
        assert store.consume("tu-0") == (None, False)
        assert store.consume("tu-1") == (None, False)
        assert store.consume("tu-4")[1] is True


class TestTtlExpiry:
    def test_an_expired_entry_is_treated_as_never_recorded(self) -> None:
        store = PlanStatusSnapshotStore(ttl_seconds=0.0)
        store.record("tu-1", PlanStatus.IN_PROGRESS)

        status, found = store.consume("tu-1")

        assert found is False
        assert status is None
