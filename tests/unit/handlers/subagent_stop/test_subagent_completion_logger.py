"""Comprehensive tests for SubagentCompletionLoggerHandler."""

import json
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_completion_logger import (
    SubagentCompletionLoggerHandler,
)


class TestSubagentCompletionLoggerHandler:
    """Test suite for SubagentCompletionLoggerHandler."""

    @pytest.fixture(autouse=True)
    def mock_project_context(self, tmp_path: Path):
        """Patch ProjectContext.daemon_untracked_dir so handler can resolve log path."""
        with patch(
            "claude_code_hooks_daemon.handlers.subagent_stop.subagent_completion_logger.ProjectContext.daemon_untracked_dir",
            return_value=tmp_path,
        ):
            yield

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return SubagentCompletionLoggerHandler()

    @pytest.fixture
    def mock_datetime(self):
        """Mock datetime.now() to return fixed timestamp."""
        with patch(
            "claude_code_hooks_daemon.handlers.subagent_stop.subagent_completion_logger.datetime"
        ) as mock_dt:
            mock_dt.now.return_value.isoformat.return_value = "2024-01-20T10:30:00"
            yield mock_dt

    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'subagent-completion-logger'."""
        assert handler.name == "subagent-completion-logger"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 100."""
        assert handler.priority == 100

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal."""
        assert handler.terminal is False

    def test_matches_always_returns_true(self, handler):
        """Should match all subagent stop events."""
        hook_input = {"subagent_name": "test-agent"}
        assert handler.matches(hook_input) is True

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_creates_log_directory(self, mock_mkdir, mock_file, handler, mock_datetime):
        """Should create log directory if it doesn't exist."""
        hook_input = {"subagent_name": "test-agent"}
        handler.handle(hook_input)

        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_writes_json_log_entry(self, mock_mkdir, mock_file, handler, mock_datetime):
        """Should write JSON log entry to file."""
        hook_input = {
            "subagent_name": "typescript-specialist",
            "exit_code": 0,
            "result": "success",
        }

        handler.handle(hook_input)

        # Check file was opened in append mode
        assert mock_file.called
        # Check JSON write was attempted
        handle = mock_file()
        assert handle.write.called

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_returns_allow_decision(self, mock_mkdir, mock_file, handler):
        """Should return allow decision."""
        hook_input = {"subagent_name": "test"}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    @patch("pathlib.Path.open", side_effect=OSError("Write error"))
    @patch("pathlib.Path.mkdir")
    def test_handle_gracefully_handles_write_errors(self, mock_mkdir, mock_file, handler):
        """Should handle file write errors gracefully."""
        hook_input = {"subagent_name": "test"}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_returns_hook_result_instance(self, mock_mkdir, mock_file, handler):
        """Should return HookResult instance."""
        hook_input = {"subagent_name": "test"}
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)

    # Path resolution tests (regression: Issue 3 — relative path → Permission denied
    # when daemon CWD is /). Logs must be written under
    # ProjectContext.daemon_untracked_dir(), not a CWD-relative path.
    def test_handle_writes_under_project_untracked_dir(
        self, handler, mock_datetime, tmp_path: Path
    ):
        """Log file must resolve under ProjectContext.daemon_untracked_dir()."""
        hook_input = {"subagent_name": "test-agent", "result": "success"}
        handler.handle(hook_input)

        log_file = tmp_path / "logs" / "hooks" / "subagent_completions.jsonl"
        assert log_file.exists()
        entry = json.loads(log_file.read_text().strip())
        assert entry["subagent_name"] == "test-agent"
