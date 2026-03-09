"""Tests for nitpick pseudo-event setup function.

TDD RED phase: Tests define how the nitpick setup function reads transcripts
incrementally and enriches hook_input with assistant messages.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.pseudo_events.nitpick import (
    NitpickSetup,
)


def _write_transcript(path: Path, entries: list[dict[str, Any]]) -> None:
    """Write JSONL entries to a transcript file."""
    with path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _assistant_entry(content: str, uuid: str = "uuid-1") -> dict[str, Any]:
    """Create an assistant transcript entry."""
    return {
        "type": "assistant",
        "uuid": uuid,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": content}],
        },
    }


def _human_entry(content: str, uuid: str = "uuid-h") -> dict[str, Any]:
    """Create a human transcript entry."""
    return {
        "type": "human",
        "uuid": uuid,
        "message": {
            "role": "human",
            "content": content,
        },
    }


class TestNitpickSetupBasic:
    """Test basic setup function behavior."""

    def test_returns_enriched_input_with_assistant_messages(self) -> None:
        """Setup returns hook_input enriched with assistant_messages."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)

        entries = [_assistant_entry("I completed the task", "uuid-1")]
        _write_transcript(path, entries)

        setup = NitpickSetup()
        hook_input: dict[str, Any] = {
            HookInputField.TRANSCRIPT_PATH: str(path),
            HookInputField.TOOL_NAME: "Bash",
        }

        result = setup(hook_input, "session-1")

        assert result is not None
        assert result["pseudo_event"] == "nitpick"
        assert len(result["assistant_messages"]) == 1
        assert result["assistant_messages"][0]["content"] == "I completed the task"
        assert result["assistant_messages"][0]["uuid"] == "uuid-1"
        # Original fields preserved
        assert result[HookInputField.TOOL_NAME] == "Bash"

        path.unlink()

    def test_returns_none_when_no_new_messages(self) -> None:
        """Setup returns None when no new assistant messages since last audit."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)

        entries = [_assistant_entry("Old message", "uuid-1")]
        _write_transcript(path, entries)

        setup = NitpickSetup()
        hook_input: dict[str, Any] = {HookInputField.TRANSCRIPT_PATH: str(path)}

        # First call: returns messages
        result = setup(hook_input, "session-1")
        assert result is not None

        # Second call without new messages: returns None
        result = setup(hook_input, "session-1")
        assert result is None

        path.unlink()

    def test_returns_none_when_no_transcript_path(self) -> None:
        """Setup returns None when transcript_path is missing."""
        setup = NitpickSetup()
        hook_input: dict[str, Any] = {HookInputField.TOOL_NAME: "Bash"}

        result = setup(hook_input, "session-1")
        assert result is None

    def test_returns_none_when_transcript_missing(self) -> None:
        """Setup returns None when transcript file doesn't exist."""
        setup = NitpickSetup()
        hook_input: dict[str, Any] = {
            HookInputField.TRANSCRIPT_PATH: "/nonexistent/transcript.jsonl"
        }

        result = setup(hook_input, "session-1")
        assert result is None


class TestNitpickSetupIncremental:
    """Test incremental reading of transcripts."""

    def test_only_reads_new_messages(self) -> None:
        """Second call only returns messages added after first call."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)

        # Write initial message
        _write_transcript(path, [_assistant_entry("First message", "uuid-1")])

        setup = NitpickSetup()
        hook_input: dict[str, Any] = {HookInputField.TRANSCRIPT_PATH: str(path)}

        # First call reads first message
        result = setup(hook_input, "session-1")
        assert result is not None
        assert len(result["assistant_messages"]) == 1

        # Append new message
        with path.open("a") as f:
            f.write(json.dumps(_assistant_entry("Second message", "uuid-2")) + "\n")

        # Second call only returns new message
        result = setup(hook_input, "session-1")
        assert result is not None
        assert len(result["assistant_messages"]) == 1
        assert result["assistant_messages"][0]["content"] == "Second message"
        assert result["assistant_messages"][0]["uuid"] == "uuid-2"

        path.unlink()

    def test_filters_to_assistant_only(self) -> None:
        """Only assistant messages are included, human messages are filtered."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)

        entries = [
            _human_entry("User question", "uuid-h1"),
            _assistant_entry("Assistant answer", "uuid-a1"),
            _human_entry("Another question", "uuid-h2"),
        ]
        _write_transcript(path, entries)

        setup = NitpickSetup()
        hook_input: dict[str, Any] = {HookInputField.TRANSCRIPT_PATH: str(path)}

        result = setup(hook_input, "session-1")
        assert result is not None
        assert len(result["assistant_messages"]) == 1
        assert result["assistant_messages"][0]["content"] == "Assistant answer"

        path.unlink()

    def test_independent_sessions(self) -> None:
        """Different sessions have independent state."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)

        entries = [_assistant_entry("Shared message", "uuid-1")]
        _write_transcript(path, entries)

        setup = NitpickSetup()
        hook_input: dict[str, Any] = {HookInputField.TRANSCRIPT_PATH: str(path)}

        # Session A reads the message
        result_a = setup(hook_input, "session-a")
        assert result_a is not None
        assert len(result_a["assistant_messages"]) == 1

        # Session B also reads the message (independent state)
        result_b = setup(hook_input, "session-b")
        assert result_b is not None
        assert len(result_b["assistant_messages"]) == 1

        path.unlink()


class TestNitpickSetupState:
    """Test NitpickState management."""

    def test_state_tracks_byte_offset(self) -> None:
        """State byte offset advances with each read."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)

        _write_transcript(path, [_assistant_entry("Message one", "uuid-1")])

        setup = NitpickSetup()
        hook_input: dict[str, Any] = {HookInputField.TRANSCRIPT_PATH: str(path)}

        # After first read, state should have non-zero offset
        setup(hook_input, "session-1")
        state = setup.get_state("session-1")
        assert state is not None
        assert state.last_byte_offset > 0

        path.unlink()

    def test_state_tracks_last_uuid(self) -> None:
        """State records UUID of last audited message."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)

        _write_transcript(path, [_assistant_entry("Message", "uuid-abc")])

        setup = NitpickSetup()
        hook_input: dict[str, Any] = {HookInputField.TRANSCRIPT_PATH: str(path)}

        setup(hook_input, "session-1")
        state = setup.get_state("session-1")
        assert state is not None
        assert state.last_audited_uuid == "uuid-abc"

        path.unlink()

    def test_state_resets_on_truncated_file(self) -> None:
        """State resets if file is shorter than last offset (truncated/rotated)."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = Path(f.name)

        # Write a long message
        _write_transcript(path, [_assistant_entry("A" * 200, "uuid-1")])

        setup = NitpickSetup()
        hook_input: dict[str, Any] = {HookInputField.TRANSCRIPT_PATH: str(path)}

        setup(hook_input, "session-1")
        state = setup.get_state("session-1")
        assert state is not None
        old_offset = state.last_byte_offset

        # Truncate file with shorter content
        _write_transcript(path, [_assistant_entry("Short", "uuid-2")])
        assert path.stat().st_size < old_offset

        # Should still read the new content (offset reset)
        result = setup(hook_input, "session-1")
        assert result is not None
        assert len(result["assistant_messages"]) == 1
        assert result["assistant_messages"][0]["content"] == "Short"

        path.unlink()
