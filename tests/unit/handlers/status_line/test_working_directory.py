"""Tests for WorkingDirectoryHandler."""

import pytest

from claude_code_hooks_daemon.handlers.status_line.working_directory import (
    WorkingDirectoryHandler,
)


class TestWorkingDirectoryHandler:
    """Test suite for WorkingDirectoryHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return WorkingDirectoryHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'status-working-directory'."""
        assert handler.name == "status-working-directory"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 25."""
        assert handler.priority == 25

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should not be terminal."""
        assert handler.terminal is False

    # matches() Tests
    def test_matches_always_returns_true(self, handler):
        """Should always match (returns True for all inputs)."""
        hook_input = {"event": "STATUS_LINE"}
        assert handler.matches(hook_input) is True

    def test_matches_returns_true_for_empty_input(self, handler):
        """Should match even with empty input."""
        hook_input = {}
        assert handler.matches(hook_input) is True

    # handle() Tests - Core Behavior
    def test_handle_returns_empty_when_current_dir_equals_project_dir(self, handler):
        """Should return empty context when current_dir equals project_dir."""
        hook_input = {
            "workspace": {
                "current_dir": "/workspace/project",
                "project_dir": "/workspace/project",
            }
        }
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_returns_relative_path_when_in_subdirectory(self, handler):
        """Should return relative path when current_dir is a subdirectory."""
        hook_input = {
            "workspace": {
                "current_dir": "/workspace/project/src/handlers",
                "project_dir": "/workspace/project",
            }
        }
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert result.context[0] == "| 📁 \033[38;5;208msrc/handlers\033[0m"

    def test_handle_returns_relative_path_with_single_level(self, handler):
        """Should return relative path for single level subdirectory."""
        hook_input = {
            "workspace": {
                "current_dir": "/workspace/project/tests",
                "project_dir": "/workspace/project",
            }
        }
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert result.context[0] == "| 📁 \033[38;5;208mtests\033[0m"

    def test_handle_returns_relative_path_with_deep_nesting(self, handler):
        """Should return relative path for deeply nested directories."""
        hook_input = {
            "workspace": {
                "current_dir": "/workspace/project/a/b/c/d/e",
                "project_dir": "/workspace/project",
            }
        }
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert result.context[0] == "| 📁 \033[38;5;208ma/b/c/d/e\033[0m"

    # handle() Tests - Missing Data
    def test_handle_returns_empty_when_no_workspace_data(self, handler):
        """Should return empty context when workspace data missing."""
        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_returns_empty_when_current_dir_missing(self, handler):
        """Should return empty context when current_dir is missing."""
        hook_input = {"workspace": {"project_dir": "/workspace/project"}}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_returns_empty_when_project_dir_missing(self, handler):
        """Should return empty context when project_dir is missing."""
        hook_input = {"workspace": {"current_dir": "/workspace/project/src"}}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_returns_empty_when_both_dirs_missing(self, handler):
        """Should return empty context when both directories are missing."""
        hook_input = {"workspace": {}}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    # handle() Tests - Edge Cases
    def test_handle_with_trailing_slashes(self, handler):
        """Should handle paths with trailing slashes correctly."""
        hook_input = {
            "workspace": {
                "current_dir": "/workspace/project/src/",
                "project_dir": "/workspace/project/",
            }
        }
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert result.context[0] == "| 📁 \033[38;5;208msrc\033[0m"

    def test_handle_with_windows_style_paths(self, handler):
        """Should handle Windows-style paths correctly on Windows.

        On Linux, pathlib treats backslashes as part of the filename,
        so we expect empty context (paths don't match the relative_to pattern).
        This test mainly ensures no crashes occur with Windows-style input.
        """
        hook_input = {
            "workspace": {
                "current_dir": "C:\\Users\\user\\project\\src",
                "project_dir": "C:\\Users\\user\\project",
            }
        }
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        # On Linux, this will return empty context (no crash)
        # On Windows, this would return relative path
        assert isinstance(result.context, list)

    def test_handle_guidance_is_none(self, handler):
        """Handler should not set guidance."""
        hook_input = {
            "workspace": {
                "current_dir": "/workspace/project/src",
                "project_dir": "/workspace/project",
            }
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_reason_is_none(self, handler):
        """Handler should not set reason."""
        hook_input = {
            "workspace": {
                "current_dir": "/workspace/project/src",
                "project_dir": "/workspace/project",
            }
        }
        result = handler.handle(hook_input)
        assert result.reason is None

    def test_handle_returns_context_list(self, handler):
        """Handler should return context as a list."""
        hook_input = {
            "workspace": {
                "current_dir": "/workspace/project/src",
                "project_dir": "/workspace/project",
            }
        }
        result = handler.handle(hook_input)
        assert isinstance(result.context, list)
