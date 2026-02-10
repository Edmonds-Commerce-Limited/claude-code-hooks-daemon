"""Tests for dogfooding reminder handler (project-level plugin).

This test lives alongside the plugin, NOT in the library test directory.
"""

import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core import Decision

# Add plugin directory to path for importing plugin handlers
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "hooks"))

from handlers.session_start.dogfooding_reminder import (
    HANDLER_ID,
    PRIORITY,
    TAG_DOGFOODING,
    DogfoodingReminderHandler,
)


class TestDogfoodingReminderHandler:
    """Test suite for DogfoodingReminderHandler."""

    @pytest.fixture
    def handler(self) -> DogfoodingReminderHandler:
        """Create handler instance."""
        return DogfoodingReminderHandler()

    @pytest.fixture
    def session_start_input(self) -> dict[str, Any]:
        """Create SessionStart hook input."""
        return {
            HookInputField.HOOK_EVENT_NAME: "SessionStart",
        }

    def test_initialization(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler initializes correctly."""
        assert handler.handler_id == HANDLER_ID
        assert handler.terminal is False

    def test_priority(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler has correct priority."""
        assert handler.priority == PRIORITY

    def test_tags(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler has correct tags including dogfooding."""
        assert TAG_DOGFOODING in handler.tags

    def test_matches_session_start(
        self, handler: DogfoodingReminderHandler, session_start_input: dict[str, Any]
    ) -> None:
        """Test handler matches SessionStart events."""
        assert handler.matches(session_start_input) is True

    def test_does_not_match_other_events(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler does not match non-SessionStart events."""
        other_inputs = [
            {HookInputField.HOOK_EVENT_NAME: "PreToolUse"},
            {HookInputField.HOOK_EVENT_NAME: "PostToolUse"},
            {HookInputField.HOOK_EVENT_NAME: "SessionEnd"},
        ]

        for hook_input in other_inputs:
            assert handler.matches(hook_input) is False

    def test_handle_returns_allow(
        self, handler: DogfoodingReminderHandler, session_start_input: dict[str, Any]
    ) -> None:
        """Test handler returns ALLOW decision."""
        result = handler.handle(session_start_input)

        assert result.decision == Decision.ALLOW
        assert result.reason is None

    def test_handle_includes_dogfooding_notice(
        self, handler: DogfoodingReminderHandler, session_start_input: dict[str, Any]
    ) -> None:
        """Test handler includes dogfooding notice in context."""
        result = handler.handle(session_start_input)

        context = "\n".join(result.context)
        assert "DOGFOODING" in context.upper()
        assert "hooks daemon" in context.lower()

    def test_handle_includes_bug_workflow(
        self, handler: DogfoodingReminderHandler, session_start_input: dict[str, Any]
    ) -> None:
        """Test handler explains bug workflow."""
        result = handler.handle(session_start_input)

        context = "\n".join(result.context)
        assert "TDD" in context
        assert "reproduction" in context.lower()
        assert "sub-agent" in context.lower() or "sub agent" in context.lower()

    def test_handle_includes_stop_and_fix_directive(
        self, handler: DogfoodingReminderHandler, session_start_input: dict[str, Any]
    ) -> None:
        """Test handler emphasizes stopping work to fix bugs."""
        result = handler.handle(session_start_input)

        context = "\n".join(result.context)
        assert "STOP" in context.upper() or "stop" in context.lower()
        assert "bug" in context.lower()

    def test_handle_includes_plan_workflow_for_big_bugs(
        self, handler: DogfoodingReminderHandler, session_start_input: dict[str, Any]
    ) -> None:
        """Test handler mentions plan workflow for bigger bugs."""
        result = handler.handle(session_start_input)

        context = "\n".join(result.context)
        assert "plan" in context.lower()
        assert "bigger" in context.lower() or "complex" in context.lower()

    def test_handler_is_non_terminal(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler is non-terminal (never blocks)."""
        assert handler.terminal is False

    def test_handle_with_none_input(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler handles None input gracefully."""
        assert handler.matches(None) is False

    def test_handle_with_string_input(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler handles string input gracefully."""
        invalid_input: Any = "not a dict"
        assert handler.matches(invalid_input) is False

    def test_handle_with_list_input(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler handles list input gracefully."""
        invalid_input: Any = []
        assert handler.matches(invalid_input) is False

    def test_handle_with_int_input(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler handles integer input gracefully."""
        invalid_input: Any = 123
        assert handler.matches(invalid_input) is False

    def test_acceptance_tests_defined(self, handler: DogfoodingReminderHandler) -> None:
        """Test handler has acceptance tests defined."""
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
        assert tests[0].title is not None
        assert tests[0].expected_decision == Decision.ALLOW
