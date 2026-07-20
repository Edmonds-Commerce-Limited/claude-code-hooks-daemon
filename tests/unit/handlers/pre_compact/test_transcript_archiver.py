"""Comprehensive tests for TranscriptArchiverHandler."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver import (
    TranscriptArchiverHandler,
)

_FIXED_TIMESTAMP = "20240120_103000"
_FIXED_ISOFORMAT = "2024-01-20T10:30:00"


class TestTranscriptArchiverHandler:
    """Test suite for TranscriptArchiverHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return TranscriptArchiverHandler()

    @pytest.fixture
    def archive_dir(self, tmp_path):
        """Patch ProjectContext.daemon_untracked_dir to a temp directory."""
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "ProjectContext.daemon_untracked_dir",
            return_value=untracked,
        ):
            yield untracked / "transcripts"

    @pytest.fixture
    def transcript_file(self, tmp_path):
        """Create a real JSONL transcript fixture file on disk."""
        path = tmp_path / "session-transcript.jsonl"
        path.write_text(
            '{"role": "user", "content": "Hello"}\n'
            '{"role": "assistant", "content": "Hi there"}\n'
        )
        return path

    @pytest.fixture
    def mock_datetime(self):
        """Mock datetime.now() to return fixed timestamp."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver.datetime"
        ) as mock_dt:
            mock_now = mock_dt.now.return_value
            mock_now.strftime.return_value = _FIXED_TIMESTAMP
            mock_now.isoformat.return_value = _FIXED_ISOFORMAT
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
        hook_input = {HookInputField.TRANSCRIPT_PATH: "/tmp/whatever.jsonl"}
        assert handler.matches(hook_input) is True

    def test_handle_prunes_old_archives_beyond_max(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Plan 00181: the archive dir is bounded to max_archives (newest kept)."""
        handler._max_archives = 3
        handler._max_archive_age_days = 3650  # effectively disable age pruning here
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Five pre-existing archives with RECENT, ordered mtimes (so only the
        # count criterion binds — ancient mtimes would trip age pruning instead).
        base = time.time() - 100.0
        for i in range(5):
            old = archive_dir / f"transcript_old{i}.json"
            old.write_text("{}")
            os.utime(old, (base + i, base + i))

        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        handler.handle(hook_input)

        remaining = {p.name for p in archive_dir.glob("transcript_*.json")}
        # The just-written file (real 'now', newest) always survives; only the
        # two most-recent pre-existing archives remain alongside it.
        assert len(remaining) == 3
        assert f"transcript_{_FIXED_TIMESTAMP}.json" in remaining
        assert "transcript_old4.json" in remaining
        assert "transcript_old0.json" not in remaining

    def test_handle_prunes_archives_older_than_age_window(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Age-based pruning: an ancient archive is dropped even under the count."""
        handler._max_archives = 100  # count does not bind here
        handler._max_archive_age_days = 1
        archive_dir.mkdir(parents=True, exist_ok=True)
        ancient = archive_dir / "transcript_ancient.json"
        ancient.write_text("{}")
        os.utime(ancient, (1000.0, 1000.0))  # epoch 1970 -> far older than 1 day

        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        handler.handle(hook_input)

        assert not ancient.exists()
        assert (archive_dir / f"transcript_{_FIXED_TIMESTAMP}.json").exists()

    def test_handle_creates_archive_directory(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Should create archive directory if it doesn't exist."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        handler.handle(hook_input)

        assert archive_dir.is_dir()

    def test_handle_saves_transcript_with_timestamp(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Should save transcript with timestamp in filename."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}

        handler.handle(hook_input)

        expected = archive_dir / f"transcript_{_FIXED_TIMESTAMP}.json"
        assert expected.is_file()

    def test_handle_embeds_transcript_file_contents(
        self, handler, archive_dir, transcript_file, mock_datetime
    ):
        """Should read the transcript_path file and embed its contents.

        Regression: previously the handler read an inline ``transcript`` key
        which Claude Code never sends, producing empty archives in production.
        """
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}

        handler.handle(hook_input)

        archive_file = archive_dir / f"transcript_{_FIXED_TIMESTAMP}.json"
        parsed = json.loads(archive_file.read_text())

        assert parsed["transcript"] == transcript_file.read_text()
        assert parsed["transcript"] != ""
        assert "Hello" in parsed["transcript"]
        assert "Hi there" in parsed["transcript"]

    def test_handle_records_source_path(self, handler, archive_dir, transcript_file, mock_datetime):
        """Should record the originating transcript path in the archive."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}

        handler.handle(hook_input)

        archive_file = archive_dir / f"transcript_{_FIXED_TIMESTAMP}.json"
        parsed = json.loads(archive_file.read_text())

        assert parsed["transcript_path"] == str(transcript_file)

    def test_handle_includes_metadata(self, handler, archive_dir, transcript_file, mock_datetime):
        """Should include metadata in saved file."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}

        handler.handle(hook_input)

        archive_file = archive_dir / f"transcript_{_FIXED_TIMESTAMP}.json"
        parsed = json.loads(archive_file.read_text())

        assert "archived_at" in parsed
        assert "transcript" in parsed

    def test_handle_empty_when_no_transcript_path(self, handler, archive_dir, mock_datetime):
        """Should write an empty transcript when no path is provided."""
        hook_input: dict = {}

        handler.handle(hook_input)

        archive_file = archive_dir / f"transcript_{_FIXED_TIMESTAMP}.json"
        parsed = json.loads(archive_file.read_text())

        assert parsed["transcript"] == ""

    def test_handle_empty_when_transcript_path_missing_file(
        self, handler, archive_dir, tmp_path, mock_datetime
    ):
        """Should write an empty transcript when the file does not exist."""
        missing = tmp_path / "does-not-exist.jsonl"
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(missing)}

        handler.handle(hook_input)

        archive_file = archive_dir / f"transcript_{_FIXED_TIMESTAMP}.json"
        parsed = json.loads(archive_file.read_text())

        assert parsed["transcript"] == ""

    def test_handle_returns_allow_decision(self, handler, archive_dir, transcript_file):
        """Should return allow decision."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_gracefully_handles_write_errors(self, handler, archive_dir, transcript_file):
        """Should handle file write errors gracefully."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        with patch.object(Path, "open", side_effect=OSError("Write error")):
            result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_gracefully_handles_missing_project_context(self, handler):
        """Should return allow when ProjectContext is not initialised."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: "/tmp/x.jsonl"}
        with patch(
            "claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver."
            "ProjectContext.daemon_untracked_dir",
            side_effect=RuntimeError("no project context"),
        ):
            result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_returns_hook_result_instance(self, handler, archive_dir, transcript_file):
        """Should return HookResult instance."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript_file)}
        result = handler.handle(hook_input)
        assert isinstance(result, HookResult)
