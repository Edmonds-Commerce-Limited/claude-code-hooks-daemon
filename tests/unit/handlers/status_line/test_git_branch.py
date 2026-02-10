"""Tests for GitBranchHandler."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import GitBranchHandler


class TestGitBranchHandler:
    """Tests for GitBranchHandler."""

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        """Create handler instance."""
        return GitBranchHandler()

    def test_handler_properties(self, handler: GitBranchHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-git-branch"
        assert handler.priority == 20
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "git" in handler.tags

    def test_matches_always_returns_true(self, handler: GitBranchHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"workspace": {"current_dir": "/tmp"}}) is True

    def test_handle_with_git_branch(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test formatting with valid git branch."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        mock_result_branch = MagicMock()
        mock_result_branch.stdout = b"main\n"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [mock_result_toplevel, mock_result_branch]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "| ⎇ main" in result.context[0]

    def test_handle_not_a_git_repo(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test returns empty context when not in git repo."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_no_workspace_data(self, handler: GitBranchHandler) -> None:
        """Test returns empty context when workspace data missing."""
        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_invalid_path(self, handler: GitBranchHandler) -> None:
        """Test returns empty context when path doesn't exist."""
        hook_input = {"workspace": {"current_dir": "/nonexistent/path"}}

        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_git_error_silent_fail(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test silent failure on git errors."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        with patch("subprocess.run", side_effect=Exception("Git error")):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_empty_branch_name(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test returns empty context when branch name is empty."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        mock_result_branch = MagicMock()
        mock_result_branch.stdout = b"\n"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [mock_result_toplevel, mock_result_branch]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_uses_project_dir_fallback(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test uses project_dir when current_dir not available."""
        hook_input = {"workspace": {"project_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        mock_result_branch = MagicMock()
        mock_result_branch.stdout = b"develop\n"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [mock_result_toplevel, mock_result_branch]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "| ⎇ develop" in result.context[0]
