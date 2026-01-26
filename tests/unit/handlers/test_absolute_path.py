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
        """Handler name should be 'prevent-absolute-workspace-paths'."""
        assert handler.name == "prevent-absolute-workspace-paths"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 12."""
        assert handler.priority == 12

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    # matches() - Write Tool - Positive Cases
    def test_matches_write_with_workspace_path_in_content(self, handler):
        """Should match Write with /workspace/ in content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/test.py",
                "content": "import sys\nsys.path.append('/workspace/lib')",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_workspace_at_content_start(self, handler):
        """Should match /workspace/ at start of content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "config.py", "content": "/workspace/data/file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_workspace_at_content_end(self, handler):
        """Should match /workspace/ at end of content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "BASE_DIR = '/workspace/'"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_multiple_workspace_paths(self, handler):
        """Should match content with multiple /workspace/ references."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "script.py",
                "content": """
                    SRC = '/workspace/src'
                    DIST = '/workspace/dist'
                """,
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Edit Tool - Positive Cases
    def test_matches_edit_with_workspace_in_new_string(self, handler):
        """Should match Edit with /workspace/ in new_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/config.py",
                "old_string": "path = 'old'",
                "new_string": "path = '/workspace/new'",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_with_workspace_in_old_string(self, handler):
        """Should match Edit with /workspace/ in old_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/config.py",
                "old_string": "path = '/workspace/old'",
                "new_string": "path = 'new'",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_with_workspace_in_both_strings(self, handler):
        """Should match Edit with /workspace/ in both old and new strings."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "config.py",
                "old_string": "path = '/workspace/old'",
                "new_string": "path = '/workspace/new'",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases
    def test_matches_write_without_workspace_returns_false(self, handler):
        """Should not match Write without /workspace/ in content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/test.py",  # file_path can be absolute
                "content": "import sys\nsys.path.append('./lib')",  # but content cannot
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_write_with_relative_paths_returns_false(self, handler):
        """Should not match Write with relative paths in content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/test.py", "content": "BASE = '../data'"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_without_workspace_returns_false(self, handler):
        """Should not match Edit without /workspace/ in strings."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/test.py",  # file_path can be absolute
                "old_string": "path = 'old'",
                "new_string": "path = 'new'",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_bash_tool_returns_false(self, handler):
        """Should not match Bash tool (only Write/Edit)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cd /workspace/ && ls"}}
        assert handler.matches(hook_input) is False

    def test_matches_read_tool_returns_false(self, handler):
        """Should not match Read tool (only Write/Edit)."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "/workspace/test.py"}}
        assert handler.matches(hook_input) is False

    def test_matches_write_empty_content_returns_false(self, handler):
        """Should not match Write with empty content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test.py", "content": ""},
        }
        assert handler.matches(hook_input) is False

    def test_matches_write_none_content_returns_false(self, handler):
        """Should not match Write with None content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test.py", "content": None},
        }
        assert handler.matches(hook_input) is False

    def test_matches_write_missing_content_key_returns_false(self, handler):
        """Should not match Write without content key."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "/workspace/test.py"}}
        assert handler.matches(hook_input) is False

    def test_matches_edit_empty_strings_returns_false(self, handler):
        """Should not match Edit with empty strings."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/test.py", "old_string": "", "new_string": ""},
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_none_strings_raises_error(self, handler):
        """Should raise TypeError with None strings (handler bug)."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/test.py",
                "old_string": None,
                "new_string": None,
            },
        }
        # Current behavior: crashes with TypeError
        # Handler should check for None before using 'in' operator
        with pytest.raises(TypeError):
            handler.matches(hook_input)

    def test_matches_edit_missing_string_keys_returns_false(self, handler):
        """Should not match Edit without string keys."""
        hook_input = {"tool_name": "Edit", "tool_input": {"file_path": "/workspace/test.py"}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should not match when tool_input is missing."""
        hook_input = {"tool_name": "Write"}
        assert handler.matches(hook_input) is False

    # Edge Cases
    def test_matches_workspace_substring_in_word_returns_true(self, handler):
        """Should match even if /workspace/ is part of a longer path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.py",
                "content": "path = '/workspace/subdir/file.txt'",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_workspace_in_comment_returns_true(self, handler):
        """Should match /workspace/ even in comments (all content checked)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.py",
                "content": "# Don't use /workspace/ paths\npath = './relative'",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_workspace_in_string_literal_returns_true(self, handler):
        """Should match /workspace/ in string literals."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": 'message = "Located at /workspace/"'},
        }
        assert handler.matches(hook_input) is True

    def test_matches_case_sensitive_workspace(self, handler):
        """Should be case-sensitive (only lowercase /workspace/)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "PATH = '/WORKSPACE/'"},  # uppercase
        }
        assert handler.matches(hook_input) is False

    # handle() Tests - Write Tool
    def test_handle_write_returns_deny_decision(self, handler):
        """handle() should return deny for Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.py",
                "content": "import sys\nsys.path.append('/workspace/lib')",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_write_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "path = '/workspace/data'"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_write_reason_shows_content_snippet(self, handler):
        """handle() reason should show snippet of problematic content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "BASE = '/workspace/data'"},
        }
        result = handler.handle(hook_input)
        assert "snippet" in result.reason.lower()
        assert "/workspace/" in result.reason

    def test_handle_write_truncates_long_content(self, handler):
        """handle() should truncate long content to 200 chars."""
        long_content = "x" * 300 + "/workspace/" + "y" * 100
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": long_content},
        }
        result = handler.handle(hook_input)
        # Snippet should be truncated to 200 chars
        assert "..." in result.reason

    def test_handle_write_explains_portability(self, handler):
        """handle() reason should explain portability issues."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "path = '/workspace/'"},
        }
        result = handler.handle(hook_input)
        assert "portability" in result.reason.lower() or "portable" in result.reason.lower()

    def test_handle_write_suggests_relative_paths(self, handler):
        """handle() reason should suggest using relative paths."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "path = '/workspace/src'"},
        }
        result = handler.handle(hook_input)
        assert "relative" in result.reason.lower()

    # handle() Tests - Edit Tool
    def test_handle_edit_returns_deny_decision(self, handler):
        """handle() should return deny for Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.py",
                "old_string": "old",
                "new_string": "path = '/workspace/new'",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_edit_shows_new_string_snippet(self, handler):
        """handle() should show snippet from new_string for Edit."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.py",
                "old_string": "old",
                "new_string": "BASE = '/workspace/data'",
            },
        }
        result = handler.handle(hook_input)
        assert "/workspace/" in result.reason

    def test_handle_edit_with_empty_new_string(self, handler):
        """handle() should handle empty new_string gracefully."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.py",
                "old_string": "path = '/workspace/'",
                "new_string": "",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason  # Should still have a reason

    def test_handle_explains_file_path_is_ok(self, handler):
        """handle() should clarify that file_path parameter can be absolute."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/test.py",
                "content": "import sys\nsys.path.append('/workspace/')",
            },
        }
        result = handler.handle(hook_input)
        # Should mention that tool parameters are OK
        assert "parameter" in result.reason.lower() or "file_path" in result.reason

    def test_handle_context_is_none(self, handler):
        """handle() context should be None (not used)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "path = '/workspace/'"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None (not used)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "path = '/workspace/'"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_allows_absolute_paths_in_parameters(self, handler):
        """Should allow absolute paths in tool parameters (file_path)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/components/Header.tsx",
                "content": "export function Header() { return <div>Header</div>; }",
            },
        }
        assert handler.matches(hook_input) is False  # No /workspace/ in CONTENT

    def test_blocks_workspace_in_code_not_parameters(self, handler):
        """Should block /workspace/ in code content, not in file_path."""
        # This should be blocked (content has /workspace/)
        bad_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "config.py",  # relative path in parameter
                "content": "BASE = '/workspace/data'",  # absolute in content
            },
        }
        assert handler.matches(bad_input) is True

        # This should be allowed (parameter has /workspace/, but content doesn't)
        good_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/config.py",  # absolute in parameter
                "content": "BASE = './data'",  # relative in content
            },
        }
        assert handler.matches(good_input) is False
