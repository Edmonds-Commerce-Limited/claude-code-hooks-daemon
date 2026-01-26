"""Comprehensive tests for GitContextInjectorHandler."""

from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.user_prompt_submit.git_context_injector import (
    GitContextInjectorHandler,
)


class TestGitContextInjectorHandler:
    """Test suite for GitContextInjectorHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return GitContextInjectorHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'git-context-injector'."""
        assert handler.name == "git-context-injector"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 20."""
        assert handler.priority == 20

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal (provides context)."""
        assert handler.terminal is False

    # matches() Tests
    def test_matches_always_returns_true(self, handler):
        """Should match all user prompt submissions."""
        hook_input = {"prompt": "Implement feature X"}
        assert handler.matches(hook_input) is True

    def test_matches_empty_input_returns_true(self, handler):
        """Should match even empty input."""
        hook_input = {}
        assert handler.matches(hook_input) is True

    # handle() - Git Available Tests
    @patch("subprocess.run")
    def test_handle_adds_git_status_context(self, mock_run, handler):
        """Should add git status to context when git is available."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="On branch main\nnothing to commit",
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context  # Non-empty list
        context_text = "\n".join(result.context).lower()
        assert "git" in context_text or "repository" in context_text
        assert "On branch main" in "\n".join(result.context)

    @patch("subprocess.run")
    def test_handle_adds_branch_name(self, mock_run, handler):
        """Should include current branch in context."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="On branch feature/new-handler\nChanges not staged",
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        context_text = "\n".join(result.context)
        assert "feature/new-handler" in context_text

    @patch("subprocess.run")
    def test_handle_adds_uncommitted_changes_info(self, mock_run, handler):
        """Should include uncommitted changes info."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Changes not staged for commit:\n  modified: file.py",
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        context_text = "\n".join(result.context).lower()
        assert "modified" in context_text

    # handle() - Git Not Available Tests
    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_handle_git_not_installed(self, mock_run, handler):
        """Should return silent allow when git is not installed."""
        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context == []

    @patch("subprocess.run")
    def test_handle_not_a_git_repository(self, mock_run, handler):
        """Should return silent allow when not in a git repository."""
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="fatal: not a git repository",
        )

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context == []

    @patch("subprocess.run")
    def test_handle_git_command_timeout(self, mock_run, handler):
        """Should handle git command timeout gracefully."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git status", timeout=5)

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert result.context == []

    # Result Properties Tests
    @patch("subprocess.run")
    def test_handle_has_no_reason(self, mock_run, handler):
        """Should not provide reason."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Clean repo")

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.reason is None

    @patch("subprocess.run")
    def test_handle_has_no_guidance(self, mock_run, handler):
        """Should not provide guidance."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Clean repo")

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert result.guidance is None

    @patch("subprocess.run")
    def test_handle_returns_hook_result_instance(self, mock_run, handler):
        """Should return HookResult instance."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Clean repo")

        hook_input = {"prompt": "Test"}
        result = handler.handle(hook_input)

        assert isinstance(result, HookResult)

    # Integration Tests
    @patch("subprocess.run")
    def test_handle_calls_git_status_with_correct_args(self, mock_run, handler):
        """Should call git status with correct arguments."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Status")

        hook_input = {"prompt": "Test"}
        handler.handle(hook_input)

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "git" in call_args[0][0]
        assert "status" in call_args[0][0]
        assert call_args[1].get("capture_output") is True
        assert call_args[1].get("text") is True
