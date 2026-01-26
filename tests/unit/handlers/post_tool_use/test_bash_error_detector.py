"""Comprehensive tests for BashErrorDetectorHandler."""

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.post_tool_use.bash_error_detector import (
    BashErrorDetectorHandler,
)


class TestBashErrorDetectorHandler:
    """Test suite for BashErrorDetectorHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return BashErrorDetectorHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'bash-error-detector'."""
        assert handler.name == "bash-error-detector"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 50."""
        assert handler.priority == 50

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal (provides feedback)."""
        assert handler.terminal is False

    # matches() - Positive Cases
    def test_matches_bash_tool(self, handler):
        """Should match Bash tool."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
            "tool_output": {"exit_code": 0, "stdout": "Build successful"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_with_error_exit_code(self, handler):
        """Should match Bash tool with error exit code."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
            "tool_output": {"exit_code": 1, "stdout": "Tests failed"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_without_output(self, handler):
        """Should match Bash tool even without output."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases
    def test_matches_write_tool_returns_false(self, handler):
        """Should not match Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.txt", "content": "test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_tool_returns_false(self, handler):
        """Should not match Read tool."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "test.txt"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_tool_returns_false(self, handler):
        """Should not match Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "test.txt", "old_string": "a", "new_string": "b"},
        }
        assert handler.matches(hook_input) is False

    # handle() - Success Cases
    def test_handle_success_returns_allow(self, handler):
        """Should return allow for successful commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
            "tool_output": {"exit_code": 0, "stdout": "Build successful"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_success_has_no_context(self, handler):
        """Should not provide context for successful commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_output": {"exit_code": 0, "stdout": "file.txt"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    # handle() - Error Cases
    def test_handle_error_exit_code_provides_context(self, handler):
        """Should provide context for non-zero exit codes."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
            "tool_output": {"exit_code": 1, "stderr": "Test suite failed"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context)
        assert "1" in context_text  # Check for exit code number

    def test_handle_error_in_stdout_provides_context(self, handler):
        """Should detect 'error' keyword in stdout."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run lint"},
            "tool_output": {"exit_code": 0, "stdout": "Error: Linting failed on 3 files"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context).lower()
        assert "error" in context_text

    def test_handle_error_in_stderr_provides_context(self, handler):
        """Should detect 'error' keyword in stderr."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "node script.js"},
            "tool_output": {"exit_code": 0, "stderr": "Error: Cannot find module"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context).lower()
        assert "error" in context_text

    def test_handle_warning_in_output_provides_context(self, handler):
        """Should detect 'warning' keyword in output."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install"},
            "tool_output": {"exit_code": 0, "stdout": "Warning: 2 deprecated packages"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context).lower()
        assert "warning" in context_text

    def test_handle_failed_keyword_provides_context(self, handler):
        """Should detect 'failed' keyword in output."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "tool_output": {"exit_code": 0, "stdout": "5 tests failed"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context).lower()
        assert "failed" in context_text

    def test_handle_case_insensitive_error_detection(self, handler):
        """Should detect errors case-insensitively."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "build.sh"},
            "tool_output": {"exit_code": 0, "stdout": "ERROR: Build failed"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.context  # Non-empty list

    def test_handle_multiple_issues_in_context(self, handler):
        """Should report multiple issues in context."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run ci"},
            "tool_output": {
                "exit_code": 1,
                "stdout": "Error: Linting failed",
                "stderr": "Warning: Tests have warnings",
            },
        }
        result = handler.handle(hook_input)
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context).lower()
        assert "error" in context_text or "'error'" in context_text
        assert "warning" in context_text or "'warning'" in context_text
        assert "1" in "\n".join(result.context)  # Exit code present

    def test_handle_includes_command_in_context(self, handler):
        """Context should include the command that was run."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
            "tool_output": {"exit_code": 1, "stderr": "Build failed"},
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        assert "npm run build" in context_text

    # Edge Cases
    def test_handle_missing_tool_output(self, handler):
        """Should handle missing tool_output gracefully."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_empty_tool_output(self, handler):
        """Should handle empty tool_output gracefully."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
            "tool_output": {},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_missing_stdout_stderr(self, handler):
        """Should handle missing stdout/stderr gracefully."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
            "tool_output": {"exit_code": 0},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_none_stdout_stderr(self, handler):
        """Should handle None stdout/stderr gracefully."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
            "tool_output": {"exit_code": 0, "stdout": None, "stderr": None},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_no_reason_field(self, handler):
        """handle() should not provide reason (non-blocking)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
            "tool_output": {"exit_code": 1, "stderr": "Failed"},
        }
        result = handler.handle(hook_input)
        assert result.reason is None

    def test_handle_no_guidance_field(self, handler):
        """handle() should not provide guidance."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
            "tool_output": {"exit_code": 1, "stderr": "Failed"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_returns_hook_result_instance(self, handler):
        """handle() should return HookResult instance."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
            "tool_output": {"exit_code": 0},
        }
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)
