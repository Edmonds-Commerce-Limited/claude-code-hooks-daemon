"""Comprehensive tests for TranscriptArchiverHandler."""

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver import (
    TranscriptArchiverHandler,
)


class TestTranscriptArchiverHandler:
    """Test suite for TranscriptArchiverHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return TranscriptArchiverHandler()

    @pytest.fixture
    def mock_datetime(self):
        """Mock datetime.now() to return fixed timestamp."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver.datetime"
        ) as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "20240120_103000"
            mock_now.isoformat.return_value = "2024-01-20T10:30:00"
            mock_dt.now.return_value = mock_now
            yield mock_dt

    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'transcript-archiver'."""
        assert handler.name == "transcript-archiver"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_is_non_terminal(self, handler):
        """Handler should be non-terminal."""
        assert handler.terminal is False

    def test_matches_always_returns_true(self, handler):
        """Should match all pre-compact events."""
        hook_input = {"transcript": "Test conversation"}
        assert handler.matches(hook_input) is True

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_creates_archive_directory(self, mock_mkdir, mock_file, handler, mock_datetime):
        """Should create archive directory if it doesn't exist."""
        hook_input = {"transcript": [{"role": "user", "content": "test"}]}
        handler.handle(hook_input)

        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_saves_transcript_with_timestamp(
        self, mock_mkdir, mock_file, handler, mock_datetime
    ):
        """Should save transcript with timestamp in filename."""
        hook_input = {"transcript": [{"role": "user", "content": "Hello"}]}

        handler.handle(hook_input)

        # Check file was opened for writing
        assert mock_file.called

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_saves_transcript_as_json(self, mock_mkdir, mock_file, handler, mock_datetime):
        """Should save transcript as formatted JSON."""
        hook_input = {
            "transcript": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
            ]
        }

        handler.handle(hook_input)

        # Check JSON was written with indent
        handle = mock_file()
        written_data = "".join(call.args[0] for call in handle.write.call_args_list)
        parsed = json.loads(written_data)

        assert len(parsed["transcript"]) == 2
        assert parsed["transcript"][0]["role"] == "user"

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_includes_metadata(self, mock_mkdir, mock_file, handler, mock_datetime):
        """Should include metadata in saved file."""
        hook_input = {"transcript": [{"role": "user", "content": "test"}]}

        handler.handle(hook_input)

        handle = mock_file()
        written_data = "".join(call.args[0] for call in handle.write.call_args_list)
        parsed = json.loads(written_data)

        assert "archived_at" in parsed
        assert "transcript" in parsed

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_returns_allow_decision(self, mock_mkdir, mock_file, handler):
        """Should return allow decision."""
        hook_input = {"transcript": []}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    @patch("pathlib.Path.open", side_effect=OSError("Write error"))
    @patch("pathlib.Path.mkdir")
    def test_handle_gracefully_handles_write_errors(self, mock_mkdir, mock_file, handler):
        """Should handle file write errors gracefully."""
        hook_input = {"transcript": []}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    @patch("pathlib.Path.open", new_callable=mock_open)
    @patch("pathlib.Path.mkdir")
    def test_handle_returns_hook_result_instance(self, mock_mkdir, mock_file, handler):
        """Should return HookResult instance."""
        hook_input = {"transcript": []}
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)
