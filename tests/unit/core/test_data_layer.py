"""Tests for DaemonDataLayer - unified API facade.

TDD RED phase: These tests define the expected API for DaemonDataLayer.
"""

from claude_code_hooks_daemon.constants import ToolName
from claude_code_hooks_daemon.core.data_layer import (
    DaemonDataLayer,
    get_data_layer,
    reset_data_layer,
)
from claude_code_hooks_daemon.core.handler_history import HandlerHistory
from claude_code_hooks_daemon.core.session_state import SessionState
from claude_code_hooks_daemon.core.transcript_reader import TranscriptReader


class TestDaemonDataLayerInit:
    """Test DaemonDataLayer initialization."""

    def test_session_returns_session_state(self) -> None:
        """session property should return a SessionState instance."""
        dl = DaemonDataLayer()
        assert isinstance(dl.session, SessionState)

    def test_transcript_returns_transcript_reader(self) -> None:
        """transcript property should return a TranscriptReader instance."""
        dl = DaemonDataLayer()
        assert isinstance(dl.transcript, TranscriptReader)

    def test_history_returns_handler_history(self) -> None:
        """history property should return a HandlerHistory instance."""
        dl = DaemonDataLayer()
        assert isinstance(dl.history, HandlerHistory)

    def test_session_is_same_instance(self) -> None:
        """session should return the same instance on multiple accesses."""
        dl = DaemonDataLayer()
        assert dl.session is dl.session

    def test_transcript_is_same_instance(self) -> None:
        """transcript should return the same instance on multiple accesses."""
        dl = DaemonDataLayer()
        assert dl.transcript is dl.transcript

    def test_history_is_same_instance(self) -> None:
        """history should return the same instance on multiple accesses."""
        dl = DaemonDataLayer()
        assert dl.history is dl.history


class TestDaemonDataLayerReset:
    """Test DaemonDataLayer.reset()."""

    def test_reset_clears_session_state(self) -> None:
        """reset() should clear session state."""
        dl = DaemonDataLayer()
        dl.session.update_from_status_event(
            {
                "model": {"id": "claude-opus-4-6", "display_name": "Opus"},
                "context_window": {"used_percentage": 75.0},
            }
        )
        dl.reset()
        assert dl.session.model_id is None
        assert dl.session.is_populated is False

    def test_reset_clears_handler_history(self) -> None:
        """reset() should clear handler history."""
        dl = DaemonDataLayer()
        dl.history.record(
            handler_id="test",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
        )
        dl.reset()
        assert dl.history.total_count == 0


class TestGetDataLayer:
    """Test get_data_layer() singleton accessor."""

    def setup_method(self) -> None:
        """Reset global state before each test."""
        reset_data_layer()

    def teardown_method(self) -> None:
        """Reset global state after each test."""
        reset_data_layer()

    def test_returns_daemon_data_layer(self) -> None:
        """get_data_layer() should return a DaemonDataLayer instance."""
        dl = get_data_layer()
        assert isinstance(dl, DaemonDataLayer)

    def test_returns_same_instance(self) -> None:
        """get_data_layer() should return the same instance on multiple calls."""
        dl1 = get_data_layer()
        dl2 = get_data_layer()
        assert dl1 is dl2

    def test_reset_creates_new_instance(self) -> None:
        """reset_data_layer() should cause get_data_layer() to create new instance."""
        dl1 = get_data_layer()
        reset_data_layer()
        dl2 = get_data_layer()
        assert dl1 is not dl2


class TestDaemonDataLayerIntegration:
    """Test DaemonDataLayer components work together."""

    def test_session_update_accessible_after_set(self) -> None:
        """Data set via session should be accessible."""
        dl = DaemonDataLayer()
        dl.session.update_from_status_event(
            {
                "model": {"id": "claude-opus-4-6", "display_name": "Claude Opus 4.6"},
                "context_window": {"used_percentage": 42.0},
            }
        )
        assert dl.session.is_opus() is True
        assert dl.session.context_used_percentage == 42.0

    def test_history_record_accessible(self) -> None:
        """Decisions recorded via history should be queryable."""
        dl = DaemonDataLayer()
        dl.history.record(
            handler_id="destructive-git",
            event_type="PreToolUse",
            decision="deny",
            tool_name=ToolName.BASH,
            reason="Blocked force push",
        )
        assert dl.history.was_blocked(ToolName.BASH) is True
        assert dl.history.count_blocks() == 1
