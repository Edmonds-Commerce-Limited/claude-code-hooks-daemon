"""Tests for ValidateInstructionContentHandler."""

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.validate_instruction_content import (
    ValidateInstructionContentHandler,
)


@pytest.fixture
def handler() -> ValidateInstructionContentHandler:
    """Create handler instance."""
    return ValidateInstructionContentHandler()


@pytest.fixture
def mock_read_tool_call() -> dict[str, Any]:
    """Create mock Read tool call."""
    return {
        "tool_name": "Read",
        "tool_input": {"file_path": "/some/path/CLAUDE.md"},
    }


@pytest.fixture
def mock_write_tool_call() -> dict[str, Any]:
    """Create mock Write tool call."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/some/path/CLAUDE.md",
            "content": "# Clean content\n\nThis is acceptable.",
        },
    }


@pytest.fixture
def mock_edit_tool_call() -> dict[str, Any]:
    """Create mock Edit tool call."""
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/some/path/README.md",
            "old_string": "old text",
            "new_string": "new text",
        },
    }


class TestMatches:
    """Test applies() method."""

    def test_applies_to_write_tool_with_claude_md(
        self, handler: ValidateInstructionContentHandler
    ) -> None:
        """Test applies to Write tool with CLAUDE.md."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/path/to/CLAUDE.md", "content": "test"},
        }
        assert handler.matches(hook_input) is True

    def test_applies_to_write_tool_with_readme_md(
        self, handler: ValidateInstructionContentHandler
    ) -> None:
        """Test applies to Write tool with README.md."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/path/to/README.md", "content": "test"},
        }
        assert handler.matches(hook_input) is True

    def test_applies_to_edit_tool_with_claude_md(
        self, handler: ValidateInstructionContentHandler
    ) -> None:
        """Test applies to Edit tool with CLAUDE.md."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/path/CLAUDE.md",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is True

    def test_applies_to_edit_tool_with_readme_md(
        self, handler: ValidateInstructionContentHandler
    ) -> None:
        """Test applies to Edit tool with README.md."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/path/README.md",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is True

    def test_does_not_apply_to_other_tools(
        self, handler: ValidateInstructionContentHandler
    ) -> None:
        """Test does not apply to other tools."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_apply_to_other_files(
        self, handler: ValidateInstructionContentHandler
    ) -> None:
        """Test does not apply to other files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/path/to/other.md", "content": "test"},
        }
        assert handler.matches(hook_input) is False


class TestImplementationLogs:
    """Test detection of implementation logs."""

    def test_blocks_created_file_log(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'created file' implementation log."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\nCreated the file ProductService.php"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"
        assert "implementation logs" in result.reason.lower()

    def test_blocks_added_class_log(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'added class' implementation log."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\nAdded class CustomerService to handle logic"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_modified_function_log(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'modified function' implementation log."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\nModified the function calculateTotal()"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_updated_directory_log(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'updated directory' implementation log."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\nUpdated directory structure for services"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_implemented_feature_log(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'implemented' feature log."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\nImplemented feature for email validation"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"


class TestStatusIndicators:
    """Test detection of status indicators."""

    def test_blocks_checkmark_complete(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks checkmark with 'complete'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\n✓ Complete implementation"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"
        assert "status indicators" in result.reason.lower()

    def test_blocks_green_circle_done(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks green circle with 'done'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\n🟢 Done with refactoring"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_checkmark_emoji_success(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks checkmark emoji with 'success'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\n✅ Success in testing"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_checkmark_fixed(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks checkmark with 'fixed'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\n✓ Fixed the bug"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"


class TestTimestamps:
    """Test detection of timestamps."""

    def test_blocks_iso_date_format(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks ISO date format."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\nLast updated: 2024-03-15"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"
        assert "timestamps" in result.reason.lower()

    def test_blocks_timestamp_in_middle(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks timestamp in middle of text."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\nUpdated on 2025-12-25 with new features"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"


class TestLlmSummaries:
    """Test detection of LLM summaries."""

    def test_blocks_summary_heading(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks '## Summary' heading."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\n## Summary\n\nThis project does X"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"
        assert "llm summaries" in result.reason.lower()

    def test_blocks_key_points_heading(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks '## Key Points' heading."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\n## Key Points\n\n- Point one\n- Point two"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_overview_heading(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks '## Overview' heading."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\n## Overview\n\nThis is an overview of changes"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"


class TestTestOutput:
    """Test detection of test output."""

    def test_blocks_tests_passed(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'X tests passed'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\n42 tests passed"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"
        assert "test output" in result.reason.lower()

    def test_blocks_test_failed(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks '1 test failed'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\n1 test failed with error"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_tests_executed(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'X tests executed'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\n15 tests executed successfully"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"


class TestFileListings:
    """Test detection of file listings."""

    def test_blocks_file_listing_with_php_extension(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks file listing with .php extension."""
        mock_write_tool_call["tool_input"]["content"] = (
            "# Instructions\n\nsrc/Service/ProductService.php"
        )
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"
        assert "file listings" in result.reason.lower()

    def test_blocks_file_listing_with_js_extension(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks file listing with .js extension."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\nassets/js/main.js modified"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_file_listing_with_md_extension(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks file listing with .md extension."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\ndocs/README.md exists"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"


class TestChangeSummaries:
    """Test detection of change summaries."""

    def test_blocks_added_lines(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'Added X lines'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\nAdded 15 lines to implement feature"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"
        assert "change summaries" in result.reason.lower()

    def test_blocks_removed_lines(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'Removed X lines'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\nRemoved 8 lines of dead code"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_changed_lines(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'Changed X lines'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\nChanged 3 lines for validation"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"


class TestCompletionIndicators:
    """Test detection of completion indicators."""

    def test_blocks_all_done(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'ALL DONE'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\nALL DONE!"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"
        assert "completion indicators" in result.reason.lower()

    def test_blocks_task_complete(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'Task complete'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\nTask complete!"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_blocks_finished_task(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks 'Finished task'."""
        mock_write_tool_call["tool_input"]["content"] = "# Instructions\n\nFinished task successfully"
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"


class TestCodeBlockExemption:
    """Test code block exemption logic."""

    def test_allows_implementation_log_in_code_block(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test allows implementation log inside code block."""
        mock_write_tool_call["tool_input"]["content"] = """# Instructions

Example output:
```
Created the file ProductService.php
```

This is acceptable."""
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "allow"

    def test_allows_status_indicator_in_code_block(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test allows status indicator inside code block."""
        mock_write_tool_call["tool_input"]["content"] = """# Instructions

Example status:
```
✓ Complete implementation
```

This is fine."""
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "allow"

    def test_allows_timestamp_in_code_block(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test allows timestamp inside code block."""
        mock_write_tool_call["tool_input"]["content"] = """# Instructions

Example date:
```
Last updated: 2024-03-15
```

Timestamps in examples are OK."""
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "allow"

    def test_blocks_pattern_after_code_block(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test blocks pattern after code block ends."""
        mock_write_tool_call["tool_input"]["content"] = """# Instructions

Example:
```
Some code here
```

Created the file ProductService.php outside code block"""
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "deny"

    def test_handles_multiple_code_blocks(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test handles multiple code blocks correctly."""
        mock_write_tool_call["tool_input"]["content"] = """# Instructions

First example:
```
Created file A.php
```

Some text here

Second example:
```
Created file B.php
```

All patterns are in code blocks."""
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "allow"


class TestEditTool:
    """Test Edit tool handling."""

    def test_checks_new_string_in_edit_tool(
        self, handler: ValidateInstructionContentHandler, mock_edit_tool_call: dict[str, Any]
    ) -> None:
        """Test checks new_string in Edit tool."""
        mock_edit_tool_call["tool_input"]["new_string"] = "Created the file ProductService.php"
        result = handler.handle(mock_edit_tool_call)
        assert result.decision == "deny"

    def test_allows_clean_edit(
        self, handler: ValidateInstructionContentHandler, mock_edit_tool_call: dict[str, Any]
    ) -> None:
        """Test allows clean edit."""
        mock_edit_tool_call["tool_input"]["new_string"] = "Clean instructional content"
        result = handler.handle(mock_edit_tool_call)
        assert result.decision == "allow"


class TestCleanContent:
    """Test that clean content is allowed."""

    def test_allows_clean_instructions(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test allows clean instructions."""
        mock_write_tool_call["tool_input"]["content"] = """# Project Instructions

## Coding Standards

- Use strict types
- Follow PSR-12
- Write tests

## Testing

Run tests with PHPUnit.
"""
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "allow"

    def test_allows_readme_with_features(
        self, handler: ValidateInstructionContentHandler, mock_write_tool_call: dict[str, Any]
    ) -> None:
        """Test allows README with feature descriptions."""
        mock_write_tool_call["tool_input"][
            "content"
        ] = """# My Project

## Features

- User authentication
- Product catalog
- Shopping cart

## Installation

Run `composer install` to set up."""
        result = handler.handle(mock_write_tool_call)
        assert result.decision == "allow"
