"""Tests for HandlerHistory - handler decision log.

TDD RED phase: These tests define the expected API for HandlerHistory.
"""

import pytest

from claude_code_hooks_daemon.constants import ToolName
from claude_code_hooks_daemon.core.handler_history import HandlerDecisionRecord, HandlerHistory


class TestHandlerHistoryInit:
    """Test HandlerHistory initialization."""

    def test_initial_state_is_empty(self) -> None:
        """HandlerHistory should start with no records."""
        history = HandlerHistory()
        assert history.get_recent(10) == []

    def test_initial_block_count_is_zero(self) -> None:
        """count_blocks() should be 0 initially."""
        history = HandlerHistory()
        assert history.count_blocks() == 0

    def test_initial_total_count_is_zero(self) -> None:
        """total_count should be 0 initially."""
        history = HandlerHistory()
        assert history.total_count == 0


class TestHandlerHistoryRecord:
    """Test HandlerHistory.record()."""

    @pytest.fixture
    def history(self) -> HandlerHistory:
        """Create a fresh HandlerHistory."""
        return HandlerHistory()

    def test_record_increments_total_count(self, history: HandlerHistory) -> None:
        """record() should increment total_count."""
        history.record(
            handler_id="destructive-git",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
            reason="Blocked force push",
        )
        assert history.total_count == 1

    def test_record_multiple_increments(self, history: HandlerHistory) -> None:
        """Multiple record() calls should increment total_count."""
        for i in range(5):
            history.record(
                handler_id=f"handler-{i}",
                event_type="PreToolUse",
                decision="allow",
                tool_name=ToolName.BASH,
            )
        assert history.total_count == 5

    def test_record_stores_handler_id(self, history: HandlerHistory) -> None:
        """record() should store handler_id."""
        history.record(
            handler_id="destructive-git",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        records = history.get_recent(1)
        assert records[0].handler_id == "destructive-git"

    def test_record_stores_event_type(self, history: HandlerHistory) -> None:
        """record() should store event_type."""
        history.record(
            handler_id="test",
            event_type="PostToolUse",
            decision="allow",
            tool_name=ToolName.WRITE,
        )
        records = history.get_recent(1)
        assert records[0].event_type == "PostToolUse"

    def test_record_stores_decision(self, history: HandlerHistory) -> None:
        """record() should store decision."""
        history.record(
            handler_id="test",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        records = history.get_recent(1)
        assert records[0].decision == "deny"

    def test_record_stores_tool_name(self, history: HandlerHistory) -> None:
        """record() should store tool_name."""
        history.record(
            handler_id="test",
            event_type="PreToolUse",
            decision="allow",
            tool_name=ToolName.WRITE,
        )
        records = history.get_recent(1)
        assert records[0].tool_name == ToolName.WRITE

    def test_record_stores_reason(self, history: HandlerHistory) -> None:
        """record() should store optional reason."""
        history.record(
            handler_id="test",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
            reason="Too dangerous",
        )
        records = history.get_recent(1)
        assert records[0].reason == "Too dangerous"

    def test_record_reason_defaults_to_none(self, history: HandlerHistory) -> None:
        """record() should default reason to None."""
        history.record(
            handler_id="test",
            event_type="PreToolUse",
            decision="allow",
            tool_name=ToolName.BASH,
        )
        records = history.get_recent(1)
        assert records[0].reason is None

    def test_record_sets_timestamp(self, history: HandlerHistory) -> None:
        """record() should set a timestamp on each record."""
        history.record(
            handler_id="test",
            event_type="PreToolUse",
            decision="allow",
            tool_name=ToolName.BASH,
        )
        records = history.get_recent(1)
        assert records[0].timestamp > 0


class TestHandlerHistoryGetRecent:
    """Test HandlerHistory.get_recent()."""

    @pytest.fixture
    def history_with_records(self) -> HandlerHistory:
        """Create a HandlerHistory with 5 records."""
        history = HandlerHistory()
        for i in range(5):
            history.record(
                handler_id=f"handler-{i}",
                event_type="PreToolUse",
                decision="allow" if i % 2 == 0 else "deny",
                tool_name=ToolName.BASH,
            )
        return history

    def test_get_recent_returns_latest_first(self, history_with_records: HandlerHistory) -> None:
        """get_recent() should return most recent records first."""
        records = history_with_records.get_recent(2)
        assert len(records) == 2
        assert records[0].handler_id == "handler-4"
        assert records[1].handler_id == "handler-3"

    def test_get_recent_limits_count(self, history_with_records: HandlerHistory) -> None:
        """get_recent() should limit to requested count."""
        records = history_with_records.get_recent(3)
        assert len(records) == 3

    def test_get_recent_returns_all_if_n_exceeds_total(
        self, history_with_records: HandlerHistory
    ) -> None:
        """get_recent() should return all records if n > total."""
        records = history_with_records.get_recent(100)
        assert len(records) == 5

    def test_get_recent_returns_empty_for_zero(self, history_with_records: HandlerHistory) -> None:
        """get_recent(0) should return empty list."""
        records = history_with_records.get_recent(0)
        assert records == []


class TestHandlerHistoryCountBlocks:
    """Test HandlerHistory.count_blocks()."""

    @pytest.fixture
    def history(self) -> HandlerHistory:
        """Create a fresh HandlerHistory."""
        return HandlerHistory()

    def test_count_blocks_counts_deny_decisions(self, history: HandlerHistory) -> None:
        """count_blocks() should count deny decisions."""
        history.record(
            handler_id="h1", event_type="PreToolUse", decision="deny", tool_name=ToolName.BASH
        )
        history.record(
            handler_id="h2", event_type="PreToolUse", decision="allow", tool_name=ToolName.BASH
        )
        history.record(
            handler_id="h3", event_type="PreToolUse", decision="deny", tool_name=ToolName.WRITE
        )
        assert history.count_blocks() == 2

    def test_count_blocks_ignores_allow(self, history: HandlerHistory) -> None:
        """count_blocks() should not count allow decisions."""
        history.record(
            handler_id="h1", event_type="PreToolUse", decision="allow", tool_name=ToolName.BASH
        )
        assert history.count_blocks() == 0

    def test_count_blocks_includes_ask(self, history: HandlerHistory) -> None:
        """count_blocks() should count ask decisions as blocks."""
        history.record(
            handler_id="h1", event_type="PreToolUse", decision="ask", tool_name=ToolName.BASH
        )
        assert history.count_blocks() == 1


class TestHandlerHistoryWasBlocked:
    """Test HandlerHistory.was_blocked()."""

    @pytest.fixture
    def history(self) -> HandlerHistory:
        """Create a HandlerHistory with some deny records."""
        h = HandlerHistory()
        h.record(handler_id="h1", event_type="PreToolUse", decision="deny", tool_name=ToolName.BASH)
        h.record(
            handler_id="h2", event_type="PreToolUse", decision="allow", tool_name=ToolName.WRITE
        )
        return h

    def test_was_blocked_true_for_denied_tool(self, history: HandlerHistory) -> None:
        """was_blocked() should return True for a tool that was denied."""
        assert history.was_blocked(ToolName.BASH) is True

    def test_was_blocked_false_for_allowed_tool(self, history: HandlerHistory) -> None:
        """was_blocked() should return False for a tool that was only allowed."""
        assert history.was_blocked(ToolName.WRITE) is False

    def test_was_blocked_false_for_unknown_tool(self, history: HandlerHistory) -> None:
        """was_blocked() should return False for an unknown tool."""
        assert history.was_blocked(ToolName.READ) is False


class TestHandlerHistoryMaxSize:
    """Test HandlerHistory respects max_size limit."""

    def test_max_size_limits_records(self) -> None:
        """History should evict oldest records when max_size exceeded."""
        history = HandlerHistory(max_size=3)
        for i in range(5):
            history.record(
                handler_id=f"handler-{i}",
                event_type="PreToolUse",
                decision="allow",
                tool_name=ToolName.BASH,
            )
        records = history.get_recent(10)
        assert len(records) == 3
        # Should keep the 3 most recent
        assert records[0].handler_id == "handler-4"
        assert records[2].handler_id == "handler-2"

    def test_total_count_reflects_all_records(self) -> None:
        """total_count should reflect all records ever added, not just stored."""
        history = HandlerHistory(max_size=3)
        for i in range(5):
            history.record(
                handler_id=f"handler-{i}",
                event_type="PreToolUse",
                decision="allow",
                tool_name=ToolName.BASH,
            )
        assert history.total_count == 5


class TestHandlerHistoryReset:
    """Test HandlerHistory.reset()."""

    def test_reset_clears_all_records(self) -> None:
        """reset() should clear all records."""
        history = HandlerHistory()
        history.record(
            handler_id="h1", event_type="PreToolUse", decision="deny", tool_name=ToolName.BASH
        )
        history.reset()
        assert history.get_recent(10) == []
        assert history.total_count == 0
        assert history.count_blocks() == 0


class TestHandlerHistoryCountBlocksByHandler:
    """Test HandlerHistory.count_blocks_by_handler()."""

    @pytest.fixture
    def history(self) -> HandlerHistory:
        """Create a fresh HandlerHistory."""
        return HandlerHistory()

    def test_returns_zero_for_empty_history(self, history: HandlerHistory) -> None:
        """count_blocks_by_handler() should return 0 for empty history."""
        assert history.count_blocks_by_handler("pipe-blocker") == 0

    def test_counts_deny_from_specific_handler(self, history: HandlerHistory) -> None:
        """count_blocks_by_handler() should count deny decisions from specific handler."""
        history.record(
            handler_id="pipe-blocker",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        assert history.count_blocks_by_handler("pipe-blocker") == 1

    def test_counts_ask_from_specific_handler(self, history: HandlerHistory) -> None:
        """count_blocks_by_handler() should count ask decisions from specific handler."""
        history.record(
            handler_id="pipe-blocker",
            event_type="PreToolUse",
            decision="ask",
            tool_name=ToolName.BASH,
        )
        assert history.count_blocks_by_handler("pipe-blocker") == 1

    def test_ignores_allow_decisions(self, history: HandlerHistory) -> None:
        """count_blocks_by_handler() should not count allow decisions."""
        history.record(
            handler_id="pipe-blocker",
            event_type="PreToolUse",
            decision="allow",
            tool_name=ToolName.BASH,
        )
        assert history.count_blocks_by_handler("pipe-blocker") == 0

    def test_ignores_other_handler_ids(self, history: HandlerHistory) -> None:
        """count_blocks_by_handler() should only count from the specified handler."""
        history.record(
            handler_id="block-sed-command",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        history.record(
            handler_id="prevent-destructive-git",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        assert history.count_blocks_by_handler("pipe-blocker") == 0

    def test_mixed_scenario_multiple_handlers(self, history: HandlerHistory) -> None:
        """count_blocks_by_handler() should handle mixed scenarios correctly."""
        # 2 denies from pipe-blocker
        history.record(
            handler_id="pipe-blocker",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        history.record(
            handler_id="pipe-blocker",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        # 1 allow from pipe-blocker (should not count)
        history.record(
            handler_id="pipe-blocker",
            event_type="PreToolUse",
            decision="allow",
            tool_name=ToolName.BASH,
        )
        # 1 deny from sed-blocker (should not count for pipe-blocker)
        history.record(
            handler_id="block-sed-command",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        # 1 ask from pipe-blocker
        history.record(
            handler_id="pipe-blocker",
            event_type="PreToolUse",
            decision="ask",
            tool_name=ToolName.BASH,
        )
        assert history.count_blocks_by_handler("pipe-blocker") == 3
        assert history.count_blocks_by_handler("block-sed-command") == 1


class TestHandlerDecisionRecord:
    """Test the HandlerDecisionRecord dataclass."""

    def test_record_fields(self) -> None:
        """HandlerDecisionRecord should store all fields."""
        record = HandlerDecisionRecord(
            handler_id="test-handler",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
            reason="Test reason",
            timestamp=1234567890.0,
        )
        assert record.handler_id == "test-handler"
        assert record.event_type == "PreToolUse"
        assert record.decision == "deny"
        assert record.tool_name == ToolName.BASH
        assert record.reason == "Test reason"
        assert record.timestamp == 1234567890.0
