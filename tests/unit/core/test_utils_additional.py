"""Additional tests for core utilities for branch coverage."""

from typing import Any

from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_content, get_file_path


class TestGetBashCommand:
    """Tests for get_bash_command function."""

    def test_returns_none_for_non_bash_tool(self) -> None:
        """Returns None when tool is not Bash."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "print('hello')"},
        }
        result = get_bash_command(hook_input)
        assert result is None


class TestGetFilePath:
    """Tests for get_file_path function."""

    def test_returns_none_for_bash_tool(self) -> None:
        """Returns None when tool is Bash."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
        }
        result = get_file_path(hook_input)
        assert result is None


class TestGetFileContent:
    """Tests for get_file_content function."""

    def test_returns_none_for_bash_tool(self) -> None:
        """Returns None when tool is Bash."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
        }
        result = get_file_content(hook_input)
        assert result is None

    def test_returns_content_for_write_tool(self) -> None:
        """Returns content for Write tool."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "# test"},
        }
        result = get_file_content(hook_input)
        assert result == "# test"
