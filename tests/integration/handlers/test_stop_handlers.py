"""Integration tests for Stop and SubagentStop handlers.

Tests: TaskCompletionCheckerHandler, AutoContinueStopHandler,
       SubagentCompletionLoggerHandler, RemindValidatorHandler,
       RemindPromptLibraryHandler
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import (
    make_stop_input,
    make_subagent_stop_input,
)


# ---------------------------------------------------------------------------
# TaskCompletionCheckerHandler
# ---------------------------------------------------------------------------
class TestTaskCompletionCheckerHandler:
    """Integration tests for TaskCompletionCheckerHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.task_completion_checker import (
            TaskCompletionCheckerHandler,
        )

        return TaskCompletionCheckerHandler()

    def test_matches_all_stop_events(self, handler: Any) -> None:
        hook_input = make_stop_input()
        assert handler.matches(hook_input) is True

    def test_provides_completion_reminder(self, handler: Any) -> None:
        hook_input = make_stop_input()
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context is not None
        assert len(result.context) > 0
        assert "Task Completion Checklist" in result.context[0]

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False


# ---------------------------------------------------------------------------
# AutoContinueStopHandler
# ---------------------------------------------------------------------------
class TestAutoContinueStopHandler:
    """Integration tests for AutoContinueStopHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
            AutoContinueStopHandler,
        )

        return AutoContinueStopHandler()

    def test_blocks_confirmation_question(self, handler: Any, tmp_path: Any) -> None:
        # Create a transcript with a confirmation question
        transcript = tmp_path / "transcript.jsonl"
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Would you like me to continue with the next step?"}
                ],
            },
        }
        transcript.write_text(json.dumps(message) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path=str(transcript),
        )
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "AUTO-CONTINUE" in result.reason

    def test_prevents_infinite_loop(self, handler: Any, tmp_path: Any) -> None:
        # When stop_hook_active is True, should not match (prevents loop)
        transcript = tmp_path / "transcript.jsonl"
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Would you like me to continue?"}],
            },
        }
        transcript.write_text(json.dumps(message) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=True,
            transcript_path=str(transcript),
        )
        assert handler.matches(hook_input) is False

    def test_ignores_error_questions(self, handler: Any, tmp_path: Any) -> None:
        transcript = tmp_path / "transcript.jsonl"
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Error: build failed. What would you like me to do?"}
                ],
            },
        }
        transcript.write_text(json.dumps(message) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path=str(transcript),
        )
        assert handler.matches(hook_input) is False

    def test_ignores_non_question(self, handler: Any, tmp_path: Any) -> None:
        transcript = tmp_path / "transcript.jsonl"
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "All tasks completed successfully."}],
            },
        }
        transcript.write_text(json.dumps(message) + "\n")

        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path=str(transcript),
        )
        assert handler.matches(hook_input) is False

    def test_handles_missing_transcript(self, handler: Any) -> None:
        hook_input = make_stop_input(
            stop_hook_active=False,
            transcript_path="/nonexistent/transcript.jsonl",
        )
        assert handler.matches(hook_input) is False

    def test_handler_is_terminal(self, handler: Any) -> None:
        assert handler.terminal is True


# ---------------------------------------------------------------------------
# SubagentCompletionLoggerHandler
# ---------------------------------------------------------------------------
class TestSubagentCompletionLoggerHandler:
    """Integration tests for SubagentCompletionLoggerHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.subagent_stop.subagent_completion_logger import (
            SubagentCompletionLoggerHandler,
        )

        return SubagentCompletionLoggerHandler()

    def test_matches_all_subagent_events(self, handler: Any) -> None:
        hook_input = make_subagent_stop_input()
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow(self, handler: Any) -> None:
        hook_input = make_subagent_stop_input(
            transcript_path="/tmp/transcript.jsonl",
            subagent_type="task",
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False


# ---------------------------------------------------------------------------
# RemindValidatorHandler
# ---------------------------------------------------------------------------
class TestRemindValidatorHandler:
    """Integration tests for RemindValidatorHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.subagent_stop.remind_validator import (
            RemindValidatorHandler,
        )

        return RemindValidatorHandler()

    def test_does_not_match_without_builder_agent(self, handler: Any) -> None:
        # Without a transcript containing a builder agent, should not match
        hook_input = make_subagent_stop_input()
        assert handler.matches(hook_input) is False

    def test_matches_when_builder_agent_completed(self, handler: Any, tmp_path: Any) -> None:
        # Create transcript with a known builder agent
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Task",
                        "input": {"subagent_type": "sitemap-modifier"},
                    }
                ],
            },
        }
        transcript.write_text(json.dumps(entry) + "\n")

        hook_input = make_subagent_stop_input(transcript_path=str(transcript))
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow_with_reminder(self, handler: Any, tmp_path: Any) -> None:
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Task",
                        "input": {"subagent_type": "sitemap-modifier"},
                    }
                ],
            },
        }
        transcript.write_text(json.dumps(entry) + "\n")

        hook_input = make_subagent_stop_input(transcript_path=str(transcript))
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context is not None
        assert len(result.context) > 0
        assert "sitemap-validator" in result.context[0]

    def test_handler_is_terminal(self, handler: Any) -> None:
        assert handler.terminal is True


# ---------------------------------------------------------------------------
# RemindPromptLibraryHandler
# ---------------------------------------------------------------------------
class TestRemindPromptLibraryHandler:
    """Integration tests for RemindPromptLibraryHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.subagent_stop.remind_prompt_library import (
            RemindPromptLibraryHandler,
        )

        return RemindPromptLibraryHandler()

    def test_matches_subagent_stop(self, handler: Any) -> None:
        hook_input = make_subagent_stop_input()
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow(self, handler: Any) -> None:
        hook_input = make_subagent_stop_input(subagent_type="explore")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handler_is_terminal(self, handler: Any) -> None:
        assert handler.terminal is True
