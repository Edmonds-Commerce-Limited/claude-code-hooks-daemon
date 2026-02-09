"""Tests for SessionState - in-memory StatusLine data cache.

TDD RED phase: These tests define the expected API for SessionState.
"""

from datetime import datetime

import pytest

from claude_code_hooks_daemon.core.session_state import SessionState


class TestSessionStateInit:
    """Test SessionState initialization."""

    def test_initial_state_has_no_model(self) -> None:
        """SessionState should start with no model info."""
        state = SessionState()
        assert state.model_id is None
        assert state.model_display_name is None

    def test_initial_state_has_zero_context(self) -> None:
        """SessionState should start with 0% context usage."""
        state = SessionState()
        assert state.context_used_percentage == 0.0

    def test_initial_state_has_no_last_updated(self) -> None:
        """SessionState should start with no last_updated timestamp."""
        state = SessionState()
        assert state.last_updated is None

    def test_initial_state_is_not_populated(self) -> None:
        """SessionState should report not populated before any update."""
        state = SessionState()
        assert state.is_populated is False


class TestSessionStateUpdate:
    """Test SessionState.update_from_status_event()."""

    def test_update_extracts_model_id(self) -> None:
        """update() should extract model ID from status event data."""
        state = SessionState()
        hook_input = {
            "model": {"id": "claude-sonnet-4-5-20250929", "display_name": "Claude 4.5 Sonnet"},
            "context_window": {"used_percentage": 25.0},
        }
        state.update_from_status_event(hook_input)
        assert state.model_id == "claude-sonnet-4-5-20250929"

    def test_update_extracts_model_display_name(self) -> None:
        """update() should extract model display name."""
        state = SessionState()
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Claude Opus 4.6"},
            "context_window": {"used_percentage": 50.0},
        }
        state.update_from_status_event(hook_input)
        assert state.model_display_name == "Claude Opus 4.6"

    def test_update_extracts_context_percentage(self) -> None:
        """update() should extract context used percentage."""
        state = SessionState()
        hook_input = {
            "model": {"id": "claude-sonnet-4-5-20250929", "display_name": "Sonnet"},
            "context_window": {"used_percentage": 73.5},
        }
        state.update_from_status_event(hook_input)
        assert state.context_used_percentage == 73.5

    def test_update_sets_last_updated_timestamp(self) -> None:
        """update() should set last_updated to current time."""
        state = SessionState()
        before = datetime.now()
        hook_input = {
            "model": {"id": "claude-sonnet-4-5-20250929", "display_name": "Sonnet"},
            "context_window": {"used_percentage": 10.0},
        }
        state.update_from_status_event(hook_input)
        after = datetime.now()
        assert state.last_updated is not None
        assert before <= state.last_updated <= after

    def test_update_marks_as_populated(self) -> None:
        """update() should mark state as populated."""
        state = SessionState()
        hook_input = {
            "model": {"id": "test", "display_name": "Test"},
            "context_window": {"used_percentage": 0.0},
        }
        state.update_from_status_event(hook_input)
        assert state.is_populated is True

    def test_update_handles_missing_model(self) -> None:
        """update() should handle missing model data gracefully."""
        state = SessionState()
        hook_input = {"context_window": {"used_percentage": 50.0}}
        state.update_from_status_event(hook_input)
        assert state.model_id is None
        assert state.model_display_name is None
        assert state.context_used_percentage == 50.0

    def test_update_handles_missing_context_window(self) -> None:
        """update() should handle missing context_window gracefully."""
        state = SessionState()
        hook_input = {
            "model": {"id": "claude-opus-4-6", "display_name": "Opus"},
        }
        state.update_from_status_event(hook_input)
        assert state.model_id == "claude-opus-4-6"
        assert state.context_used_percentage == 0.0

    def test_update_handles_empty_dict(self) -> None:
        """update() should handle empty hook_input without crashing."""
        state = SessionState()
        state.update_from_status_event({})
        assert state.model_id is None
        assert state.context_used_percentage == 0.0

    def test_update_overwrites_previous_values(self) -> None:
        """update() should overwrite previous state on each call."""
        state = SessionState()
        hook_input_1 = {
            "model": {"id": "model-a", "display_name": "Model A"},
            "context_window": {"used_percentage": 10.0},
        }
        hook_input_2 = {
            "model": {"id": "model-b", "display_name": "Model B"},
            "context_window": {"used_percentage": 90.0},
        }
        state.update_from_status_event(hook_input_1)
        state.update_from_status_event(hook_input_2)
        assert state.model_id == "model-b"
        assert state.model_display_name == "Model B"
        assert state.context_used_percentage == 90.0


class TestSessionStateModelHelpers:
    """Test model family detection convenience methods."""

    @pytest.fixture
    def state_with_model(self) -> SessionState:
        """Create a SessionState and return it for updating."""
        return SessionState()

    def _update_with_model(self, state: SessionState, model_id: str, display: str) -> None:
        """Helper to update state with a model."""
        state.update_from_status_event(
            {
                "model": {"id": model_id, "display_name": display},
                "context_window": {"used_percentage": 0.0},
            }
        )

    def test_is_opus_true_for_opus_model(self, state_with_model: SessionState) -> None:
        """is_opus() should return True for Opus models."""
        self._update_with_model(state_with_model, "claude-opus-4-6", "Claude Opus 4.6")
        assert state_with_model.is_opus() is True

    def test_is_opus_false_for_sonnet(self, state_with_model: SessionState) -> None:
        """is_opus() should return False for Sonnet models."""
        self._update_with_model(state_with_model, "claude-sonnet-4-5-20250929", "Claude 4.5 Sonnet")
        assert state_with_model.is_opus() is False

    def test_is_sonnet_true_for_sonnet_model(self, state_with_model: SessionState) -> None:
        """is_sonnet() should return True for Sonnet models."""
        self._update_with_model(state_with_model, "claude-sonnet-4-5-20250929", "Claude 4.5 Sonnet")
        assert state_with_model.is_sonnet() is True

    def test_is_sonnet_false_for_opus(self, state_with_model: SessionState) -> None:
        """is_sonnet() should return False for Opus models."""
        self._update_with_model(state_with_model, "claude-opus-4-6", "Claude Opus 4.6")
        assert state_with_model.is_sonnet() is False

    def test_is_haiku_true_for_haiku_model(self, state_with_model: SessionState) -> None:
        """is_haiku() should return True for Haiku models."""
        self._update_with_model(state_with_model, "claude-haiku-4-5-20251001", "Claude 4.5 Haiku")
        assert state_with_model.is_haiku() is True

    def test_is_haiku_false_for_opus(self, state_with_model: SessionState) -> None:
        """is_haiku() should return False for Opus models."""
        self._update_with_model(state_with_model, "claude-opus-4-6", "Claude Opus 4.6")
        assert state_with_model.is_haiku() is False

    def test_model_helpers_false_when_no_model(self, state_with_model: SessionState) -> None:
        """Model helpers should return False when no model is set."""
        assert state_with_model.is_opus() is False
        assert state_with_model.is_sonnet() is False
        assert state_with_model.is_haiku() is False

    def test_model_name_short_opus(self, state_with_model: SessionState) -> None:
        """model_name_short() should return 'Opus' for Opus models."""
        self._update_with_model(state_with_model, "claude-opus-4-6", "Claude Opus 4.6")
        assert state_with_model.model_name_short() == "Opus"

    def test_model_name_short_sonnet(self, state_with_model: SessionState) -> None:
        """model_name_short() should return 'Sonnet' for Sonnet models."""
        self._update_with_model(state_with_model, "claude-sonnet-4-5-20250929", "Claude 4.5 Sonnet")
        assert state_with_model.model_name_short() == "Sonnet"

    def test_model_name_short_haiku(self, state_with_model: SessionState) -> None:
        """model_name_short() should return 'Haiku' for Haiku models."""
        self._update_with_model(state_with_model, "claude-haiku-4-5-20251001", "Claude 4.5 Haiku")
        assert state_with_model.model_name_short() == "Haiku"

    def test_model_name_short_unknown(self, state_with_model: SessionState) -> None:
        """model_name_short() should return display name for unknown models."""
        self._update_with_model(state_with_model, "custom-model-v1", "Custom Model")
        assert state_with_model.model_name_short() == "Custom Model"

    def test_model_name_short_no_model(self, state_with_model: SessionState) -> None:
        """model_name_short() should return 'Unknown' when no model is set."""
        assert state_with_model.model_name_short() == "Unknown"


class TestSessionStateReset:
    """Test SessionState.reset()."""

    def test_reset_clears_all_state(self) -> None:
        """reset() should clear all cached state."""
        state = SessionState()
        state.update_from_status_event(
            {
                "model": {"id": "claude-opus-4-6", "display_name": "Opus"},
                "context_window": {"used_percentage": 75.0},
            }
        )
        state.reset()
        assert state.model_id is None
        assert state.model_display_name is None
        assert state.context_used_percentage == 0.0
        assert state.last_updated is None
        assert state.is_populated is False
