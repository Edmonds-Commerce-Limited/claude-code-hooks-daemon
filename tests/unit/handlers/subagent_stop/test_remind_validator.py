"""Tests for RemindValidatorHandler."""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.subagent_stop.remind_validator import (
    RemindValidatorHandler,
)


class TestRemindValidatorHandler:
    """Test RemindValidatorHandler initialization and configuration."""

    @pytest.fixture
    def handler(self) -> RemindValidatorHandler:
        """Create handler instance for testing."""
        return RemindValidatorHandler()

    def test_handler_initialization(self, handler: RemindValidatorHandler) -> None:
        """Handler initializes with correct attributes."""
        assert handler.name == "remind-validate-after-builder"
        assert handler.priority == 10
        assert "workflow" in handler.tags
        assert "validation" in handler.tags
        assert "ec-specific" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags

    def test_builder_to_validator_mapping_defined(self, handler: RemindValidatorHandler) -> None:
        """Handler has builder to validator mapping defined."""
        assert len(handler.BUILDER_TO_VALIDATOR) > 0
        assert isinstance(handler.BUILDER_TO_VALIDATOR, dict)

    def test_builder_mapping_structure(self, handler: RemindValidatorHandler) -> None:
        """Builder mappings have required structure."""
        for builder, config in handler.BUILDER_TO_VALIDATOR.items():
            assert "validator" in config
            assert "description" in config
            assert "validation_target" in config
            assert "validation_command" in config
            assert isinstance(config["validator"], str)
            assert isinstance(config["description"], str)


class TestMatches:
    """Test match detection logic."""

    @pytest.fixture
    def handler(self) -> RemindValidatorHandler:
        """Create handler instance for testing."""
        return RemindValidatorHandler()

    @pytest.fixture
    def transcript_file(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file."""
        return tmp_path / "transcript.jsonl"

    def _write_task_tool_use(self, transcript_file: Path, subagent_type: str) -> None:
        """Helper to write a Task tool use to transcript."""
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Task",
                        "input": {"subagent_type": subagent_type},
                    }
                ],
            },
        }
        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

    def test_matches_sitemap_modifier_completion(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Matches when sitemap-modifier agent completes."""
        self._write_task_tool_use(transcript_file, "sitemap-modifier")

        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": str(transcript_file),
        }

        assert handler.matches(hook_input) is True

    def test_matches_page_implementer_completion(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Matches when page-implementer agent completes."""
        self._write_task_tool_use(transcript_file, "page-implementer")

        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": str(transcript_file),
        }

        assert handler.matches(hook_input) is True

    def test_does_not_match_wrong_event(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Does not match if event is not SubagentStop."""
        self._write_task_tool_use(transcript_file, "sitemap-modifier")

        hook_input: dict[str, Any] = {
            "hook_event_name": "PreToolUse",
            "transcript_path": str(transcript_file),
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_without_transcript_path(self, handler: RemindValidatorHandler) -> None:
        """Does not match if transcript path is missing."""
        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": "",
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_unknown_agent(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Does not match if completed agent has no validator."""
        self._write_task_tool_use(transcript_file, "unknown-agent")

        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": str(transcript_file),
        }

        assert handler.matches(hook_input) is False

    def test_matches_all_configured_builders(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Matches all configured builder agents."""
        for builder in handler.BUILDER_TO_VALIDATOR.keys():
            self._write_task_tool_use(transcript_file, builder)

            hook_input: dict[str, Any] = {
                "hook_event_name": "SubagentStop",
                "transcript_path": str(transcript_file),
            }

            assert handler.matches(hook_input) is True


class TestHandle:
    """Test handle logic."""

    @pytest.fixture
    def handler(self) -> RemindValidatorHandler:
        """Create handler instance for testing."""
        return RemindValidatorHandler()

    @pytest.fixture
    def transcript_file(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file."""
        return tmp_path / "transcript.jsonl"

    def _write_task_tool_use(self, transcript_file: Path, subagent_type: str) -> None:
        """Helper to write a Task tool use to transcript."""
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Task",
                        "input": {"subagent_type": subagent_type},
                    }
                ],
            },
        }
        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

    def test_returns_reminder_for_sitemap_modifier(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Returns reminder to run sitemap-validator."""
        self._write_task_tool_use(transcript_file, "sitemap-modifier")

        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": str(transcript_file),
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "sitemap-modifier" in result.context[0]
        assert "sitemap-validator" in result.context[0]
        assert "sitemap modifications" in result.context[0]

    def test_returns_reminder_for_page_implementer(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Returns reminder to run page-technical-reviewer."""
        self._write_task_tool_use(transcript_file, "page-implementer")

        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": str(transcript_file),
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "page-implementer" in result.context[0]
        assert "page-technical-reviewer" in result.context[0]
        assert "page implementation" in result.context[0]

    def test_returns_allow_for_unknown_agent(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Returns ALLOW without reminder for unknown agent."""
        self._write_task_tool_use(transcript_file, "unknown-agent")

        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": str(transcript_file),
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 0

    def test_reminder_includes_validation_command(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Reminder includes the validation command."""
        self._write_task_tool_use(transcript_file, "sitemap-modifier")

        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": str(transcript_file),
        }

        result = handler.handle(hook_input)

        assert "Task tool:" in result.context[0]
        assert "subagent_type: sitemap-validator" in result.context[0]

    def test_reminder_includes_validation_target(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Reminder includes the validation target."""
        self._write_task_tool_use(transcript_file, "sitemap-modifier")

        hook_input: dict[str, Any] = {
            "hook_event_name": "SubagentStop",
            "transcript_path": str(transcript_file),
        }

        result = handler.handle(hook_input)

        assert "CLAUDE/Sitemap/ files" in result.context[0]


class TestGetLastCompletedAgent:
    """Test transcript parsing logic."""

    @pytest.fixture
    def handler(self) -> RemindValidatorHandler:
        """Create handler instance for testing."""
        return RemindValidatorHandler()

    @pytest.fixture
    def transcript_file(self, tmp_path: Path) -> Path:
        """Create a temporary transcript file."""
        return tmp_path / "transcript.jsonl"

    def test_extracts_subagent_type_from_task_tool(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Extracts subagent_type from Task tool use."""
        message = {
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

        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

        result = handler._get_last_completed_agent(str(transcript_file))
        assert result == "sitemap-modifier"

    def test_returns_most_recent_task_tool(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Returns most recent Task tool when multiple exist."""
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {"subagent_type": "first-agent"},
                        }
                    ],
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {"subagent_type": "second-agent"},
                        }
                    ],
                },
            },
        ]

        with transcript_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        result = handler._get_last_completed_agent(str(transcript_file))
        assert result == "second-agent"

    def test_ignores_non_task_tools(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Ignores tool uses that are not Task."""
        messages = [
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        }
                    ],
                },
            },
            {
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
            },
        ]

        with transcript_file.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        result = handler._get_last_completed_agent(str(transcript_file))
        assert result == "sitemap-modifier"

    def test_returns_empty_for_missing_file(self, handler: RemindValidatorHandler) -> None:
        """Returns empty string for missing file."""
        result = handler._get_last_completed_agent("/nonexistent/file.jsonl")
        assert result == ""

    def test_handles_invalid_json_lines(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Handles transcript with invalid JSON lines."""
        with transcript_file.open("w") as f:
            f.write("invalid json\n")
            f.write(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "Task",
                                    "input": {"subagent_type": "valid-agent"},
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )

        result = handler._get_last_completed_agent(str(transcript_file))
        assert result == "valid-agent"

    def test_returns_empty_for_no_task_tools(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Returns empty string when no Task tools found."""
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Some text"}],
            },
        }

        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

        result = handler._get_last_completed_agent(str(transcript_file))
        assert result == ""

    def test_handles_missing_subagent_type(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Handles Task tool without subagent_type."""
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Task",
                        "input": {"other_field": "value"},
                    }
                ],
            },
        }

        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

        result = handler._get_last_completed_agent(str(transcript_file))
        assert result == ""

    def test_handles_exception_gracefully(self, handler: RemindValidatorHandler) -> None:
        """Handles exceptions gracefully and returns empty string."""
        result = handler._get_last_completed_agent("/invalid\x00path.jsonl")
        assert result == ""

    def test_handles_multiple_content_blocks(
        self, handler: RemindValidatorHandler, transcript_file: Path
    ) -> None:
        """Handles message with multiple content blocks."""
        message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Some text"},
                    {
                        "type": "tool_use",
                        "name": "Task",
                        "input": {"subagent_type": "test-agent"},
                    },
                ],
            },
        }

        with transcript_file.open("w") as f:
            f.write(json.dumps(message) + "\n")

        result = handler._get_last_completed_agent(str(transcript_file))
        assert result == "test-agent"
