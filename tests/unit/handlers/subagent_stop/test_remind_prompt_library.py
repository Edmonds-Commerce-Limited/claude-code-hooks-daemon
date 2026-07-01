"""Tests for RemindPromptLibraryHandler."""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.subagent_stop.remind_prompt_library import (
    RemindPromptLibraryHandler,
)


class TestRemindPromptLibraryHandler:
    """Test RemindPromptLibraryHandler."""

    @pytest.fixture
    def handler(self) -> RemindPromptLibraryHandler:
        """Create handler instance for testing."""
        return RemindPromptLibraryHandler()

    def test_handler_initialization(self, handler: RemindPromptLibraryHandler) -> None:
        """Handler initializes with correct attributes."""
        assert handler.name == "remind-capture-prompt"
        assert handler.priority == 100
        assert "workflow" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags

    def test_matches_always_returns_true(self, handler: RemindPromptLibraryHandler) -> None:
        """Handler always matches (reminds after every sub-agent)."""
        hook_input: dict[str, Any] = {}
        assert handler.matches(hook_input) is True

        hook_input = {"subagent_type": "test-agent"}
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow_with_reminder(self, handler: RemindPromptLibraryHandler) -> None:
        """Handle returns ALLOW with reminder message."""
        hook_input: dict[str, Any] = {"subagent_type": "test-agent"}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert result.context
        assert "test-agent" in "\n".join(result.context)
        assert "completed" in "\n".join(result.context)

    def test_reminder_includes_capture_instructions(
        self, handler: RemindPromptLibraryHandler
    ) -> None:
        """Reminder includes npm command for capturing prompts."""
        hook_input: dict[str, Any] = {"subagent_type": "sitemap-modifier"}

        result = handler.handle(hook_input)

        assert "npm run llm:prompts" in "\n".join(result.context)
        assert "add --from-json" in "\n".join(result.context)

    def test_reminder_includes_benefits(self, handler: RemindPromptLibraryHandler) -> None:
        """Reminder includes benefits of capturing prompts."""
        hook_input: dict[str, Any] = {"subagent_type": "test-agent"}

        result = handler.handle(hook_input)

        assert "Reuse successful prompts" in "\n".join(result.context)
        assert "Track what works" in "\n".join(result.context)
        assert "institutional knowledge" in "\n".join(result.context)

    def test_reminder_includes_documentation_link(
        self, handler: RemindPromptLibraryHandler
    ) -> None:
        """Reminder includes link to documentation."""
        hook_input: dict[str, Any] = {"subagent_type": "test-agent"}

        result = handler.handle(hook_input)

        assert "CLAUDE/PromptLibrary/README.md" in "\n".join(result.context)

    def test_handles_missing_subagent_type(self, handler: RemindPromptLibraryHandler) -> None:
        """Handles missing subagent_type gracefully."""
        hook_input: dict[str, Any] = {}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert "unknown" in "\n".join(result.context)

    def test_uses_provided_subagent_type_in_message(
        self, handler: RemindPromptLibraryHandler
    ) -> None:
        """Uses the provided subagent_type in the message."""
        hook_input: dict[str, Any] = {"subagent_type": "custom-agent-name"}

        result = handler.handle(hook_input)

        assert "custom-agent-name" in "\n".join(result.context)

    def test_reminder_survives_stop_formatting(self, handler: RemindPromptLibraryHandler) -> None:
        """The reminder must actually reach the user via to_json('Stop').

        Regression test: an ALLOW decision's context was previously ignored
        entirely by HookResult._format_stop_response for Stop/SubagentStop
        events, and this handler put its whole message in `reason` (which
        was also dropped) - making it a complete no-op in production.
        """
        hook_input: dict[str, Any] = {"subagent_type": "test-agent"}
        result = handler.handle(hook_input)
        response = result.to_json("Stop")
        additional_context = response["hookSpecificOutput"]["additionalContext"]
        assert "test-agent" in additional_context
        assert "completed" in additional_context

    def test_reminder_survives_subagent_stop_formatting(
        self, handler: RemindPromptLibraryHandler
    ) -> None:
        """The reminder must also reach the user via to_json('SubagentStop')."""
        hook_input: dict[str, Any] = {"subagent_type": "test-agent"}
        result = handler.handle(hook_input)
        response = result.to_json("SubagentStop")
        additional_context = response["hookSpecificOutput"]["additionalContext"]
        assert "test-agent" in additional_context
