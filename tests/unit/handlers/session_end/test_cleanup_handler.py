"""Comprehensive tests for CleanupHandler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.session_end.cleanup_handler import CleanupHandler


class TestCleanupHandler:
    """Test suite for CleanupHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return CleanupHandler()

    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'session-cleanup'."""
        assert handler.name == "session-cleanup"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 100."""
        assert handler.priority == 100

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal."""
        assert handler.terminal is False

    def test_matches_always_returns_true(self, handler):
        """Should match all session end events."""
        hook_input = {"reason": "user_exit"}
        assert handler.matches(hook_input) is True

    @patch("claude_code_hooks_daemon.handlers.session_end.cleanup_handler.Path")
    def test_handle_cleans_temp_directory(self, mock_path, handler):
        """Should attempt to clean temp directory."""
        mock_temp_dir = MagicMock()
        mock_path.return_value = mock_temp_dir
        mock_temp_dir.exists.return_value = True
        mock_temp_dir.is_dir.return_value = True

        # Mock temp files
        mock_file1 = MagicMock(spec=Path)
        mock_file1.is_file.return_value = True
        mock_file2 = MagicMock(spec=Path)
        mock_file2.is_file.return_value = True

        mock_temp_dir.glob.return_value = [mock_file1, mock_file2]

        hook_input = {}
        handler.handle(hook_input)

        # Should attempt to delete files
        mock_file1.unlink.assert_called_once()
        mock_file2.unlink.assert_called_once()

    @patch("claude_code_hooks_daemon.handlers.session_end.cleanup_handler.Path")
    def test_handle_temp_dir_not_exists(self, mock_path, handler):
        """Should handle gracefully when temp dir doesn't exist."""
        mock_temp_dir = MagicMock()
        mock_path.return_value = mock_temp_dir
        mock_temp_dir.exists.return_value = False

        hook_input = {}
        result = handler.handle(hook_input)

        assert result.decision == "allow"
        # Should not call glob if dir doesn't exist
        mock_temp_dir.glob.assert_not_called()

    @patch("claude_code_hooks_daemon.handlers.session_end.cleanup_handler.Path")
    def test_handle_returns_allow_decision(self, mock_path, handler):
        """Should return allow decision."""
        mock_temp_dir = MagicMock()
        mock_path.return_value = mock_temp_dir
        mock_temp_dir.exists.return_value = False

        hook_input = {}
        result = handler.handle(hook_input)

        assert result.decision == "allow"

    @patch("claude_code_hooks_daemon.handlers.session_end.cleanup_handler.Path")
    def test_handle_gracefully_handles_deletion_errors(self, mock_path, handler):
        """Should handle file deletion errors gracefully."""
        mock_temp_dir = MagicMock()
        mock_path.return_value = mock_temp_dir
        mock_temp_dir.exists.return_value = True
        mock_temp_dir.is_dir.return_value = True

        mock_file = MagicMock(spec=Path)
        mock_file.is_file.return_value = True
        mock_file.unlink.side_effect = OSError("Permission denied")

        mock_temp_dir.glob.return_value = [mock_file]

        hook_input = {}
        result = handler.handle(hook_input)

        # Should not raise exception
        assert result.decision == "allow"

    @patch("claude_code_hooks_daemon.handlers.session_end.cleanup_handler.Path")
    def test_handle_skips_non_files(self, mock_path, handler):
        """Should skip directories and only delete files."""
        mock_temp_dir = MagicMock()
        mock_path.return_value = mock_temp_dir
        mock_temp_dir.exists.return_value = True
        mock_temp_dir.is_dir.return_value = True

        mock_file = MagicMock(spec=Path)
        mock_file.is_file.return_value = True

        mock_dir = MagicMock(spec=Path)
        mock_dir.is_file.return_value = False

        mock_temp_dir.glob.return_value = [mock_file, mock_dir]

        hook_input = {}
        handler.handle(hook_input)

        # Should delete file but not directory
        mock_file.unlink.assert_called_once()
        mock_dir.unlink.assert_not_called()

    @patch("claude_code_hooks_daemon.handlers.session_end.cleanup_handler.Path")
    def test_handle_returns_hook_result_instance(self, mock_path, handler):
        """Should return HookResult instance."""
        mock_temp_dir = MagicMock()
        mock_path.return_value = mock_temp_dir
        mock_temp_dir.exists.return_value = False

        hook_input = {}
        result = handler.handle(hook_input)

        assert isinstance(result, HookResult)

    @patch("claude_code_hooks_daemon.handlers.session_end.cleanup_handler.Path")
    def test_handle_has_no_context(self, mock_path, handler):
        """Should not provide context."""
        mock_temp_dir = MagicMock()
        mock_path.return_value = mock_temp_dir
        mock_temp_dir.exists.return_value = False

        hook_input = {}
        result = handler.handle(hook_input)

        assert result.context == []

    @patch(
        "claude_code_hooks_daemon.handlers.session_end.cleanup_handler.Path",
        side_effect=OSError("Path error"),
    )
    def test_handle_gracefully_handles_path_errors(self, mock_path, handler):
        """Should handle Path() construction errors gracefully."""
        hook_input = {}
        result = handler.handle(hook_input)

        # Should not raise exception
        assert result.decision == "allow"
