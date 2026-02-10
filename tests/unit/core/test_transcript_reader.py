"""Tests for TranscriptReader - JSONL transcript parser.

TDD RED phase: These tests define the expected API for TranscriptReader.
"""

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import ToolName
from claude_code_hooks_daemon.core.transcript_reader import (
    ToolUse,
    TranscriptMessage,
    TranscriptReader,
)


class TestTranscriptReaderInit:
    """Test TranscriptReader initialization."""

    def test_initial_state_not_loaded(self) -> None:
        """TranscriptReader should not be loaded initially."""
        reader = TranscriptReader()
        assert reader.is_loaded() is False

    def test_get_messages_empty_when_not_loaded(self) -> None:
        """get_messages() should return empty list when not loaded."""
        reader = TranscriptReader()
        assert reader.get_messages() == []


class TestTranscriptReaderLoad:
    """Test TranscriptReader.load()."""

    def test_load_marks_as_loaded(self, tmp_path: Path) -> None:
        """load() should mark reader as loaded."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.is_loaded() is True

    def test_load_nonexistent_file_stays_unloaded(self) -> None:
        """load() with nonexistent file should stay unloaded."""
        reader = TranscriptReader()
        reader.load("/nonexistent/file.jsonl")
        assert reader.is_loaded() is False

    def test_load_new_path_resets_cache(self, tmp_path: Path) -> None:
        """load() with new path should reset cached data."""
        # Create first transcript with a message
        transcript1 = tmp_path / "t1.jsonl"
        transcript1.write_text(
            json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n"
        )
        # Create second transcript with different content
        transcript2 = tmp_path / "t2.jsonl"
        transcript2.write_text(
            json.dumps({"type": "human", "message": {"content": "World"}}) + "\n"
        )

        reader = TranscriptReader()
        reader.load(str(transcript1))
        msgs1 = reader.get_messages()

        reader.load(str(transcript2))
        msgs2 = reader.get_messages()

        # Messages should be different after loading new file
        assert len(msgs1) > 0
        assert len(msgs2) > 0
        assert msgs1[0].content != msgs2[0].content

    def test_load_same_path_uses_cache(self, tmp_path: Path) -> None:
        """load() with same path should not re-parse."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs1 = reader.get_messages()

        # Load same path again
        reader.load(str(transcript))
        msgs2 = reader.get_messages()

        assert msgs1 == msgs2


class TestTranscriptReaderGetMessages:
    """Test TranscriptReader.get_messages()."""

    @pytest.fixture
    def reader_with_messages(self, tmp_path: Path) -> TranscriptReader:
        """Create reader loaded with sample messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "human", "message": {"content": "What is Python?"}}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": "Python is a programming language."},
                }
            ),
            json.dumps({"type": "human", "message": {"content": "Tell me more."}}),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_get_messages_returns_all(self, reader_with_messages: TranscriptReader) -> None:
        """get_messages() should return all parsed messages."""
        msgs = reader_with_messages.get_messages()
        assert len(msgs) == 3

    def test_get_messages_preserves_order(self, reader_with_messages: TranscriptReader) -> None:
        """get_messages() should preserve JSONL line order."""
        msgs = reader_with_messages.get_messages()
        assert msgs[0].role == "human"
        assert msgs[1].role == "assistant"
        assert msgs[2].role == "human"

    def test_get_messages_extracts_content(self, reader_with_messages: TranscriptReader) -> None:
        """get_messages() should extract message content."""
        msgs = reader_with_messages.get_messages()
        assert msgs[0].content == "What is Python?"
        assert msgs[1].content == "Python is a programming language."


class TestTranscriptReaderGetToolUses:
    """Test TranscriptReader.get_tool_uses()."""

    @pytest.fixture
    def reader_with_tools(self, tmp_path: Path) -> TranscriptReader:
        """Create reader loaded with tool use messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "human", "message": {"content": "Run ls"}}),
            json.dumps(
                {
                    "type": "tool_use",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls -la"},
                }
            ),
            json.dumps(
                {
                    "type": "tool_result",
                    "tool_name": "Bash",
                    "output": "file1.txt\nfile2.txt",
                }
            ),
            json.dumps(
                {
                    "type": "tool_use",
                    "tool_name": "Read",
                    "tool_input": {"file_path": "/tmp/test.py"},
                }
            ),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_get_tool_uses_returns_tool_entries(self, reader_with_tools: TranscriptReader) -> None:
        """get_tool_uses() should return tool_use entries."""
        tools = reader_with_tools.get_tool_uses()
        assert len(tools) == 2

    def test_get_tool_uses_extracts_tool_name(self, reader_with_tools: TranscriptReader) -> None:
        """get_tool_uses() should extract tool names."""
        tools = reader_with_tools.get_tool_uses()
        assert tools[0].tool_name == ToolName.BASH
        assert tools[1].tool_name == ToolName.READ

    def test_get_tool_uses_extracts_tool_input(self, reader_with_tools: TranscriptReader) -> None:
        """get_tool_uses() should extract tool input."""
        tools = reader_with_tools.get_tool_uses()
        assert tools[0].tool_input == {"command": "ls -la"}


class TestTranscriptReaderGetLastNMessages:
    """Test TranscriptReader.get_last_n_messages()."""

    @pytest.fixture
    def reader_with_5_messages(self, tmp_path: Path) -> TranscriptReader:
        """Create reader with 5 messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = []
        for i in range(5):
            role = "human" if i % 2 == 0 else "assistant"
            lines.append(json.dumps({"type": role, "message": {"content": f"Message {i}"}}))
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_get_last_n_returns_n_messages(self, reader_with_5_messages: TranscriptReader) -> None:
        """get_last_n_messages() should return last N messages."""
        msgs = reader_with_5_messages.get_last_n_messages(3)
        assert len(msgs) == 3

    def test_get_last_n_returns_latest(self, reader_with_5_messages: TranscriptReader) -> None:
        """get_last_n_messages() should return the most recent messages."""
        msgs = reader_with_5_messages.get_last_n_messages(2)
        assert msgs[0].content == "Message 3"
        assert msgs[1].content == "Message 4"

    def test_get_last_n_returns_all_if_n_exceeds(
        self, reader_with_5_messages: TranscriptReader
    ) -> None:
        """get_last_n_messages(100) should return all messages."""
        msgs = reader_with_5_messages.get_last_n_messages(100)
        assert len(msgs) == 5


class TestTranscriptReaderSearchMessages:
    """Test TranscriptReader.search_messages()."""

    @pytest.fixture
    def reader_with_searchable(self, tmp_path: Path) -> TranscriptReader:
        """Create reader with searchable messages."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"type": "human", "message": {"content": "Fix the authentication bug"}}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": "I'll look at the auth module."},
                }
            ),
            json.dumps({"type": "human", "message": {"content": "Now add unit tests"}}),
        ]
        transcript.write_text("\n".join(lines) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        return reader

    def test_search_finds_matching_messages(self, reader_with_searchable: TranscriptReader) -> None:
        """search_messages() should find messages containing pattern."""
        results = reader_with_searchable.search_messages("auth")
        assert len(results) == 2  # "authentication" and "auth module"

    def test_search_case_insensitive(self, reader_with_searchable: TranscriptReader) -> None:
        """search_messages() should be case-insensitive."""
        results = reader_with_searchable.search_messages("FIX")
        assert len(results) == 1

    def test_search_no_results(self, reader_with_searchable: TranscriptReader) -> None:
        """search_messages() should return empty for no matches."""
        results = reader_with_searchable.search_messages("database")
        assert results == []


class TestTranscriptReaderEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_malformed_json_lines(self, tmp_path: Path) -> None:
        """Reader should skip malformed JSON lines."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"type": "human", "message": {"content": "Valid"}})
            + "\n"
            + "not valid json\n"
            + json.dumps({"type": "assistant", "message": {"content": "Also valid"}})
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 2

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        """Reader should handle empty transcript file."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        reader = TranscriptReader()
        reader.load(str(transcript))
        assert reader.get_messages() == []
        assert reader.is_loaded() is True

    def test_handles_lines_without_type(self, tmp_path: Path) -> None:
        """Reader should skip lines without 'type' field."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"data": "no type field"})
            + "\n"
            + json.dumps({"type": "human", "message": {"content": "Has type"}})
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1


class TestTranscriptReaderParsingEdgeCases:
    """Test edge cases in _parse method for missing coverage."""

    def test_handles_non_dict_json_lines(self, tmp_path: Path) -> None:
        """Reader should skip JSON lines that parse to non-dict (e.g., list, string)."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps([1, 2, 3])
            + "\n"
            + json.dumps("just a string")
            + "\n"
            + json.dumps({"type": "human", "message": {"content": "Valid"}})
            + "\n"
        )
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_messages()
        assert len(msgs) == 1
        assert msgs[0].content == "Valid"

    def test_get_last_n_messages_with_zero_returns_empty(self, tmp_path: Path) -> None:
        """get_last_n_messages(0) should return empty list."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_last_n_messages(0)
        assert msgs == []

    def test_get_last_n_messages_with_negative_returns_empty(self, tmp_path: Path) -> None:
        """get_last_n_messages(-1) should return empty list."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "human", "message": {"content": "Hello"}}) + "\n")
        reader = TranscriptReader()
        reader.load(str(transcript))
        msgs = reader.get_last_n_messages(-1)
        assert msgs == []


class TestTranscriptMessage:
    """Test TranscriptMessage dataclass."""

    def test_message_fields(self) -> None:
        """TranscriptMessage should store role and content."""
        msg = TranscriptMessage(role="human", content="Hello", raw={})
        assert msg.role == "human"
        assert msg.content == "Hello"


class TestToolUse:
    """Test ToolUse dataclass."""

    def test_tool_use_fields(self) -> None:
        """ToolUse should store tool_name and tool_input."""
        tool = ToolUse(tool_name=ToolName.BASH, tool_input={"command": "ls"}, raw={})
        assert tool.tool_name == ToolName.BASH
        assert tool.tool_input == {"command": "ls"}
