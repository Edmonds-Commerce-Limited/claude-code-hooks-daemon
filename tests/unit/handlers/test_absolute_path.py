"""Comprehensive tests for AbsolutePathHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.absolute_path import AbsolutePathHandler


class TestAbsolutePathHandler:
    """Test suite for AbsolutePathHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return AbsolutePathHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'require-absolute-paths'."""
        assert handler.name == "require-absolute-paths"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 12."""
        assert handler.priority == 12

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    # matches() - Positive Cases: Relative paths (should match)
    def test_matches_write_with_relative_path(self, handler):
        """Should match Write with relative path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.py",
                "content": "print('hello')",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_read_with_relative_path(self, handler):
        """Should match Read with relative path."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "README.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_with_relative_path(self, handler):
        """Should match Edit with relative path."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "config.py",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_nested_relative_path(self, handler):
        """Should match Write with nested relative path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/components/Header.tsx",
                "content": "export function Header() {}",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_parent_directory_path(self, handler):
        """Should match Write with parent directory path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "../config/settings.py",
                "content": "SETTINGS = {}",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Absolute paths (should not match)
    def test_matches_write_with_absolute_path_returns_false(self, handler):
        """Should not match Write with absolute path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/test.py",
                "content": "print('hello')",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_with_absolute_path_returns_false(self, handler):
        """Should not match Read with absolute path."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_with_absolute_path_returns_false(self, handler):
        """Should not match Edit with absolute path."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/config.py",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_bash_tool_returns_false(self, handler):
        """Should not match Bash tool (only Read/Write/Edit)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        assert handler.matches(hook_input) is False

    def test_matches_empty_file_path_returns_false(self, handler):
        """Should not match when file_path is empty."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "", "content": "test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_none_file_path_returns_false(self, handler):
        """Should not match when file_path is None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": None, "content": "test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_file_path_returns_false(self, handler):
        """Should not match when file_path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"content": "test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should not match when tool_input is missing."""
        hook_input = {"tool_name": "Write"}
        assert handler.matches(hook_input) is False

    # handle() Tests - Write Tool
    def test_handle_write_returns_deny_decision(self, handler):
        """handle() should return deny for Write tool with relative path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.py",
                "content": "print('hello')",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_write_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_write_reason_shows_relative_path(self, handler):
        """handle() reason should show the relative path provided."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "config.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert "config.py" in result.reason

    def test_handle_write_explains_why_absolute_required(self, handler):
        """handle() reason should explain why absolute paths are required."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert "absolute" in result.reason.lower()
        assert "required" in result.reason.lower()

    def test_handle_provides_example_absolute_path(self, handler):
        """handle() reason should provide example with /workspace/."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert "/workspace/" in result.reason

    # handle() Tests - Read Tool
    def test_handle_read_returns_deny_decision(self, handler):
        """handle() should return deny for Read tool with relative path."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    # handle() Tests - Edit Tool
    def test_handle_edit_returns_deny_decision(self, handler):
        """handle() should return deny for Edit tool with relative path."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "config.py",
                "old_string": "old",
                "new_string": "new",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_context_is_empty(self, handler):
        """handle() context should be empty (not used)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None (not used)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_allows_absolute_paths(self, handler):
        """Should allow absolute paths (not match)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/components/Header.tsx",
                "content": "export function Header() { return <div>Header</div>; }",
            },
        }
        assert handler.matches(hook_input) is False

    def test_blocks_relative_paths(self, handler):
        """Should block relative paths (match and deny)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/components/Header.tsx",
                "content": "export function Header() { return <div>Header</div>; }",
            },
        }
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == "deny"
