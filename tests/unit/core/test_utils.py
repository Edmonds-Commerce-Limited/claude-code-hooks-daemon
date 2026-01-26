"""Comprehensive tests for utility functions."""

from pathlib import Path

from claude_code_hooks_daemon.core.utils import (
    get_bash_command,
    get_file_content,
    get_file_path,
    get_workspace_root,
)

# get_bash_command() Tests


class TestGetBashCommand:
    """Test get_bash_command() utility."""

    def test_get_bash_command_returns_command_string(self):
        """Should return command string for Bash tool."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
        result = get_bash_command(hook_input)
        assert result == "ls -la"

    def test_get_bash_command_with_complex_command(self):
        """Should return complex command with pipes and quotes."""
        command = "find . -name '*.py' | grep -v __pycache__"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        result = get_bash_command(hook_input)
        assert result == command

    def test_get_bash_command_with_multiline_command(self):
        """Should return multiline command string."""
        command = "cd /tmp\nls -la\necho 'done'"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        result = get_bash_command(hook_input)
        assert result == command

    def test_get_bash_command_with_empty_command(self):
        """Should return empty string for empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        result = get_bash_command(hook_input)
        assert result == ""

    def test_get_bash_command_not_bash_tool_returns_none(self):
        """Should return None for non-Bash tools."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.py"}}
        result = get_bash_command(hook_input)
        assert result is None

    def test_get_bash_command_read_tool_returns_none(self):
        """Should return None for Read tool."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "test.py"}}
        result = get_bash_command(hook_input)
        assert result is None

    def test_get_bash_command_edit_tool_returns_none(self):
        """Should return None for Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "test.py", "old_string": "old", "new_string": "new"},
        }
        result = get_bash_command(hook_input)
        assert result is None

    def test_get_bash_command_missing_tool_input_returns_empty_string(self):
        """Should return empty string if tool_input missing."""
        hook_input = {"tool_name": "Bash"}
        result = get_bash_command(hook_input)
        assert result == ""

    def test_get_bash_command_missing_command_key_returns_empty_string(self):
        """Should return empty string if command key missing."""
        hook_input = {"tool_name": "Bash", "tool_input": {"description": "test"}}
        result = get_bash_command(hook_input)
        assert result == ""

    def test_get_bash_command_command_is_none_returns_none(self):
        """Should return None if command is None."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": None}}
        result = get_bash_command(hook_input)
        assert result is None

    def test_get_bash_command_empty_tool_input_returns_empty_string(self):
        """Should return empty string if tool_input is empty dict."""
        hook_input = {"tool_name": "Bash", "tool_input": {}}
        result = get_bash_command(hook_input)
        assert result == ""


# get_file_path() Tests


class TestGetFilePath:
    """Test get_file_path() utility."""

    def test_get_file_path_write_tool(self):
        """Should return file_path for Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test.py", "content": "print('hello')"},
        }
        result = get_file_path(hook_input)
        assert result == "/workspace/test.py"

    def test_get_file_path_edit_tool(self):
        """Should return file_path for Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/src/main.py",
                "old_string": "old",
                "new_string": "new",
            },
        }
        result = get_file_path(hook_input)
        assert result == "/workspace/src/main.py"

    def test_get_file_path_relative_path(self):
        """Should return relative file paths."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "src/test.py", "content": ""},
        }
        result = get_file_path(hook_input)
        assert result == "src/test.py"

    def test_get_file_path_with_spaces(self):
        """Should handle paths with spaces."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/my file.py", "content": ""},
        }
        result = get_file_path(hook_input)
        assert result == "/workspace/my file.py"

    def test_get_file_path_empty_string(self):
        """Should return empty string for empty file_path."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "", "content": "test"}}
        result = get_file_path(hook_input)
        assert result == ""

    def test_get_file_path_not_write_or_edit_returns_none(self):
        """Should return None for non-Write/Edit tools."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        result = get_file_path(hook_input)
        assert result is None

    def test_get_file_path_read_tool_returns_none(self):
        """Should return None for Read tool (not Write/Edit)."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "test.py"}}
        result = get_file_path(hook_input)
        assert result is None

    def test_get_file_path_grep_tool_returns_none(self):
        """Should return None for Grep tool."""
        hook_input = {"tool_name": "Grep", "tool_input": {"pattern": "test"}}
        result = get_file_path(hook_input)
        assert result is None

    def test_get_file_path_missing_tool_input_returns_empty_string(self):
        """Should return empty string if tool_input missing."""
        hook_input = {"tool_name": "Write"}
        result = get_file_path(hook_input)
        assert result == ""

    def test_get_file_path_missing_file_path_key_returns_empty_string(self):
        """Should return empty string if file_path key missing."""
        hook_input = {"tool_name": "Write", "tool_input": {"content": "test"}}
        result = get_file_path(hook_input)
        assert result == ""

    def test_get_file_path_file_path_is_none_returns_none(self):
        """Should return None if file_path is None."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": None, "content": "test"}}
        result = get_file_path(hook_input)
        assert result is None

    def test_get_file_path_empty_tool_input_returns_empty_string(self):
        """Should return empty string if tool_input is empty dict."""
        hook_input = {"tool_name": "Write", "tool_input": {}}
        result = get_file_path(hook_input)
        assert result == ""


# get_file_content() Tests


class TestGetFileContent:
    """Test get_file_content() utility."""

    def test_get_file_content_write_tool(self):
        """Should return content for Write tool."""
        content = "print('Hello, World!')"
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": content},
        }
        result = get_file_content(hook_input)
        assert result == content

    def test_get_file_content_edit_tool(self):
        """Should return content for Edit tool."""
        content = "new content here"
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.py",
                "old_string": "old",
                "new_string": "new",
                "content": content,
            },
        }
        result = get_file_content(hook_input)
        assert result == content

    def test_get_file_content_multiline(self):
        """Should return multiline content."""
        content = "line 1\nline 2\nline 3"
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": content},
        }
        result = get_file_content(hook_input)
        assert result == content

    def test_get_file_content_empty_string(self):
        """Should return empty string for empty content."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.py", "content": ""}}
        result = get_file_content(hook_input)
        assert result == ""

    def test_get_file_content_with_special_characters(self):
        """Should handle content with special characters."""
        content = "Special: \t\n\r 'quotes' \"double\""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": content},
        }
        result = get_file_content(hook_input)
        assert result == content

    def test_get_file_content_not_write_or_edit_returns_none(self):
        """Should return None for non-Write/Edit tools."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "echo 'test'"}}
        result = get_file_content(hook_input)
        assert result is None

    def test_get_file_content_read_tool_returns_none(self):
        """Should return None for Read tool."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "test.py"}}
        result = get_file_content(hook_input)
        assert result is None

    def test_get_file_content_missing_tool_input_returns_empty_string(self):
        """Should return empty string if tool_input missing."""
        hook_input = {"tool_name": "Write"}
        result = get_file_content(hook_input)
        assert result == ""

    def test_get_file_content_missing_content_key_returns_empty_string(self):
        """Should return empty string if content key missing."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.py"}}
        result = get_file_content(hook_input)
        assert result == ""

    def test_get_file_content_content_is_none_returns_none(self):
        """Should return None if content is None."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.py", "content": None}}
        result = get_file_content(hook_input)
        assert result is None

    def test_get_file_content_empty_tool_input_returns_empty_string(self):
        """Should return empty string if tool_input is empty dict."""
        hook_input = {"tool_name": "Write", "tool_input": {}}
        result = get_file_content(hook_input)
        assert result == ""

    def test_get_file_content_large_content(self):
        """Should handle large content strings."""
        content = "x" * 100000  # 100KB
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": content},
        }
        result = get_file_content(hook_input)
        assert result == content
        assert len(result) == 100000


# get_workspace_root() Tests


class TestGetWorkspaceRoot:
    """Test get_workspace_root() utility."""

    def test_get_workspace_root_finds_project_root(self):
        """Should find project root with .git and CLAUDE."""
        root = get_workspace_root()
        assert root.exists()
        assert (root / ".git").exists()
        assert (root / "CLAUDE").exists()

    def test_get_workspace_root_returns_path_object(self):
        """Should return Path object."""
        root = get_workspace_root()
        assert isinstance(root, Path)

    def test_get_workspace_root_is_absolute(self):
        """Should return absolute path."""
        root = get_workspace_root()
        assert root.is_absolute()

    def test_get_workspace_root_has_both_markers(self):
        """Should require both .git and CLAUDE directories."""
        root = get_workspace_root()
        git_dir = root / ".git"
        claude_dir = root / "CLAUDE"

        assert git_dir.exists()
        assert claude_dir.exists()

    def test_get_workspace_root_consistent_across_calls(self):
        """Should return same root across multiple calls."""
        root1 = get_workspace_root()
        root2 = get_workspace_root()
        assert root1 == root2

    def test_get_workspace_root_contains_expected_directories(self):
        """Should find workspace with expected project structure."""
        root = get_workspace_root()

        # Check for project directories
        expected_dirs = [".git", "CLAUDE", ".claude"]
        for dir_name in expected_dirs:
            dir_path = root / dir_name
            assert dir_path.exists(), f"Expected {dir_name} to exist at {root}"


# Edge Cases and Integration Tests


class TestUtilityEdgeCases:
    """Test edge cases for utility functions."""

    def test_get_bash_command_with_json_command(self):
        """Should handle command with JSON content."""
        command = 'echo \'{"key": "value"}\''
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        result = get_bash_command(hook_input)
        assert result == command

    def test_get_file_path_with_unicode_characters(self):
        """Should handle file paths with unicode characters."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test_文件.py", "content": ""},
        }
        result = get_file_path(hook_input)
        assert result == "/workspace/test_文件.py"

    def test_get_file_content_with_unicode(self):
        """Should handle content with unicode characters."""
        content = "print('Hello 世界! 🌍')"
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": content},
        }
        result = get_file_content(hook_input)
        assert result == content

    def test_all_utilities_handle_malformed_input(self):
        """All utilities should handle malformed input gracefully."""
        malformed: dict = {}

        # Should not raise exceptions
        assert get_bash_command(malformed) is None
        assert get_file_path(malformed) is None
        assert get_file_content(malformed) is None

    def test_utilities_with_missing_tool_name(self):
        """Should handle missing tool_name key."""
        hook_input = {"tool_input": {"command": "ls"}}

        # get() returns None if key missing, so these should handle gracefully
        result = get_bash_command(hook_input)
        # Tool name is None, not "Bash", so returns None
        assert result is None


class TestUtilityIntegration:
    """Integration tests for utilities working together."""

    def test_write_tool_utilities(self):
        """Test utilities work correctly for Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test.py", "content": "print('test')"},
        }

        # get_file_path should return path
        assert get_file_path(hook_input) == "/workspace/test.py"

        # get_file_content should return content
        assert get_file_content(hook_input) == "print('test')"

        # get_bash_command should return None (not Bash)
        assert get_bash_command(hook_input) is None

    def test_edit_tool_utilities(self):
        """Test utilities work correctly for Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "src/main.py",
                "old_string": "old",
                "new_string": "new",
                "content": "new content",
            },
        }

        # get_file_path should return path
        assert get_file_path(hook_input) == "src/main.py"

        # get_file_content should return content
        assert get_file_content(hook_input) == "new content"

        # get_bash_command should return None (not Bash)
        assert get_bash_command(hook_input) is None

    def test_bash_tool_utilities(self):
        """Test utilities work correctly for Bash tool."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}

        # get_bash_command should return command
        assert get_bash_command(hook_input) == "ls -la"

        # get_file_path should return None (not Write/Edit)
        assert get_file_path(hook_input) is None

        # get_file_content should return None (not Write/Edit)
        assert get_file_content(hook_input) is None

    def test_read_tool_utilities(self):
        """Test utilities return None for Read tool."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "test.py"}}

        # All should return None (Read not handled by any utility)
        assert get_bash_command(hook_input) is None
        assert get_file_path(hook_input) is None
        assert get_file_content(hook_input) is None
