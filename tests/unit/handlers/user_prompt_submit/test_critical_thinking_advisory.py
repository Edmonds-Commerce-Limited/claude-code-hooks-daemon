"""Comprehensive tests for CriticalThinkingAdvisoryHandler."""

import random
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, HookResult


class TestCriticalThinkingAdvisoryHandler:
    """Test suite for CriticalThinkingAdvisoryHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance with seeded RNG for determinism."""
        from claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory import (
            CriticalThinkingAdvisoryHandler,
        )

        h = CriticalThinkingAdvisoryHandler()
        h._rng = random.Random(42)  # Seed for deterministic tests
        return h

    # --- Initialisation Tests ---

    def test_init_sets_correct_handler_id(self, handler):
        """Handler ID should be CRITICAL_THINKING_ADVISORY."""
        assert handler.handler_id is HandlerID.CRITICAL_THINKING_ADVISORY

    def test_init_sets_correct_name(self, handler):
        """Handler name should match display_name."""
        assert handler.name == HandlerID.CRITICAL_THINKING_ADVISORY.display_name

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 55."""
        assert handler.priority == Priority.CRITICAL_THINKING_ADVISORY

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal (advisory only)."""
        assert handler.terminal is False

    def test_init_has_advisory_tag(self, handler):
        """Handler should have ADVISORY tag."""
        assert HandlerTag.ADVISORY in handler.tags

    def test_init_has_non_terminal_tag(self, handler):
        """Handler should have NON_TERMINAL tag."""
        assert HandlerTag.NON_TERMINAL in handler.tags

    def test_init_last_fired_count_allows_first_fire(self, handler):
        """Initial _last_fired_count should allow first fire (negative offset)."""
        assert handler._last_fired_count < 0

    # --- matches() Tests ---

    def test_matches_returns_false_for_short_prompt(self, handler):
        """Should not match prompts shorter than 80 characters."""
        hook_input = {"prompt": "yes"}
        assert handler.matches(hook_input) is False

    def test_matches_returns_false_for_empty_prompt(self, handler):
        """Should not match empty prompts."""
        hook_input = {"prompt": ""}
        assert handler.matches(hook_input) is False

    def test_matches_returns_false_for_missing_prompt(self, handler):
        """Should not match when prompt key is missing."""
        hook_input = {}
        assert handler.matches(hook_input) is False

    def test_matches_returns_false_for_79_chars(self, handler):
        """Should not match prompts of exactly 79 characters."""
        hook_input = {"prompt": "a" * 79}
        assert handler.matches(hook_input) is False

    def test_matches_returns_true_for_80_chars(self, handler):
        """Should match prompts of exactly 80 characters."""
        hook_input = {"prompt": "a" * 80}
        assert handler.matches(hook_input) is True

    def test_matches_returns_true_for_long_prompt(self, handler):
        """Should match prompts well above the threshold."""
        hook_input = {
            "prompt": "Implement a new handler that blocks destructive git operations like reset --hard and clean -fd across the entire repository"
        }
        assert handler.matches(hook_input) is True

    # --- handle() Tests: Random gate ---

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_handle_silent_allow_when_random_gate_fails(self, mock_gdl, handler):
        """Should return ALLOW without context when random gate rejects."""
        mock_gdl.return_value.history.total_count = 100  # Past cooldown

        # Seed RNG so random() > FIRE_PROBABILITY (0.2)
        # With seed 42, first random() is ~0.639 which is > 0.2, so gate fails
        handler._rng = random.Random(42)
        handler._last_fired_count = -10  # Ensure cooldown passes

        hook_input = {"prompt": "a" * 100}
        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW.value
        assert result.context == []

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_handle_fires_when_random_gate_passes(self, mock_gdl, handler):
        """Should return ALLOW with context when random gate passes."""
        mock_gdl.return_value.history.total_count = 100

        # Find a seed where random() <= 0.2
        rng = random.Random(1)  # seed=1: first random() is ~0.134 which is <= 0.2
        handler._rng = rng
        handler._last_fired_count = -10

        hook_input = {"prompt": "a" * 100}
        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW.value
        assert len(result.context) == 1
        assert len(result.context[0]) > 0

    # --- handle() Tests: Cooldown gate ---

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_handle_silent_allow_when_cooldown_active(self, mock_gdl, handler):
        """Should return ALLOW without context when cooldown is active."""
        mock_gdl.return_value.history.total_count = 5
        handler._last_fired_count = 4  # Only 1 event since last fire, need 3

        hook_input = {"prompt": "a" * 100}
        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW.value
        assert result.context == []

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_handle_cooldown_exactly_at_boundary(self, mock_gdl, handler):
        """Cooldown should still be active when difference equals COOLDOWN_EVENTS - 1."""
        mock_gdl.return_value.history.total_count = 5
        handler._last_fired_count = 3  # Difference is 2, need >= 3

        hook_input = {"prompt": "a" * 100}
        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW.value
        assert result.context == []

    # --- handle() Tests: All gates pass ---

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_handle_allow_with_context_when_all_gates_pass(self, mock_gdl, handler):
        """Should return ALLOW with advisory context when all gates pass."""
        mock_gdl.return_value.history.total_count = 100
        handler._last_fired_count = -10  # Cooldown passes

        # Use seed where random() <= 0.2
        handler._rng = random.Random(1)

        hook_input = {"prompt": "a" * 100}
        result = handler.handle(hook_input)

        assert isinstance(result, HookResult)
        assert result.decision == Decision.ALLOW.value
        assert len(result.context) == 1

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_context_message_is_from_pool(self, mock_gdl, handler):
        """Context message should be one of the predefined advisory messages."""
        from claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory import (
            _ADVISORY_MESSAGES,
        )

        mock_gdl.return_value.history.total_count = 100
        handler._last_fired_count = -10
        handler._rng = random.Random(1)

        hook_input = {"prompt": "a" * 100}
        result = handler.handle(hook_input)

        assert result.context[0] in _ADVISORY_MESSAGES

    # --- Cooldown reset tests ---

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_cooldown_resets_after_firing(self, mock_gdl, handler):
        """_last_fired_count should update to current total_count after firing."""
        mock_gdl.return_value.history.total_count = 50
        handler._last_fired_count = -10
        handler._rng = random.Random(1)  # Will pass random gate

        hook_input = {"prompt": "a" * 100}
        handler.handle(hook_input)

        assert handler._last_fired_count == 50

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_cooldown_does_not_reset_on_silent_allow(self, mock_gdl, handler):
        """_last_fired_count should NOT change when handler doesn't fire."""
        mock_gdl.return_value.history.total_count = 5
        handler._last_fired_count = 4  # Cooldown active

        hook_input = {"prompt": "a" * 100}
        handler.handle(hook_input)

        assert handler._last_fired_count == 4  # Unchanged

    # --- Multiple calls test ---

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_multiple_calls_respect_cooldown(self, mock_gdl, handler):
        """After firing, subsequent calls within cooldown should be silent."""
        handler._rng = random.Random(1)  # Passes random gate
        handler._last_fired_count = -10

        # First call: should fire
        mock_gdl.return_value.history.total_count = 10
        hook_input = {"prompt": "a" * 100}
        result1 = handler.handle(hook_input)
        assert len(result1.context) == 1

        # Second call: cooldown active (only 1 event later)
        mock_gdl.return_value.history.total_count = 11
        handler._rng = random.Random(1)  # Reset seed to pass random gate
        result2 = handler.handle(hook_input)
        assert result2.context == []

        # Third call: cooldown still active (only 2 events later)
        mock_gdl.return_value.history.total_count = 12
        handler._rng = random.Random(1)
        result3 = handler.handle(hook_input)
        assert result3.context == []

        # Fourth call: cooldown expired (3 events later)
        mock_gdl.return_value.history.total_count = 13
        handler._rng = random.Random(1)
        result4 = handler.handle(hook_input)
        assert len(result4.context) == 1

    # --- Result properties ---

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_handle_has_no_reason(self, mock_gdl, handler):
        """Should not provide reason."""
        mock_gdl.return_value.history.total_count = 100
        handler._last_fired_count = -10
        handler._rng = random.Random(1)

        result = handler.handle({"prompt": "a" * 100})
        assert result.reason is None

    @patch(
        "claude_code_hooks_daemon.handlers.user_prompt_submit.critical_thinking_advisory.get_data_layer"
    )
    def test_handle_has_no_guidance(self, mock_gdl, handler):
        """Should not provide guidance."""
        mock_gdl.return_value.history.total_count = 100
        handler._last_fired_count = -10
        handler._rng = random.Random(1)

        result = handler.handle({"prompt": "a" * 100})
        assert result.guidance is None

    # --- Acceptance tests ---

    def test_acceptance_tests_defined(self, handler):
        """Handler should define acceptance tests."""
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
