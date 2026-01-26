"""Comprehensive tests for AutoApproveReadsHandler."""

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.permission_request.auto_approve_reads import (
    AutoApproveReadsHandler,
)


class TestAutoApproveReadsHandler:
    """Test suite for AutoApproveReadsHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return AutoApproveReadsHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'auto-approve-safe-reads'."""
        assert handler.name == "auto-approve-safe-reads"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    # matches() - Positive Cases
    def test_matches_read_tool_md_file(self, handler):
        """Should match Read tool for .md files."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_read_tool_txt_file(self, handler):
        """Should match Read tool for .txt files."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/notes.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_read_tool_uppercase_md(self, handler):
        """Should match .MD extension (case insensitive)."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.MD"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_read_tool_uppercase_txt(self, handler):
        """Should match .TXT extension (case insensitive)."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/notes.TXT"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_read_tool_nested_path(self, handler):
        """Should match .md/.txt files in nested directories."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/docs/guides/setup.md"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases
    def test_matches_read_tool_py_file_returns_false(self, handler):
        """Should not match .py files."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/script.py"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_tool_js_file_returns_false(self, handler):
        """Should not match .js files."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/app.js"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_write_tool_returns_false(self, handler):
        """Should not match Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/README.md", "content": "test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_tool_returns_false(self, handler):
        """Should not match Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/README.md",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_bash_tool_returns_false(self, handler):
        """Should not match Bash tool."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat README.md"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_without_file_path_returns_false(self, handler):
        """Should not match when file_path is missing."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_with_none_file_path_returns_false(self, handler):
        """Should not match when file_path is None."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": None},
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_with_empty_file_path_returns_false(self, handler):
        """Should not match when file_path is empty string."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": ""},
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should not match when tool_input is missing."""
        hook_input = {"tool_name": "Read"}
        assert handler.matches(hook_input) is False

    # Edge Cases
    def test_matches_dotfile_md_returns_true(self, handler):
        """Should match .md dotfiles."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/.github/README.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_no_extension_returns_false(self, handler):
        """Should not match files without extension."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/Makefile"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_md_in_filename_but_different_ext_returns_false(self, handler):
        """Should not match files with .md in name but different extension."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/readme.md.bak"},
        }
        assert handler.matches(hook_input) is False

    # handle() Tests
    def test_handle_returns_allow_decision(self, handler):
        """handle() should return allow for safe reads."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_has_no_reason(self, handler):
        """handle() should not provide reason (auto-approval)."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/notes.txt"},
        }
        result = handler.handle(hook_input)
        assert result.reason is None

    def test_handle_has_no_context(self, handler):
        """handle() should not provide context."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_has_no_guidance(self, handler):
        """handle() should not provide guidance."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_returns_hook_result_instance(self, handler):
        """handle() should return HookResult instance."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
        }
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)
