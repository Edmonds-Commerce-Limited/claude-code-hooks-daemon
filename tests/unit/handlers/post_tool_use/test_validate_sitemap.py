"""Tests for ValidateSitemapHandler."""

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.validate_sitemap import (
    ValidateSitemapHandler,
)


class TestValidateSitemapHandler:
    """Tests for ValidateSitemapHandler."""

    @pytest.fixture
    def handler(self) -> ValidateSitemapHandler:
        """Create handler instance."""
        return ValidateSitemapHandler()

    def test_initialization(self, handler: ValidateSitemapHandler) -> None:
        """Handler should initialize with correct attributes."""
        assert handler.name == "validate-sitemap-on-edit"
        assert handler.priority == 20
        assert "validation" in handler.tags
        assert "advisory" in handler.tags

    def test_matches_sitemap_file(self, handler: ValidateSitemapHandler) -> None:
        """Should match sitemap markdown files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Sitemap/components.md",
            },
        }

        assert handler.matches(hook_input) is True

    def test_matches_nested_sitemap_file(self, handler: ValidateSitemapHandler) -> None:
        """Should match sitemap files in subdirectories."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Sitemap/pages/home.md",
            },
        }

        assert handler.matches(hook_input) is True

    def test_matches_edit_tool(self, handler: ValidateSitemapHandler) -> None:
        """Should match Edit tool on sitemap files."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Sitemap/layout.md",
            },
        }

        assert handler.matches(hook_input) is True

    def test_does_not_match_claude_md(self, handler: ValidateSitemapHandler) -> None:
        """Should not match CLAUDE/Sitemap/CLAUDE.md documentation file."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Sitemap/CLAUDE.md",
            },
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_non_sitemap_files(self, handler: ValidateSitemapHandler) -> None:
        """Should not match files outside Sitemap directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/components.md",
            },
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_non_markdown_files(self, handler: ValidateSitemapHandler) -> None:
        """Should not match non-markdown files in Sitemap directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Sitemap/data.json",
            },
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_non_write_tools(self, handler: ValidateSitemapHandler) -> None:
        """Should not match tools other than Write/Edit."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "echo test",
            },
        }

        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_file_path(self, handler: ValidateSitemapHandler) -> None:
        """Should not match when file_path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {},
        }

        assert handler.matches(hook_input) is False

    def test_handle_returns_reminder(self, handler: ValidateSitemapHandler) -> None:
        """Should return reminder with validation instructions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Sitemap/components.md",
            },
        }

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "REMINDER" in result.context[0]
        assert "sitemap-validator" in result.context[0]
        assert "components.md" in result.context[0]

    def test_handle_includes_validation_checklist(self, handler: ValidateSitemapHandler) -> None:
        """Reminder should include validation checklist."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Sitemap/pages.md",
            },
        }

        result = handler.handle(hook_input)

        context_text = result.context[0]
        assert "No content" in context_text
        assert "No hallucinated components" in context_text
        assert "No implementation details" in context_text
        assert "Correct notation" in context_text

    def test_handle_includes_task_tool_syntax(self, handler: ValidateSitemapHandler) -> None:
        """Reminder should include Task tool syntax."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/Sitemap/layout.md",
            },
        }

        result = handler.handle(hook_input)

        context_text = result.context[0]
        assert "Task tool:" in context_text
        assert "subagent_type: sitemap-validator" in context_text
        assert "model: haiku" in context_text

    def test_handle_includes_file_path_in_reminder(self, handler: ValidateSitemapHandler) -> None:
        """Reminder should include the specific file path."""
        test_path = "/workspace/CLAUDE/Sitemap/custom-section.md"
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": test_path,
            },
        }

        result = handler.handle(hook_input)

        assert test_path in result.context[0]

    def test_handle_different_sitemap_files(self, handler: ValidateSitemapHandler) -> None:
        """Should handle different sitemap file names."""
        file_paths = [
            "/workspace/CLAUDE/Sitemap/components.md",
            "/workspace/CLAUDE/Sitemap/pages.md",
            "/workspace/CLAUDE/Sitemap/layouts.md",
            "/workspace/CLAUDE/Sitemap/sections/header.md",
        ]

        for file_path in file_paths:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {"file_path": file_path},
            }

            result = handler.handle(hook_input)
            assert result.decision == Decision.ALLOW
            assert file_path in result.context[0]

    def test_non_terminal_handler(self, handler: ValidateSitemapHandler) -> None:
        """Handler should be non-terminal (allow chain continuation)."""
        # Check if handler is terminal (it shouldn't be)
        # Non-terminal handlers allow other handlers to run
        assert "non-terminal" in handler.tags

    def test_advisory_tag(self, handler: ValidateSitemapHandler) -> None:
        """Handler should have advisory tag (informational only)."""
        assert "advisory" in handler.tags
