"""Tests for shared stop hook helper utilities.

TDD RED phase: These tests define the expected API for stop_hook_helpers.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.stop_hook_helpers import (
    get_transcript_reader,
    is_stop_hook_active,
)


class TestIsStopHookActive:
    """Test is_stop_hook_active() shared utility."""

    def test_false_when_not_set(self) -> None:
        """Returns False when neither field is present."""
        assert is_stop_hook_active({}) is False

    def test_true_with_snake_case(self) -> None:
        """Returns True when stop_hook_active is True."""
        assert is_stop_hook_active({"stop_hook_active": True}) is True

    def test_true_with_camel_case(self) -> None:
        """Returns True when stopHookActive is True."""
        assert is_stop_hook_active({"stopHookActive": True}) is True

    def test_false_with_snake_case_false(self) -> None:
        """Returns False when stop_hook_active is explicitly False."""
        assert is_stop_hook_active({"stop_hook_active": False}) is False

    def test_false_with_camel_case_false(self) -> None:
        """Returns False when stopHookActive is explicitly False."""
        assert is_stop_hook_active({"stopHookActive": False}) is False

    def test_true_when_either_is_true(self) -> None:
        """Returns True if either variant is True."""
        assert is_stop_hook_active({"stop_hook_active": False, "stopHookActive": True}) is True


class TestGetTranscriptReader:
    """Test get_transcript_reader() shared utility."""

    def test_returns_reader_for_valid_transcript(self, tmp_path: Path) -> None:
        """Returns a loaded TranscriptReader for valid transcript path."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Hello"}],
                    },
                }
            )
            + "\n"
        )
        hook_input: dict[str, Any] = {"transcript_path": str(transcript)}
        reader = get_transcript_reader(hook_input)
        assert reader is not None
        assert reader.is_loaded() is True

    def test_returns_none_when_no_transcript_path(self) -> None:
        """Returns None when transcript_path is missing from hook_input."""
        assert get_transcript_reader({}) is None

    def test_returns_none_when_transcript_path_empty(self) -> None:
        """Returns None when transcript_path is empty string."""
        assert get_transcript_reader({"transcript_path": ""}) is None

    def test_returns_none_when_file_not_found(self) -> None:
        """Returns None when transcript file does not exist."""
        assert get_transcript_reader({"transcript_path": "/nonexistent/file.jsonl"}) is None

    def test_reader_has_messages(self, tmp_path: Path) -> None:
        """Returned reader should have parsed messages."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Test message"}],
                    },
                }
            )
            + "\n"
        )
        hook_input: dict[str, Any] = {"transcript_path": str(transcript)}
        reader = get_transcript_reader(hook_input)
        assert reader is not None
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "Test message"
