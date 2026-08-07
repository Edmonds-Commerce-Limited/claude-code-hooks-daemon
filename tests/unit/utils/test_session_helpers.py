"""Tests for shared session-classification helpers."""

from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.utils.session_helpers import (
    RESUME_SESSION_MIN_TRANSCRIPT_BYTES,
    is_resume_session,
)


class TestIsResumeSession:
    """Tests for is_resume_session()."""

    def test_returns_true_for_large_transcript(self, tmp_path: Path) -> None:
        """A transcript file larger than the threshold IS a resume."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)
        assert is_resume_session({"transcript_path": str(transcript)}) is True

    def test_returns_false_for_small_transcript(self, tmp_path: Path) -> None:
        """A transcript file at/under the threshold is NOT a resume."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 50)
        assert is_resume_session({"transcript_path": str(transcript)}) is False

    def test_returns_false_for_empty_transcript(self, tmp_path: Path) -> None:
        """An empty transcript file is NOT a resume."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        assert is_resume_session({"transcript_path": str(transcript)}) is False

    def test_returns_false_for_exactly_threshold_bytes(self, tmp_path: Path) -> None:
        """A transcript exactly at the threshold is NOT a resume (strict >)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * RESUME_SESSION_MIN_TRANSCRIPT_BYTES)
        assert is_resume_session({"transcript_path": str(transcript)}) is False

    def test_returns_false_for_nonexistent_transcript(self, tmp_path: Path) -> None:
        """A missing transcript file is NOT a resume."""
        missing = tmp_path / "missing.jsonl"
        assert is_resume_session({"transcript_path": str(missing)}) is False

    def test_returns_false_for_missing_transcript_path_key(self) -> None:
        """No transcript_path field is NOT a resume."""
        assert is_resume_session({}) is False

    def test_returns_false_for_empty_transcript_path_value(self) -> None:
        """An empty-string transcript_path is NOT a resume."""
        assert is_resume_session({"transcript_path": ""}) is False

    def test_returns_false_on_oserror_from_stat(self, tmp_path: Path) -> None:
        """OSError from path.stat() is treated as NOT a resume."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)
        with patch("pathlib.Path.stat", side_effect=OSError("Permission denied")):
            assert is_resume_session({"transcript_path": str(transcript)}) is False

    def test_returns_false_on_valueerror_from_path_construction(self) -> None:
        """ValueError from Path() construction is treated as NOT a resume."""
        assert is_resume_session({"transcript_path": "\x00invalid"}) is False
